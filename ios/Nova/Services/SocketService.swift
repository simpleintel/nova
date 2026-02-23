import Foundation
import SocketIO

final class SocketService: ObservableObject {

    @Published var onlineCount: Int = 0
    @Published var isConnected: Bool = false

    // MARK: - Callbacks (set by AppState)

    var onMatched: (([String: Any]) -> Void)?
    var onPartnerDisconnected: (() -> Void)?
    var onWaiting: (() -> Void)?
    var onOffer: (([String: Any]) -> Void)?
    var onAnswer: (([String: Any]) -> Void)?
    var onICE: (([String: Any]) -> Void)?
    var onForceLogout: (() -> Void)?

    private var manager: SocketManager?
    private var socket: SocketIOClient?

    // MARK: - Connection

    func connect() {
        guard socket == nil, let url = URL(string: Config.serverURL) else { return }

        // Forward session cookies so the server recognises us
        let cookies = HTTPCookieStorage.shared.cookies(for: url) ?? []

        manager = SocketManager(socketURL: url, config: [
            .log(false),
            .compress,
            .forceWebsockets(true),
            .reconnects(true),
            .reconnectAttempts(-1),
            .reconnectWait(1),
            .reconnectWaitMax(10),
            .cookies(cookies),
        ])

        socket = manager?.defaultSocket
        bindEvents()
        socket?.connect()
    }

    func disconnect() {
        socket?.disconnect()
        socket = nil
        manager?.disconnect()
        manager = nil
        DispatchQueue.main.async { self.isConnected = false }
    }

    // MARK: - Emitters

    func joinQueue() {
        socket?.emit("q")
    }

    func skip() {
        socket?.emit("s")
    }

    func sendOffer(_ sdp: [String: Any]) {
        socket?.emit("offer", sdp)
    }

    func sendAnswer(_ sdp: [String: Any]) {
        socket?.emit("answer", sdp)
    }

    func sendICE(_ candidate: [String: Any]) {
        socket?.emit("ice", candidate)
    }

    // MARK: - Event binding

    private func bindEvents() {
        guard let socket else { return }

        socket.on(clientEvent: .connect) { [weak self] _, _ in
            DispatchQueue.main.async { self?.isConnected = true }
        }

        socket.on(clientEvent: .disconnect) { [weak self] _, _ in
            DispatchQueue.main.async { self?.isConnected = false }
        }

        socket.on("oc") { [weak self] data, _ in
            if let count = data.first as? Int {
                DispatchQueue.main.async { self?.onlineCount = count }
            }
        }

        socket.on("w") { [weak self] _, _ in
            self?.onWaiting?()
        }

        socket.on("m") { [weak self] data, _ in
            if let dict = data.first as? [String: Any] {
                self?.onMatched?(dict)
            }
        }

        socket.on("pd") { [weak self] _, _ in
            self?.onPartnerDisconnected?()
        }

        socket.on("offer") { [weak self] data, _ in
            if let dict = data.first as? [String: Any] {
                self?.onOffer?(dict)
            }
        }

        socket.on("answer") { [weak self] data, _ in
            if let dict = data.first as? [String: Any] {
                self?.onAnswer?(dict)
            }
        }

        socket.on("ice") { [weak self] data, _ in
            if let dict = data.first as? [String: Any] {
                self?.onICE?(dict)
            }
        }

        socket.on("force_logout") { [weak self] _, _ in
            self?.onForceLogout?()
        }
    }
}
