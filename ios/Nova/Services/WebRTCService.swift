import Foundation
import WebRTC

final class WebRTCService: NSObject, ObservableObject {

    // MARK: - Published tracks for SwiftUI video views

    @Published var localVideoTrack: RTCVideoTrack?
    @Published var remoteVideoTrack: RTCVideoTrack?

    // MARK: - Callbacks (set by AppState)

    var onLocalOffer: (([String: Any]) -> Void)?
    var onLocalAnswer: (([String: Any]) -> Void)?
    var onICECandidate: (([String: Any]) -> Void)?
    var onConnected: (() -> Void)?
    var onDisconnected: (() -> Void)?

    // MARK: - Private state

    private var peerConnection: RTCPeerConnection?
    private var videoCapturer: RTCCameraVideoCapturer?
    private var audioTrack: RTCAudioTrack?
    private var iceRestarts = 0
    private var isInitiator = false

    // MARK: - Factory (shared, heavy to create)

    private static let factory: RTCPeerConnectionFactory = {
        RTCInitializeSSL()
        return RTCPeerConnectionFactory(
            encoderFactory: RTCDefaultVideoEncoderFactory(),
            decoderFactory: RTCDefaultVideoDecoderFactory()
        )
    }()

    private var rtcConfig: RTCConfiguration {
        let config = RTCConfiguration()
        var servers: [RTCIceServer] = Config.stunServers.map {
            RTCIceServer(urlStrings: [$0])
        }
        servers += Config.turnServers.map {
            RTCIceServer(urlStrings: [$0.url], username: $0.username, credential: $0.credential)
        }
        config.iceServers = servers
        config.sdpSemantics = .unifiedPlan
        config.iceCandidatePoolSize = 5
        return config
    }

    // MARK: - Local media

    func startLocalStream(completion: @escaping (Bool) -> Void) {
        let audioConstraints = RTCMediaConstraints(mandatoryConstraints: nil, optionalConstraints: nil)
        let audioSource = Self.factory.audioSource(with: audioConstraints)
        audioTrack = Self.factory.audioTrack(with: audioSource, trackId: "audio0")

        let videoSource = Self.factory.videoSource()
        videoCapturer = RTCCameraVideoCapturer(delegate: videoSource)

        guard let camera = RTCCameraVideoCapturer.captureDevices()
            .first(where: { $0.position == .front })
                ?? RTCCameraVideoCapturer.captureDevices().first
        else {
            completion(false)
            return
        }

        let targetFormat = camera.formats
            .filter {
                let dims = CMVideoFormatDescriptionGetDimensions($0.formatDescription)
                return dims.width <= 640
            }
            .sorted {
                let d1 = CMVideoFormatDescriptionGetDimensions($0.formatDescription)
                let d2 = CMVideoFormatDescriptionGetDimensions($1.formatDescription)
                return d1.width * d1.height > d2.width * d2.height
            }
            .first ?? camera.formats.first!

        let fps = targetFormat.videoSupportedFrameRateRanges
            .compactMap { min(Int($0.maxFrameRate), 30) }
            .max() ?? 30

        videoCapturer?.startCapture(with: camera, format: targetFormat, fps: fps) { [weak self] error in
            guard let self else { return }
            if error != nil {
                completion(false)
                return
            }
            let track = Self.factory.videoTrack(with: videoSource, trackId: "video0")
            DispatchQueue.main.async {
                self.localVideoTrack = track
            }
            completion(true)
        }
    }

    // MARK: - Peer connection lifecycle

    func setupPeer(isInitiator: Bool) {
        closePeer()
        self.isInitiator = isInitiator
        iceRestarts = 0

        let constraints = RTCMediaConstraints(
            mandatoryConstraints: [
                "OfferToReceiveAudio": "true",
                "OfferToReceiveVideo": "true",
            ],
            optionalConstraints: nil
        )

        peerConnection = Self.factory.peerConnection(with: rtcConfig, constraints: constraints, delegate: self)

        if let audio = audioTrack {
            peerConnection?.add(audio, streamIds: ["stream0"])
        }
        if let video = localVideoTrack {
            peerConnection?.add(video, streamIds: ["stream0"])
        }

        if isInitiator {
            createOffer()
        }
    }

    // MARK: - Incoming signaling

    func handleOffer(data: [String: Any]) {
        guard let pc = peerConnection,
              let sdpString = data["sdp"] as? String,
              let typeString = data["type"] as? String else { return }

        let sdp = RTCSessionDescription(type: sdpType(from: typeString), sdp: sdpString)
        pc.setRemoteDescription(sdp) { [weak self] error in
            if error == nil { self?.createAnswer() }
        }
    }

    func handleAnswer(data: [String: Any]) {
        guard let pc = peerConnection,
              let sdpString = data["sdp"] as? String,
              let typeString = data["type"] as? String else { return }

        let sdp = RTCSessionDescription(type: sdpType(from: typeString), sdp: sdpString)
        pc.setRemoteDescription(sdp) { _ in }
    }

    func handleICE(data: [String: Any]) {
        guard let pc = peerConnection,
              let candidate = data["candidate"] as? String,
              let sdpMLineIndex = data["sdpMLineIndex"] as? Int32 else { return }

        let sdpMid = data["sdpMid"] as? String
        let ice = RTCIceCandidate(sdp: candidate, sdpMLineIndex: sdpMLineIndex, sdpMid: sdpMid)
        pc.add(ice) { _ in }
    }

