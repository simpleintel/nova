# Nova iOS App

Native iPhone app for Nova — a P2P anonymous video chat platform. Built with SwiftUI, WebRTC, Socket.IO, and Google Sign-In.

## Architecture

```
Nova/
├── NovaApp.swift           # App entry point, Google Sign-In config
├── ContentView.swift       # Root navigation (switches between screens)
├── Info.plist              # Permissions (camera, microphone)
├── Assets.xcassets/        # App icon, accent color
├── Models/
│   ├── User.swift          # NovaUser model
│   └── AppState.swift      # Central state management (ObservableObject)
├── Views/
│   ├── AuthView.swift      # Login screen (Google Sign-In, age/TOS checks)
│   ├── NicknameView.swift  # Nickname prompt for new users
│   ├── LobbyView.swift     # Main lobby (start chat, online count, GDPR)
│   ├── VideoChatView.swift # Full-screen video chat with controls
│   ├── ReportSheet.swift   # Report user modal
│   └── VideoView.swift     # UIViewRepresentable wrapper for RTCMTLVideoView
└── Services/
    ├── Constants.swift     # Server URL, Google Client ID, STUN/TURN config
    ├── APIService.swift    # REST API calls (auth, profile, reports, GDPR)
    ├── SocketService.swift # Socket.IO real-time connection
    └── WebRTCService.swift # WebRTC peer connection, camera, signaling
```

## Prerequisites

- **macOS** with **Xcode 15+** installed
- **[XcodeGen](https://github.com/yonaskolb/XcodeGen)** (generates the .xcodeproj)
- A running Nova backend server (the Flask app in the repo root)
- A Google Cloud project with OAuth 2.0 credentials

## Setup

### 1. Install XcodeGen

```bash
brew install xcodegen
```

### 2. Configure the app

Edit `Nova/Services/Constants.swift`:

```swift
enum Config {
    static let serverURL = "https://your-nova-server.com"  // Your backend URL
    static let googleClientID = "YOUR_IOS_CLIENT_ID"       // From Google Cloud Console
    ...
}
```

### 3. Set up Google Sign-In

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Select your project (same one used for the web app)
3. Go to **APIs & Services → Credentials**
4. Create an **OAuth 2.0 Client ID** for **iOS**
   - Bundle ID: `com.simpleintelligence.nova`
5. Copy the **iOS Client ID** into `Constants.swift`
6. Update `Info.plist` — replace `YOUR_IOS_CLIENT_ID` in the URL scheme:
   ```
   com.googleusercontent.apps.YOUR_IOS_CLIENT_ID
   ```

**Important:** The backend verifies the `aud` claim in the Google ID token. You have two options:

- **Option A (recommended):** In the Google Cloud Console, when creating the iOS OAuth client, note the client ID. Then update your backend's `GOOGLE_CLIENT_ID` env var to accept both web and iOS client IDs, OR
- **Option B:** Configure the iOS client to use the web client ID as the server client ID (see [Google docs](https://developers.google.com/identity/sign-in/ios/backend-auth))

### 4. Generate the Xcode project

```bash
cd ios/
xcodegen generate
```

This creates `Nova.xcodeproj` from `project.yml`.

### 5. Open in Xcode

```bash
open Nova.xcodeproj
```

Xcode will automatically resolve Swift Package Manager dependencies:
- **SocketIO** (socket.io-client-swift)
- **GoogleSignIn** (GoogleSignIn-iOS)
- **WebRTC** (webrtc-swift-package)

### 6. Build & Run

1. Select your target device (iPhone 14+ recommended)
2. Set your **Development Team** in Signing & Capabilities
3. Press **Cmd+R** to build and run

> **Note:** WebRTC camera capture does not work in the iOS Simulator. You must test on a physical iPhone.

## Backend Compatibility

This iOS app connects to the same Nova Flask backend. The communication protocol is identical:

| Component    | Protocol                          |
|--------------|-----------------------------------|
| Auth         | REST API (`/api/auth/google`)     |
| Profile      | REST API (`/api/profile`)         |
| Real-time    | Socket.IO (matching, signaling)   |
| Video/Audio  | WebRTC (peer-to-peer)             |
| Reports      | REST API (`/api/report`)          |
| GDPR         | REST API (`/api/my-data`, etc.)   |

Socket events are the same as the web client: `q` (queue), `s` (skip), `m` (matched), `pd` (partner disconnected), `offer`/`answer`/`ice` (WebRTC signaling).

## App Screens

1. **Auth** — Google Sign-In with age confirmation and TOS acceptance
2. **Nickname** — First-time users set a display nickname
3. **Lobby** — Shows online count, start button, data export, account deletion
4. **Video Chat** — Full-screen P2P video with camera/mic toggles, skip, report, disconnect

## Features

- Native SwiftUI interface optimized for iPhone
- WebRTC peer-to-peer video (no server relay for media)
- Automatic ICE restart on connection drops (up to 3 attempts)
- Camera/microphone toggle controls
- User reporting with reason categories
- GDPR data export and account self-deletion
- Session persistence via HTTP cookies
- Smooth screen transitions with animations
