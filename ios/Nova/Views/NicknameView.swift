import SwiftUI

struct NicknameView: View {
    @EnvironmentObject var appState: AppState
    @State private var nickname = ""
    @State private var errorMessage = ""
    @FocusState private var isFocused: Bool

    var body: some View {
        VStack(spacing: 0) {
            Spacer()

            Text("Nova")
                .font(.system(size: 64, weight: .bold))
                .tracking(-2)

            Text("Choose a nickname")
                .font(.system(size: 16))
                .foregroundColor(.secondary)
                .padding(.bottom, 24)

            VStack(spacing: 12) {
                Text("This is how others will see you in discussions")
                    .font(.system(size: 13))
                    .foregroundColor(.secondary)

                TextField("Enter nickname (2-20 chars)", text: $nickname)
                    .textFieldStyle(.plain)
                    .font(.system(size: 15))
                    .multilineTextAlignment(.center)
                    .padding(12)
                    .background(
                        RoundedRectangle(cornerRadius: 8)
                            .stroke(isFocused ? Color(.systemGray2) : Color(.systemGray4), lineWidth: 1)
                    )
                    .focused($isFocused)
                    .submitLabel(.continue)
                    .onSubmit { submit() }
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)

                Button(action: submit) {
                    Text("Continue →")
                        .font(.system(size: 18, weight: .bold))
                        .foregroundColor(.white)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 16)
                        .background(Color.black)
                        .cornerRadius(10)
                }

                if !errorMessage.isEmpty {
                    Text(errorMessage)
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundColor(.red)
                }
            }
            .padding(.horizontal, 40)

            Spacer()
        }
        .background(Color(.systemBackground))
        .onAppear { isFocused = true }
    }

    private func submit() {
        let trimmed = nickname.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.count >= 2 else {
            errorMessage = "Nickname must be at least 2 characters"
            return
        }
        guard trimmed.count <= 20 else {
            errorMessage = "Nickname must be 20 characters or less"
            return
        }
        errorMessage = ""
        appState.setNickname(trimmed)
    }
}
