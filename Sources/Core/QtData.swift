import Foundation

/// Big-endian writer matching Qt's QDataStream encoding.
struct ByteWriter {
    var data = Data()

    mutating func u8(_ v: UInt8) { data.append(v) }
    mutating func u32(_ v: UInt32) { for s in [24, 16, 8, 0] { data.append(UInt8((v >> UInt32(s)) & 0xff)) } }
    mutating func i32(_ v: Int32) { u32(UInt32(bitPattern: v)) }
    mutating func u64(_ v: UInt64) { for s in stride(from: 56, through: 0, by: -8) { data.append(UInt8((v >> UInt64(s)) & 0xff)) } }
    mutating func f64(_ v: Double) { u64(v.bitPattern) }
    mutating func bytes(_ d: Data) { data.append(d) }

    /// QString: byte length followed by UTF-16BE.
    mutating func qString(_ s: String) {
        let units = Array(s.utf16)
        u32(UInt32(units.count * 2))
        for u in units { data.append(UInt8(u >> 8)); data.append(UInt8(u & 0xff)) }
    }
}

struct ByteReader {
    let bytes: [UInt8]
    var pos = 0

    init(_ data: Data) { bytes = [UInt8](data) }

    mutating func take(_ n: Int) throws -> ArraySlice<UInt8> {
        guard n >= 0, pos + n <= bytes.count else { throw PURError.truncated }
        defer { pos += n }
        return bytes[pos..<pos + n]
    }
    mutating func u8() throws -> UInt8 { try take(1).first! }
    mutating func u32() throws -> UInt32 { try take(4).reduce(0) { ($0 << 8) | UInt32($1) } }
    mutating func i32() throws -> Int32 { Int32(bitPattern: try u32()) }
    mutating func u64() throws -> UInt64 { try take(8).reduce(0) { ($0 << 8) | UInt64($1) } }
    mutating func f64() throws -> Double { Double(bitPattern: try u64()) }
    mutating func qString() throws -> String {
        let n = Int(try u32())
        let b = try take(n)
        var units: [UInt16] = []
        var i = b.startIndex
        while i + 1 < b.endIndex { units.append(UInt16(b[i]) << 8 | UInt16(b[i + 1])); i += 2 }
        return String(decoding: units, as: UTF16.self)
    }
}

public enum PURError: Error, Equatable {
    case truncated
    case notAPURFile
    case checksumMismatch
    case sqlite(String)
    case unsupportedImage
}

/// The QVariant payloads PureRef stores in its tables.
/// (QVariant type ids: QRectF = 20, QTransform = 80, user type = 1024.)
enum QtVariant {
    static func transform(_ m: [Double]) -> Data {
        var w = ByteWriter()
        w.u32(80); w.u8(0)
        m.forEach { w.f64($0) }
        return w.data
    }

    static func rectF(x: Double, y: Double, w: Double, h: Double) -> Data {
        var out = ByteWriter()
        out.u32(20); out.u8(0)
        [x, y, w, h].forEach { out.f64($0) }
        return out.data
    }

    private static func user(_ name: String, _ payload: Data) -> Data {
        var w = ByteWriter()
        w.u32(1024); w.u8(0)
        w.u32(UInt32(name.utf8.count + 1))
        w.bytes(Data(name.utf8)); w.u8(0)
        w.bytes(payload)
        return w.data
    }

    /// Closed rectangle path (as QPainterPath's stream form) used for image bounds.
    static func rectPath(x: Double, y: Double, w: Double, h: Double) -> Data {
        var p = ByteWriter()
        let pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
        p.i32(Int32(pts.count))
        for (i, pt) in pts.enumerated() {
            p.i32(i == 0 ? 0 : 1)   // MoveTo, then LineTo
            p.f64(pt.0); p.f64(pt.1)
        }
        p.i32(0)   // current-start index
        p.i32(0)   // fill rule
        return user("QPainterPath", p.data)
    }

    /// Sort key as the fraction `n / 1` in PureRef's BigRational layout.
    static func bigRational(_ n: Int) -> Data {
        var p = ByteWriter()
        p.u32(0); p.u8(1); p.u64(1); p.u32(UInt32(n))   // numerator
        p.u32(1); p.u64(1); p.u32(1)                    // denominator
        return user("BigRational", p.data)
    }

    static func readTransform(_ d: Data) throws -> [Double] {
        var r = ByteReader(d)
        guard try r.u32() == 80 else { throw PURError.truncated }
        _ = try r.u8()
        return try (0..<9).map { _ in try r.f64() }
    }

    static func readRectF(_ d: Data) throws -> (x: Double, y: Double, w: Double, h: Double) {
        var r = ByteReader(d)
        guard try r.u32() == 20 else { throw PURError.truncated }
        _ = try r.u8()
        return (try r.f64(), try r.f64(), try r.f64(), try r.f64())
    }
}
