import Foundation

struct NovaUser: Codable {
    let name: String
    let email: String
    let avatar: String
    var nickname: String

    init(name: String = "", email: String = "", avatar: String = "", nickname: String = "") {
        self.name = name
        self.email = email
        self.avatar = avatar
        self.nickname = nickname
    }
}
