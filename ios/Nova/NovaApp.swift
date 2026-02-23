import SwiftUI
import GoogleSignIn

@main
struct NovaApp: App {
    @StateObject private var appState = AppState()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(appState)
                .onOpenURL { url in
                    GIDSignIn.sharedInstance.handle(url)
                }
                .onAppear {
                    configureGoogleSignIn()
                }
        }
    }

    private func configureGoogleSignIn() {
        guard !Config.googleClientID.isEmpty,
              Config.googleClientID != "YOUR_IOS_CLIENT_ID" else { return }
        GIDSignIn.sharedInstance.configuration = GIDConfiguration(clientID: Config.googleClientID)
    }
}