    // MARK: - Toggles

    func toggleCamera(enabled: Bool) {
        localVideoTrack?.isEnabled = enabled
    }

    func toggleMic(enabled: Bool) {
        audioTrack?.isEnabled = enabled
    }

    // MARK: - Cleanup

    func closePeer() {
        peerConnection?.close()
        peerConnection = nil
        DispatchQueue.main.async { self.remoteVideoTrack = nil }
        iceRestarts = 0
    }

    func cleanup() {
        closePeer()
        videoCapturer?.stopCapture()
        videoCapturer = nil
        DispatchQueue.main.async {
            self.localVideoTrack = nil
        }
        audioTrack = nil
    }

    // MARK: - Private helpers

    private func createOffer() {
        let constraints = RTCMediaConstraints(
            mandatoryConstraints: [
                "OfferToReceiveAudio": "true",
                "OfferToReceiveVideo": "true",
            ],
            optionalConstraints: nil
        )

        peerConnection?.offer(for: constraints) { [weak self] sdp, error in
            guard let self, let sdp, error == nil else { return }
            self.peerConnection?.setLocalDescription(sdp) { error in
                guard error == nil else { return }
                self.onLocalOffer?([
                    "type": self.sdpTypeString(sdp.type),
                    "sdp": sdp.sdp,
                ])
            }
        }
    }

    private func createAnswer() {
        let constraints = RTCMediaConstraints(
            mandatoryConstraints: [
                "OfferToReceiveAudio": "true",
                "OfferToReceiveVideo": "true",
            ],
            optionalConstraints: nil
        )

        peerConnection?.answer(for: constraints) { [weak self] sdp, error in
            guard let self, let sdp, error == nil else { return }
            self.peerConnection?.setLocalDescription(sdp) { error in
                guard error == nil else { return }
                self.onLocalAnswer?([
                    "type": self.sdpTypeString(sdp.type),
                    "sdp": sdp.sdp,
                ])
            }
        }
    }

    private func tryICERestart() {
        guard isInitiator, let pc = peerConnection else { return }

        let constraints = RTCMediaConstraints(
            mandatoryConstraints: [
                "IceRestart": "true",
                "OfferToReceiveAudio": "true",
                "OfferToReceiveVideo": "true",
            ],
            optionalConstraints: nil
        )

        pc.offer(for: constraints) { [weak self] sdp, error in
            guard let self, let sdp, error == nil else { return }
            pc.setLocalDescription(sdp) { error in
                guard error == nil else { return }
                self.onLocalOffer?([
                    "type": self.sdpTypeString(sdp.type),
                    "sdp": sdp.sdp,
                ])
            }
        }
    }

    private func sdpType(from string: String) -> RTCSdpType {
        switch string {
        case "offer":   return .offer
        case "answer":  return .answer
        case "pranswer": return .prAnswer
        default:        return .offer
        }
    }

    private func sdpTypeString(_ type: RTCSdpType) -> String {
        switch type {
        case .offer:    return "offer"
        case .answer:   return "answer"
        case .prAnswer: return "pranswer"
        case .rollback: return "rollback"
        @unknown default: return "offer"
        }
    }
}

// MARK: - RTCPeerConnectionDelegate

extension WebRTCService: RTCPeerConnectionDelegate {

    func peerConnection(_ peerConnection: RTCPeerConnection, didChange stateChanged: RTCSignalingState) {}

    func peerConnection(_ peerConnection: RTCPeerConnection, didAdd stream: RTCMediaStream) {
        if let videoTrack = stream.videoTracks.first {
            DispatchQueue.main.async { [weak self] in
                self?.remoteVideoTrack = videoTrack
                self?.onConnected?()
            }
        }
    }

    func peerConnection(_ peerConnection: RTCPeerConnection, didRemove stream: RTCMediaStream) {}

    func peerConnectionShouldNegotiate(_ peerConnection: RTCPeerConnection) {}

    func peerConnection(_ peerConnection: RTCPeerConnection, didChange newState: RTCIceConnectionState) {
        switch newState {
        case .connected, .completed:
            DispatchQueue.main.async { [weak self] in
                self?.onConnected?()
            }

        case .disconnected:
            DispatchQueue.main.asyncAfter(deadline: .now() + 3) { [weak self] in
                guard let self,
                      self.peerConnection?.iceConnectionState == .disconnected,
                      self.iceRestarts < Config.maxICERestarts else { return }
                self.iceRestarts += 1
                self.tryICERestart()
            }

        case .failed:
            if iceRestarts < Config.maxICERestarts {
                iceRestarts += 1
                tryICERestart()
            } else {
                DispatchQueue.main.async { [weak self] in
                    self?.onDisconnected?()
                }
            }

        default:
            break
        }
    }

    func peerConnection(_ peerConnection: RTCPeerConnection, didChange newState: RTCIceGatheringState) {}

    func peerConnection(_ peerConnection: RTCPeerConnection, didGenerate candidate: RTCIceCandidate) {
        onICECandidate?([
            "candidate": candidate.sdp,
            "sdpMLineIndex": candidate.sdpMLineIndex,
            "sdpMid": candidate.sdpMid ?? "",
        ])
    }

    func peerConnection(_ peerConnection: RTCPeerConnection, didRemove candidates: [RTCIceCandidate]) {}

    func peerConnection(_ peerConnection: RTCPeerConnection, didOpen dataChannel: RTCDataChannel) {}
}
