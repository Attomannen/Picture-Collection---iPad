#if canImport(SQLite3)
import Foundation
import SQLite3

private let sqliteTransient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

/// Minimal SQLite wrapper, just enough for `.pur` files.
final class SQLiteDB {
    private(set) var handle: OpaquePointer?

    init(path: String, readOnly: Bool) throws {
        let flags = readOnly ? SQLITE_OPEN_READONLY : (SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE)
        guard sqlite3_open_v2(path, &handle, flags, nil) == SQLITE_OK else {
            let msg = handle.map { String(cString: sqlite3_errmsg($0)) } ?? "open failed"
            sqlite3_close(handle)
            throw PURError.sqlite(msg)
        }
    }

    deinit { sqlite3_close(handle) }

    var message: String { String(cString: sqlite3_errmsg(handle)) }

    func exec(_ sql: String) throws {
        guard sqlite3_exec(handle, sql, nil, nil, nil) == SQLITE_OK else { throw PURError.sqlite(message) }
    }

    func prepare(_ sql: String) throws -> SQLiteStatement { try SQLiteStatement(db: self, sql: sql) }
}

final class SQLiteStatement {
    private var stmt: OpaquePointer?
    private let db: SQLiteDB

    init(db: SQLiteDB, sql: String) throws {
        self.db = db
        guard sqlite3_prepare_v2(db.handle, sql, -1, &stmt, nil) == SQLITE_OK else { throw PURError.sqlite(db.message) }
    }

    deinit { sqlite3_finalize(stmt) }

    // MARK: Binding (1-based)

    func bind(_ i: Int32, int v: Int) { sqlite3_bind_int64(stmt, i, Int64(v)) }
    func bind(_ i: Int32, double v: Double) { sqlite3_bind_double(stmt, i, v) }
    func bindNull(_ i: Int32) { sqlite3_bind_null(stmt, i) }

    func bind(_ i: Int32, text s: String) {
        let bytes = Array(s.utf8)
        if bytes.isEmpty { sqlite3_bind_text(stmt, i, "", 0, sqliteTransient); return }
        bytes.withUnsafeBufferPointer {
            sqlite3_bind_text(stmt, i, UnsafeRawPointer($0.baseAddress)?.assumingMemoryBound(to: CChar.self),
                              Int32($0.count), sqliteTransient)
        }
    }

    func bind(_ i: Int32, blob d: Data) {
        d.withUnsafeBytes { sqlite3_bind_blob(stmt, i, $0.baseAddress, Int32($0.count), sqliteTransient) }
    }

    /// PureRef stores its Qt-serialised values in TEXT columns, as the UTF-8 form of the
    /// bytes read as Latin-1 characters. This writes raw bytes in that form.
    func bind(_ i: Int32, qtBytes d: Data) {
        let scalars = String.UnicodeScalarView(d.map { Unicode.Scalar($0) })
        bind(i, text: String(scalars))
    }

    // MARK: Stepping

    @discardableResult
    func step() throws -> Bool {
        switch sqlite3_step(stmt) {
        case SQLITE_ROW: return true
        case SQLITE_DONE: return false
        default: throw PURError.sqlite(db.message)
        }
    }

    func reset() { sqlite3_reset(stmt); sqlite3_clear_bindings(stmt) }

    // MARK: Columns (0-based)

    func int(_ i: Int32) -> Int { Int(sqlite3_column_int64(stmt, i)) }
    func double(_ i: Int32) -> Double { sqlite3_column_double(stmt, i) }
    func isNull(_ i: Int32) -> Bool { sqlite3_column_type(stmt, i) == SQLITE_NULL }

    func blob(_ i: Int32) -> Data {
        guard let p = sqlite3_column_blob(stmt, i) else { return Data() }
        return Data(bytes: p, count: Int(sqlite3_column_bytes(stmt, i)))
    }

    func text(_ i: Int32) -> String { String(decoding: blob(i), as: UTF8.self) }

    /// Inverse of `bind(_:qtBytes:)`.
    func qtBytes(_ i: Int32) -> Data {
        Data(String(decoding: blob(i), as: UTF8.self).unicodeScalars.map { UInt8(truncatingIfNeeded: $0.value) })
    }
}
#endif
