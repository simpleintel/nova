import SwiftUI

struct ContentView: View {
    @EnvironmentObject var appState: AppState

    var body: some View {
        ZStack {
            switch appState.screen {
            case .auth:
                AuthView()
                    .transition(.opacity)
            case .nickname:
                NicknameView()
                    .transition(.opacity)
            case .lobby:
                LobbyView()
                    .transition(.opacity)
            case .chat:
                VideoChatView()
                    .transition(.opacity)
            }
        }
        .animation(.easeInOut(duration: 0.25), value: appState.screen)
    }
}
