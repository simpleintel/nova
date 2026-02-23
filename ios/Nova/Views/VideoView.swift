import SwiftUI
import WebRTC

/// Wraps `RTCMTLVideoView` (Metal-based) for use in SwiftUI.
struct VideoView: UIViewRepresentable {
    let track: RTCVideoTrack
    var mirror: Bool = false

    func makeUIView(context: Context) -> RTCMTLVideoView {
        let view = RTCMTLVideoView(frame: .zero)
        view.videoContentMode = .scaleAspectFill
        view.clipsToBounds = true
        if mirror {
            view.transform = CGAffineTransform(scaleX: -1, y: 1)
        }
        track.add(view)
        context.coordinator.currentTrack = track
        context.coordinator.view = view
        return view
    }

    func updateUIView(_ uiView: RTCMTLVideoView, context: Context) {
        if context.coordinator.currentTrack !== track {
            context.coordinator.currentTrack?.remove(uiView)
            track.add(uiView)
            context.coordinator.currentTrack = track
        }
    }

    static func dismantleUIView(_ uiView: RTCMTLVideoView, coordinator: Coordinator) {
        coordinator.currentTrack?.remove(uiView)
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    class Coordinator {
        weak var currentTrack: RTCVideoTrack?
        weak var view: RTCMTLVideoView?
    }
}
