import SwiftUI

struct ReportSheet: View {
    @EnvironmentObject var appState: AppState
    @Environment(\.dismiss) var dismiss

    @State private var selectedReason = ""
    @State private var details = ""
    @State private var message = ""
    @State private var isError = false

    private let reasons: [(id: String, label: String)] = [
        ("harassment",    "Harassment / Bullying"),
        ("inappropriate", "Inappropriate Content"),
        ("underage",      "Appears Underage"),
        ("spam",          "Spam / Bot"),
        ("illegal",       "Illegal Activity"),
        ("other",         "Other"),
    ]

    var body: some View {
        NavigationView {
            VStack(spacing: 16) {
                Text("Select a reason")
                    .font(.system(size: 14))
                    .foregroundColor(.secondary)
                    .padding(.top, 8)

                ForEach(reasons, id: \.id) { reason in
                    Button {
                        selectedReason = reason.id
                    } label: {
                        HStack {
                            Text(reason.label)
                                .foregroundColor(.primary)
                            Spacer()
                            if selectedReason == reason.id {
                                Image(systemName: "checkmark")
                                    .foregroundColor(.accentColor)
                                    .fontWeight(.bold)
                            }
                        }
                        .padding(.horizontal, 16)
                        .padding(.vertical, 12)
                        .background(
                            RoundedRectangle(cornerRadius: 8)
                                .fill(selectedReason == reason.id
                                      ? Color(.systemGray6)
                                      : Color.clear)
                        )
                    }
                }
                .font(.system(size: 15))

                TextField("Optional details…", text: $details, axis: .vertical)
                    .lineLimit(2...4)
                    .textFieldStyle(.roundedBorder)
                    .padding(.horizontal, 16)

                if !message.isEmpty {
                    Text(message)
                        .font(.system(size: 12))
                        .foregroundColor(isError ? .red : .green)
                }

                Spacer()
            }
            .navigationTitle("Report User")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Report") { submitReport() }
                        .fontWeight(.bold)
                        .disabled(selectedReason.isEmpty)
                }
            }
        }
        .presentationDetents([.medium, .large])
    }

    private func submitReport() {
        guard !selectedReason.isEmpty else {
            message = "Please select a reason"
            isError = true
            return
        }

        Task {
            let result = await appState.apiService.report(reason: selectedReason, details: details)
            switch result {
            case .success(let msg):
                message = msg
                isError = false
                try? await Task.sleep(nanoseconds: 1_500_000_000)
                dismiss()
            case .failure(let error):
                message = error.localizedDescription
                isError = true
            }
        }
    }
}
