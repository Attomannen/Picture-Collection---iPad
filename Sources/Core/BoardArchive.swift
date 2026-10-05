import Foundation

/// Single-file container for a board and its images (".picboard").
///
/// Layout: "PBRD1" | UInt32 big-endian JSON length | JSON envelope | asset bytes...
/// The envelope lists each asset's name and length, in the order the bytes follow.
public enum BoardArchive {
    public enum ArchiveError: Error { case badMagic, truncated }

    static let magic = Data("PBRD1".utf8)

    struct Envelope: Codable {
        struct Asset: Codable { var name: String; var length: Int }
        var board: Board
        var assets: [Asset]
    }

    public static func encode(board: Board, assets: [String: Data]) throws -> Data {
        // Only keep assets that are still referenced.
        let used = Set(board.items.map(\.asset))
        let names = used.filter { assets[$0] != nil }.sorted()
        let envelope = Envelope(board: board,
                                assets: names.map { .init(name: $0, length: assets[$0]!.count) })
        let json = try JSONEncoder().encode(envelope)
        var out = magic
        var len = UInt32(json.count).bigEndian
        out.append(Data(bytes: &len, count: 4))
        out.append(json)
        for n in names { out.append(assets[n]!) }
        return out
    }

    public static func decode(_ data: Data) throws -> (board: Board, assets: [String: Data]) {
        let data = Data(data) // normalise indices
        guard data.count >= magic.count + 4 else { throw ArchiveError.truncated }
        guard data.prefix(magic.count) == magic else { throw ArchiveError.badMagic }
        var pos = magic.count
        let jsonLen = data[pos..<pos + 4].reduce(0) { ($0 << 8) | Int($1) }
        pos += 4
        guard pos + jsonLen <= data.count else { throw ArchiveError.truncated }
        let envelope = try JSONDecoder().decode(Envelope.self, from: data[pos..<pos + jsonLen])
        pos += jsonLen
        var assets: [String: Data] = [:]
        for a in envelope.assets {
            guard pos + a.length <= data.count else { throw ArchiveError.truncated }
            assets[a.name] = data[pos..<pos + a.length]
            pos += a.length
        }
        return (envelope.board, assets)
    }
}
