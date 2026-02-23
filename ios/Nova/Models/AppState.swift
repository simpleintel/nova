import SwiftUI
import Combine

enum AppScreen: Equatable {
    case auth
    case nickname
    case lobby
    case chat
}

@MainActor
final class AppState: ObservableObject {

    // MARK: - Published state

    @Published var screen: AppScreen = .auth
    @Published var user: NovaUser?
    @Published var onlineCount: Int = 0
    @Published var isMatched: Bool = false
    @Published var isSearching: Bool = false
    @Published var statusText: String = ""
    @Published var statusSubtext: String = ""
    @Published var partnerNickname: String = ""
    @Published var showReport: Bool = false
    @Published var cameraEnabled: Bool = true
    @Published var micEnabled: Bool = true
    @Published var errorMessage: String = ""

    // MARK: - Services

    let socketService = SocketService()
    let webRTCService = WebRTCService()
    let apiService = APIService()

    private var cancellables = Set<AnyCancellable>()

    // MARK: - Init

    init() {
        setupBindings()
        checkExistingSession()
    }

    // MARK: - Bindings between services and published state

    private func setupBindings() {
        socketService.$onlineCount
            .receive(on: DispatchQueue.main)
            .assign(to: &$onlineCount)

        socketService.onMatched = { [weak self] data in
            Task { @MainActor in self?.handleMatched(data: data) }
        }

        socketService.onPartnerDisconnected = { [weak self] in
            Task { @MainActor in self?.handlePartnerDisconnected() }
        }

        socketService.onWaiting = { [weak self] in
            Task { @MainActor in
                self?.isSearching = true
                self?.isMatched = false
                self?.statusText = "Finding a discussion partner…"
                self?.statusSubtext = "Matching you with someone new"
            }
        }

        socketService.onOffer = { [weak self] data in
            self?.webRTCService.handleOffer(data: data)
        }

        socketService.onAnswer = { [weak self] data in
            self?.webRTCService.handleAnswer(data: data)
        }

        socketService.onICE = { [weak self] data in
            self?.webRTCService.handleICE(data: data)
        }

        socketService.onForceLogout = { [weak self] in
            Task { @MainActor in
                self?.user = nil
                self?.screen = .auth
                self?.socketService.disconnect()
                self?.webRTCService.cleanup()
            }
        }

        // WebRTC → Socket forwarding
        webRTCService.onLocalOffer = { [weak self] sdp in
            self?.socketService.sendOffer(sdp)
        }

        webRTCService.onLocalAnswer = { [weak self] sdp in
            self?.socketService.sendAnswer(sdp)
        }

        webRTCService.onICECandidate = { [weak self] candidate in
            self?.socketService.sendICE(candidate)
        }

        webRTCService.onConnected = { [weak self] in
            Task { @MainActor in
                self?.isMatched = true
                self?.isSearching = false
                self?.statusText = ""
            }
        }

        webRTCService.onDisconnected = { [weak self] in
            Task { @MainActor in self?.handlePartnerDisconnected() }
        }
    }

    // MARK: - Session

    func checkExistingSession() {
        Task {
            if let user = await apiService.checkSession() {
                self.user = user
                if user.nickname.isEmpty {
                    screen = .nickname
                } else {
                    screen = .lobby
                    socketService.connect()
                }
            }
        }
    }

    // MARK: - Auth

    func loginWithGoogle(credential: String, tosAccepted: Bool) {
        Task {
            let result = await apiService.googleAuth(credential: credential, tosAccepted: tosAccepted)
            switch result {
            case .success(let user):
                self.user = user
                errorMessage = ""
                if user.nickname.isEmpty {
                    screen = .nickname
                } else {
                    screen = .lobby
                    socketService.connect()
                }
            case .failure(let error):
                errorMessage = error.localizedDescription
            }
        }
    }

    func setNickname(_ nickname: String) {
        Task {
            let result = await apiService.setNickname(nickname)
            switch result {
            case .success(let nick):
                user?.nickname = nick
                errorMessage = ""
                screen = .lobby
                socketService.connect()
            case .failure(let error):
                errorMessage = error.localizedDescription
            }
        }
    }

    func logout() {
        Task {
            await apiService.logout()
            user = nil
            socketService.disconnect()
            webRTCService.cleanup()
            screen = .auth
        }
    }

    // MARK: - Chat lifecycle

    func startChat() {
        screen = .chat
        isSearching = true
        cameraEnabled = true
        micEnabled = true
        statusText = "Starting camera…"
        statusSubtext = "Requesting access…"

        webRTCService.startLocalStream { [weak self] success in
            Task { @MainActor in
                guard let self else { return }
                if success {
                    self.statusText = "Finding a discussion partner…"
                    self.statusSubtext = "Matching you with someone new"
                    self.socketService.joinQueue()
                } else {
                    self.statusText = "Camera access required"
                    self.statusSubtext = "Go to Settings → Nova → Allow Camera & Microphone"
                }
            }
        }
    }

    func skip() {
        isMatched = false
        isSearching = true
        partnerNickname = ""
        statusText = "Finding a discussion partner…"
        statusSubtext = "Matching you with someone new"
        webRTCService.closePeer()
        socketService.skip()
    }

    func disconnect() {
        socketService.skip()
        isMatched = false
        isSearching = false
        partnerNickname = ""
        webRTCService.cleanup()
        screen = .lobby
    }

    // MARK: - Toggles

    func toggleCamera() {
        cameraEnabled.toggle()
        webRTCService.toggleCamera(enabled: cameraEnabled)
    }

    func toggleMic() {
        micEnabled.toggle()
        webRTCService.toggleMic(enabled: micEnabled)
    }

    // MARK: - Reporting

    func submitReport(reason: String, details: String) {
        Task {
            let result = await apiService.report(reason: reason, details: details)
            switch result {
            case .success:
                showReport = false
            case .failure(let error):
                errorMessage = error.localizedDescription
            }
        }
    }

    // MARK: - Private

    private func handleMatched(data: [String: Any]) {
        let isInitiator = data["init"] as? Bool ?? false
        let partnerNick = data["partner_nick"] as? String ?? ""

        isSearching = true
        statusText = "Matched! Connecting video…"
        statusSubtext = "Establishing peer-to-peer link"
        partnerNickname = partnerNick

        webRTCService.setupPeer(isInitiator: isInitiator)
    }

    private func handlePartnerDisconnected() {
        isMatched = false
        partnerNickname = ""
        webRTCService.closePeer()
        statusText = "Partner left"
        statusSubtext = "Finding someone new…"
        isSearching = true

        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
            self?.socketService.joinQueue()
        }
    }
}
