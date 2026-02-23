import SwiftUI

struct LobbyView: View {
    @EnvironmentObject var appState: AppState
    @State private var showDeleteConfirm = false

    var body: some View {
        VStack(spacing: 0) {
            Spacer()

            Text("Nova")
                .font(.system(size: 64, weight: .bold))
                .tracking(-2)

            Text("Real-time video debates with strangers")
                .font(.system(size: 16))
                .foregroundColor(.secondary)
                .padding(.bottom, 16)

            userBar
            onlineBadge
            startButton

            Text("Peer-to-peer video · Hear different perspectives")
                .font(.system(size: 14))
                .foregroundColor(Color(.systemGray2))
                .padding(.top, 8)

            gdprButtons

            Spacer()

            footerLinks
        }
        .background(Color(.systemBackground))
        .alert("Delete Account?", isPresented: $showDeleteConfirm) {
            Button("Cancel", role: .cancel) {}
            Button("Delete", role: .destructive) { deleteAccount() }
        } message: {
            Text("This will permanently remove your profile, nickname, and all personal data. This cannot be undone.")
        }
    }

    // MARK: - Subviews

    private var userBar: some View {
        HStack(spacing: 8) {
            if let avatar = appState.user?.avatar, !avatar.isEmpty,
               let url = URL(string: avatar) {
                AsyncImage(url: url) { image in
                    image.resizable()
                } placeholder: {
                    Circle().fill(Color(.systemGray5))
                }
                .frame(width: 26, height: 26)
                .clipShape(Circle())
                .overlay(Circle().stroke(Color(.systemGray4), lineWidth: 1))
            }

            Group {
                Text("Logged in as ")
                    .foregroundColor(.secondary) +
                Text(appState.user?.nickname ?? appState.user?.name ?? "")
                    .fontWeight(.bold)
            }
            .font(.system(size: 13))

            Button("log out") { appState.logout() }
                .font(.system(size: 14))
                .foregroundColor(.secondary)
                .padding(.horizontal, 12)
                .padding(.vertical, 6)
                .background(
                    RoundedRectangle(cornerRadius: 6)
                        .stroke(Color(.systemGray4), lineWidth: 1)
                )
        }
        .padding(.bottom, 16)
    }

    private var onlineBadge: some View {
        HStack(spacing: 7) {
            PulsingDot()
            Text("\(appState.onlineCount) online")
                .font(.system(size: 13, weight: .medium))
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 5)
        .background(
            Capsule().stroke(Color(.systemGray4), lineWidth: 1)
        )
        .padding(.bottom, 16)
    }

    private var startButton: some View {
        Button {
            appState.startChat()
        } label: {
            HStack(spacing: 6) {
                Image(systemName: "mic.fill")
                Text("Start a Discussion")
            }
            .font(.system(size: 18, weight: .bold))
            .foregroundColor(.white)
            .padding(.horizontal, 40)
            .padding(.vertical, 16)
            .background(Color.black)
            .cornerRadius(10)
        }
    }

    private var gdprButtons: some View {
        HStack(spacing: 8) {
            Button { exportData() } label: {
                Label("My Data", systemImage: "arrow.down.circle")
                    .font(.system(size: 13))
            }
            .buttonStyle(OutlineButtonStyle())

            Button { showDeleteConfirm = true } label: {
                Label("Delete Account", systemImage: "trash")
                    .font(.system(size: 13))
            }
            .buttonStyle(OutlineButtonStyle())
        }
        .padding(.top, 16)
    }

    private var footerLinks: some View {
        VStack(spacing: 4) {
            Text("Contact: rahul@simpleintelligence.com")
                .font(.system(size: 13))
                .foregroundColor(.secondary)
            HStack(spacing: 8) {
                Link("Privacy", destination: URL(string: "\(Config.serverURL)/privacy")!)
                Text("·").foregroundColor(.secondary)
                Link("Terms", destination: URL(string: "\(Config.serverURL)/tos")!)
            }
            .font(.system(size: 13))
            .foregroundColor(.secondary)
        }
        .padding(.bottom, 20)
    }

    // MARK: - Actions

    private func exportData() {
        Task {
            let result = await appState.apiService.exportData()
            guard case .success(let data) = result else { return }
            let fileURL = FileManager.default.temporaryDirectory.appendingPathComponent("nova-my-data.json")
            try? data.write(to: fileURL)
            guard let scene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
                  let rootVC = scene.windows.first?.rootViewController else { return }
            let ac = UIActivityViewController(activityItems: [fileURL], applicationActivities: nil)
            rootVC.present(ac, animated: true)
        }
    }

    private func deleteAccount() {
        Task {
            let result = await appState.apiService.deleteAccount()
            if case .success = result {
                appState.user = nil
                appState.socketService.disconnect()
                appState.webRTCService.cleanup()
                appState.screen = .auth
            }
        }
    }
}

// MARK: - Reusable styles

struct OutlineButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .foregroundColor(.secondary)
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .background(
                RoundedRectangle(cornerRadius: 6)
                    .stroke(Color(.systemGray4), lineWidth: 1)
            )
            .opacity(configuration.isPressed ? 0.7 : 1)
    }
}

struct PulsingDot: View {
    @State private var opacity: Double = 1

    var body: some View {
        Circle()
            .fill(Color.primary)
            .frame(width: 7, height: 7)
            .opacity(opacity)
            .animation(.easeInOut(duration: 1).repeatForever(autoreverses: true), value: opacity)
            .onAppear { opacity = 0.3 }
    }
}
