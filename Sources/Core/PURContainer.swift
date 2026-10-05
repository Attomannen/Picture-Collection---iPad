import Foundation

/// The outer layer of a PureRef `.pur` file.
///
/// A `.pur` is a SQLite database whose first `P` bytes have been moved to the end of the
/// file and replaced by a header:
///
///     QString "2.1" | Int32 0 | UInt64 T | QString app version | QString MD5 | UInt32 n | n bytes JPEG
///
/// where `T` is the database size, `P = 108 + n`, and the MD5 is over everything after the
/// checksum string (from the JPEG length on). The original first `P` bytes of the database
/// are stored at offset `T`.
public enum PURContainer {
    public static let formatVersion = "2.1"
    public static let appVersion = "2.1.3"

    /// Tiny placeholder thumbnail (the one PureRef writes for an empty board).
    public static let placeholderThumbnail = Data(base64Encoded: "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAMCAgICAgMCAgIDAwMDBAYEBAQEBAgGBgUGCQgKCgkICQkKDA8MCgsOCwkJDRENDg8QEBEQCgwSExIQEw8QEBD/wAALCAEAAQABAREA/8QAFQABAQAAAAAAAAAAAAAAAAAAAAn/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAA/AJ7gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP//Z")!

    public struct Unwrapped {
        public var database: Data
        public var thumbnail: Data
        public var appVersion: String
        public var checksumValid: Bool
    }

    public static func unwrap(_ file: Data) throws -> Unwrapped {
        let file = Data(Array(file))
        var r = ByteReader(file)
        guard (try? r.qString()) == formatVersion else { throw PURError.notAPURFile }
        _ = try r.i32()
        let total = Int(try r.u64())
        let version = try r.qString()
        let checksum = try r.qString()
        let thumbStart = r.pos
        let n = Int(try r.u32())
        let thumbnail = Data(try r.take(n))
        let prefix = r.pos
        guard total <= file.count, file.count - total == prefix, prefix <= total else { throw PURError.notAPURFile }

        let db = file[total...] + file[prefix..<total]
        let valid = MD5.hex(file[thumbStart...]) == checksum
        return Unwrapped(database: Data(db), thumbnail: thumbnail, appVersion: version, checksumValid: valid)
    }

    public static func wrap(database db: Data, thumbnail: Data) throws -> Data {
        let db = Data(Array(db))
        let prefix = 108 + thumbnail.count
        guard prefix <= db.count else { throw PURError.truncated }

        var rest = ByteWriter()
        rest.u32(UInt32(thumbnail.count))
        rest.bytes(thumbnail)
        rest.bytes(db[prefix...])
        rest.bytes(db[..<prefix])

        var head = ByteWriter()
        head.qString(formatVersion)
        head.i32(0)
        head.u64(UInt64(db.count))
        head.qString(appVersion)
        head.qString(MD5.hex(rest.data))
        return head.data + rest.data
    }
}
