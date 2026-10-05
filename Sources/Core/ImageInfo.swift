import Foundation

/// Reads the format and pixel size of PNG / JPEG data without decoding it.
public enum ImageInfo {
    public enum Format { case png, jpeg }

    public static func probe(_ data: Data) -> (format: Format, width: Int, height: Int)? {
        let b = [UInt8](data.prefix(1 << 16))
        if b.count >= 24, Array(b[0..<8]) == [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a] {
            let w = be32(b, 16), h = be32(b, 20)
            return (.png, w, h)
        }
        guard b.count > 4, b[0] == 0xff, b[1] == 0xd8 else { return nil }
        var i = 2
        while i + 4 < b.count {
            guard b[i] == 0xff else { i += 1; continue }
            let marker = b[i + 1]
            if marker == 0xff { i += 1; continue }
            if marker == 0xd8 || marker == 0x01 || (0xd0...0xd7).contains(marker) { i += 2; continue }
            let len = Int(b[i + 2]) << 8 | Int(b[i + 3])
            let isSOF = (0xc0...0xcf).contains(marker) && marker != 0xc4 && marker != 0xc8 && marker != 0xcc
            if isSOF, i + 9 < b.count {
                let h = Int(b[i + 5]) << 8 | Int(b[i + 6])
                let w = Int(b[i + 7]) << 8 | Int(b[i + 8])
                return (.jpeg, w, h)
            }
            i += 2 + len
        }
        return nil
    }

    private static func be32(_ b: [UInt8], _ o: Int) -> Int {
        Int(b[o]) << 24 | Int(b[o + 1]) << 16 | Int(b[o + 2]) << 8 | Int(b[o + 3])
    }
}
