import Foundation

enum APIError: LocalizedError {
    case networkError
    case serverError(String)

    var errorDescription: String? {
        switch self {
        case .networkError:
            return "Network error. Check your connection."
        case .serverError(let msg):
            return msg
        }
    }
}

final class APIService {

    private let baseURL: String
    private let session: URLSession

    init(baseURL: String = Config.serverURL) {
        self.baseURL = baseURL
        let config = URLSessionConfiguration.default
        config.httpCookieAcceptPolicy = .always
        config.httpShouldSetCookies = true
        config.httpCookieStorage = .shared
        session = URLSession(configuration: config)
    }

    // MARK: - Session check

    func checkSession() async -> NovaUser? {
        guard let url = URL(string: "\(baseURL)/api/me") else { return nil }
        do {
            let (data, _) = try await session.data(from: url)
            guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  json["ok"] as? Bool == true,
                  let userDict = json["user"] as? [String: Any] else { return nil }
            return parseUser(userDict)
        } catch {
            return nil
        }
    }

    // MARK: - Auth

    func googleAuth(credential: String, tosAccepted: Bool) async -> Result<NovaUser, APIError> {
        await postForUser("/api/auth/google", body: [
            "credential": credential,
            "tos_accepted": tosAccepted,
        ])
    }

    func emailLogin(email: String, password: String) async -> Result<NovaUser, APIError> {
        await postForUser("/api/auth/email", body: [
            "action": "login",
            "email": email,
            "password": password,
        ])
    }

    func emailSignup(email: String, password: String, tosAccepted: Bool) async -> Result<NovaUser, APIError> {
        await postForUser("/api/auth/email", body: [
            "action": "signup",
            "email": email,
            "password": password,
            "tos_accepted": tosAccepted,
        ])
    }

    func logout() async {
        _ = try? await post("/api/logout", body: [:])
    }

    // MARK: - Profile

    func setNickname(_ nickname: String) async -> Result<String, APIError> {
        do {
            let data = try await post("/api/profile", body: ["nickname": nickname])
            guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                return .failure(.networkError)
            }
            if json["ok"] as? Bool == true, let nick = json["nickname"] as? String {
                return .success(nick)
            }
            return .failure(.serverError(json["err"] as? String ?? "Unknown error"))
        } catch {
            return .failure(.networkError)
        }
    }

    // MARK: - Reporting

    func report(reason: String, details: String) async -> Result<String, APIError> {
        do {
            let data = try await post("/api/report", body: [
                "reason": reason,
                "details": details,
            ])
            guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                return .failure(.networkError)
            }
            if json["ok"] as? Bool == true {
                return .success(json["msg"] as? String ?? "Report submitted.")
            }
            return .failure(.serverError(json["err"] as? String ?? "Failed to submit report"))
        } catch {
            return .failure(.networkError)
        }
    }

    // MARK: - GDPR

    func exportData() async -> Result<Data, APIError> {
        guard let url = URL(string: "\(baseURL)/api/my-data") else { return .failure(.networkError) }
        do {
            let (data, _) = try await session.data(from: url)
            return .success(data)
        } catch {
            return .failure(.networkError)
        }
    }

    func deleteAccount() async -> Result<Void, APIError> {
        do {
            let data = try await post("/api/delete-account", body: [:])
            guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  json["ok"] as? Bool == true else {
                return .failure(.serverError("Failed to delete account"))
            }
            return .success(())
        } catch {
            return .failure(.networkError)
        }
    }

    // MARK: - Helpers

    private func post(_ path: String, body: [String: Any]) async throws -> Data {
        guard let url = URL(string: "\(baseURL)\(path)") else { throw APIError.networkError }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, _) = try await session.data(for: request)
        return data
    }

    private func postForUser(_ path: String, body: [String: Any]) async -> Result<NovaUser, APIError> {
        do {
            let data = try await post(path, body: body)
            guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                return .failure(.networkError)
            }
            if json["ok"] as? Bool == true, let userDict = json["user"] as? [String: Any] {
                return .success(parseUser(userDict))
            }
            return .failure(.serverError(json["err"] as? String ?? "Unknown error"))
        } catch {
            return .failure(.networkError)
        }
    }

    private func parseUser(_ dict: [String: Any]) -> NovaUser {
        NovaUser(
            name: dict["name"] as? String ?? "",
            email: dict["email"] as? String ?? "",
            avatar: dict["avatar"] as? String ?? "",
            nickname: dict["nickname"] as? String ?? ""
        )
    }
}
