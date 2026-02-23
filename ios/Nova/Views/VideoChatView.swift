import SwiftUI
import WebRTC

struct VideoChatView: View {
    @EnvironmentObject var appState: AppState
    @State private var showReport = false

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()

            VStack(spacing: 0) {
                videoArea
                controlBar
            }
        }
        .sheet(isPresented: $showReport) {
            ReportSheet()
                .environmentObject(appState)
        }
        .statusBarHidden(true)
    }

    // MARK: - Video area

    private var videoArea: some View {
        ZStack {
            // Remote video (full screen)
            if let remoteTrack = appState.webRTCService.remoteVideoTrack {
                VideoView(track: remoteTrack)
                    .ignoresSafeArea()
            } else {
                Color(white: 0.04)
            }

            // Overlay HUD
            VStack {
                topBar
                Spacer()
                bottomOverlay
            }

            // Local video picture-in-picture
            localPIP

            // Status overlay (searching / connecting)
            if !appState.statusText.isEmpty {
                statusOverlay
            }
        }
        .frame(maxHeight: .infinity)
    }

    private var topBar: some View {
        HStack {
            Text("Nova")
                .font(.system(size: 13, weight: .bold))
                .foregroundColor(Color(.systemGray))
                .padding(.horizontal, 12)
                .padding(.vertical, 4)
                .background(Color.black.opacity(0.6))
                .clipShape(Capsule())

            Spacer()

            HStack(spacing: 5) {
                Circle()
                    .fill(Color.white)
                    .frame(width: 6, height: 6)
                Text("\(appState.onlineCount) online")
                    .font(.system(size: 12))
                    .foregroundColor(Color(.systemGray))
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 4)
            .background(Color.black.opacity(0.6))
            .clipShape(Capsule())
        }
        .padding(.horizontal, 14)
        .padding(.top, 54)
    }

    @ViewBuilder
    private var bottomOverlay: some View {
        if !appState.partnerNickname.isEmpty && appState.isMatched {
            HStack {
                Text(appState.partnerNickname)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundColor(.white)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 4)
                    .background(.ultraThinMaterial, in: Capsule())
                Spacer()
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 16)
        }
    }

    private var localPIP: some View {
        VStack {
            Spacer()
            HStack {
                Spacer()
                if let localTrack = appState.webRTCService.localVideoTrack {
                    VideoView(track: localTrack, mirror: true)
                        .frame(width: 120, height: 90)
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                        .overlay(
                            RoundedRectangle(cornerRadius: 10)
                                .stroke(Color.white.opacity(0.15), lineWidth: 2)
                        )
                }
            }
            .padding(.trailing, 14)
            .padding(.bottom, 14)
        }
    }

    private var statusOverlay: some View {
        VStack(spacing: 6) {
            if appState.isSearching {
                ProgressView()
                    .progressViewStyle(CircularProgressViewStyle(tint: .white))
                    .scaleEffect(1.3)
                    .padding(.bottom, 8)
            }

            Text(appState.statusText)
                .font(.system(size: 17, weight: .semibold))
                .foregroundColor(.white)

            if !appState.statusSubtext.isEmpty {
                Text(appState.statusSubtext)
                    .font(.system(size: 13))
                    .foregroundColor(Color(.systemGray))
            }
        }
    }

    // MARK: - Control bar

    private var controlBar: some View {
        HStack(spacing: 14) {
            CircleButton(
                icon: appState.cameraEnabled ? "video.fill" : "video.slash.fill",
                style: appState.cameraEnabled ? .dark : .light
            ) {
                appState.toggleCamera()
            }

            CircleButton(
                icon: appState.micEnabled ? "mic.fill" : "mic.slash.fill",
                style: appState.micEnabled ? .dark : .light
            ) {
                appState.toggleMic()
            }

            CircleButton(icon: "forward.fill", style: .dark) {
                appState.skip()
            }

            CircleButton(icon: "flag.fill", style: .dark) {
                showReport = true
            }

            CircleButton(icon: "xmark", style: .destructive) {
                appState.disconnect()
            }
        }
        .padding(.vertical, 14)
        .frame(maxWidth: .infinity)
        .background(Color(white: 0.07))
    }
}

// MARK: - Circle button

enum CircleButtonStyle { case dark, light, destructive }

struct CircleButton: View {
    let icon: String
    let style: CircleButtonStyle
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: icon)
                .font(.system(size: 18, weight: .medium))
                .foregroundColor(foreground)
                .frame(width: 48, height: 48)
                .background(background, in: Circle())
        }
    }

    private var foreground: Color {
        switch style {
        case .dark:        return .white
        case .light:       return .black
        case .destructive: return .black
        }
    }

    private var background: Color {
        switch style {
        case .dark:        return Color(white: 0.15)
        case .light:       return .white
        case .destructive: return .white
        }
    }
}
