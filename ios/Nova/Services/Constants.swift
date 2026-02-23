import Foundation

enum Config {
    /// Base URL of your Nova backend server (no trailing slash).
    /// Change this to your deployed server URL before building.
    static let serverURL = "https://your-nova-server.com"

    /// Google OAuth *iOS* client ID from Google Cloud Console.
    /// Create one under APIs & Services → Credentials → OAuth 2.0 Client IDs → iOS.
    static let googleClientID = "YOUR_IOS_CLIENT_ID"

    /// STUN servers for WebRTC ICE gathering.
    static let stunServers = [
        "stun:stun.l.google.com:19302",
        "stun:stun1.l.google.com:19302",
    ]

    /// TURN servers for relay when direct P2P fails.
    static let turnServers: [(url: String, username: String, credential: String)] = [
        ("turn:openrelay.metered.ca:80", "openrelayproject", "openrelayproject"),
        ("turn:openrelay.metered.ca:443", "openrelayproject", "openrelayproject"),
        ("turn:openrelay.metered.ca:443?transport=tcp", "openrelayproject", "openrelayproject"),
    ]

    static let maxICERestarts = 3
}
