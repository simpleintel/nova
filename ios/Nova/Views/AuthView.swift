import SwiftUI
import GoogleSignIn
import GoogleSignInSwift

struct AuthView: View {
    @EnvironmentObject var appState: AppState
    @State private var ageConfirmed = false
    @State private var tosAccepted = false
    @State private var errorMessage = ""

    var body: some View {
        ScrollView(showsIndicators: false) {
            VStack(spacing: 0) {
                heroSection
                authBox
                divider
                featuresSection
                footer
            }
        }
        .background(Color(.systemBackground))
    }

    // MARK: - Hero

    private var heroSection: some View {
        VStack(spacing: 8) {
            Text("Nova")
                .font(.system(size: 64, weight: .bold))
                .tracking(-2)

            Text("Live video debates with strangers.\nChallenge your perspective.")
                .font(.system(size: 17))
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
        }
        .padding(.top, 60)
        .padding(.bottom, 32)
    }

    // MARK: - Auth controls

    private var authBox: some View {
        VStack(spacing: 12) {
            Toggle(isOn: $ageConfirmed) {
                Text("I confirm I am 18 years or older")
                    .font(.system(size: 14, weight: .semibold))
            }
            .toggleStyle(CheckboxToggleStyle())

            Toggle(isOn: $tosAccepted) {
                (Text("I agree to the ")
                    + Text("Terms of Service").underline()
                    + Text(" & ")
                    + Text("Privacy Policy").underline()
                ).font(.system(size: 14))
            }
            .toggleStyle(CheckboxToggleStyle())

            GoogleSignInButton(scheme: .light, style: .wide, state: .normal) {
                handleGoogleSignIn()
            }
            .frame(height: 50)
            .padding(.top, 8)

            if !errorMessage.isEmpty {
                Text(errorMessage)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundColor(.red)
                    .multilineTextAlignment(.center)
            }
        }
        .padding(.horizontal, 40)
        .padding(.bottom, 32)
    }

    private var divider: some View {
        Rectangle()
            .fill(Color(.systemGray5))
            .frame(width: 48, height: 1)
            .padding(.bottom, 20)
    }

    // MARK: - Features grid

    private var featuresSection: some View {
        VStack(spacing: 18) {
            Text("How it works")
                .font(.system(size: 20, weight: .bold))

            LazyVGrid(columns: [
                GridItem(.flexible(), spacing: 14),
                GridItem(.flexible(), spacing: 14),
            ], spacing: 14) {
                FeatureCard(title: "Live video, not text",
                            text: "Real face-to-face conversations. No typing, no hiding.")
                FeatureCard(title: "Matched instantly",
                            text: "Sign in, tap one button, and you're connected.")
                FeatureCard(title: "Global perspectives",
                            text: "Talk to people from around the world.")
                FeatureCard(title: "Private & P2P",
                            text: "Video goes directly between you and your partner.")
                FeatureCard(title: "Safe & moderated",
                            text: "Report tools, auto-bans, and session logging.")
                FeatureCard(title: "Completely free",
                            text: "No subscriptions, no coins, no paywalls.")
            }
        }
        .padding(.horizontal, 20)
        .padding(.bottom, 32)
    }

    private var footer: some View {
        VStack(spacing: 4) {
            Text("All connections are logged for legal compliance.")
                .font(.system(size: 13))
                .foregroundColor(.secondary)
            Text("Contact: rahul@simpleintelligence.com")
                .font(.system(size: 13))
                .foregroundColor(.secondary)
        }
        .padding(.bottom, 40)
    }

    // MARK: - Google Sign-In

    private func handleGoogleSignIn() {
        errorMessage = ""

        guard ageConfirmed else {
            errorMessage = "You must confirm you are 18 or older."
            return
        }
        guard tosAccepted else {
            errorMessage = "You must accept the Terms of Service & Privacy Policy."
            return
        }

        guard let windowScene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
              let rootVC = windowScene.windows.first?.rootViewController else { return }

        GIDSignIn.sharedInstance.signIn(withPresenting: rootVC) { result, error in
            guard let result, error == nil else {
                errorMessage = error?.localizedDescription ?? "Google sign-in failed"
                return
            }
            guard let idToken = result.user.idToken?.tokenString else {
                errorMessage = "Failed to get Google token"
                return
            }
            appState.loginWithGoogle(credential: idToken, tosAccepted: true)
        }
    }
}

// MARK: - Checkbox toggle

struct CheckboxToggleStyle: ToggleStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: configuration.isOn ? "checkmark.square.fill" : "square")
                .foregroundColor(configuration.isOn ? .primary : .secondary)
                .font(.system(size: 18))
                .onTapGesture { configuration.isOn.toggle() }

            configuration.label
                .onTapGesture { configuration.isOn.toggle() }
        }
    }
}

// MARK: - Feature card

struct FeatureCard: View {
    let title: String
    let text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.system(size: 15, weight: .bold))
            Text(text)
                .font(.system(size: 14))
                .foregroundColor(.secondary)
                .lineSpacing(2)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .stroke(Color(.systemGray5), lineWidth: 1)
        )
    }
}
