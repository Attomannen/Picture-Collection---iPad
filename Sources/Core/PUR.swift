#if canImport(SQLite3)
import Foundation

/// Reads and writes PureRef `.pur` files (format 2.1).
public enum PUR {
    public struct ImportResult {
        public var board: Board
        public var assets: [String: Data]
        /// Things in the file this app can't represent yet (notes, groups, crops, ...).
        public var warnings: [String]
    }

    private static let userVersion = 200101

    // MARK: Read

    public static func read(_ file: Data) throws -> ImportResult {
        let container = try PURContainer.unwrap(file)
        let tmp = FileManager.default.temporaryDirectory.appendingPathComponent("pur-\(UUID().uuidString).db")
        try container.database.write(to: tmp)
        defer { try? FileManager.default.removeItem(at: tmp) }

        let db = try SQLiteDB(path: tmp.path, readOnly: true)
        var warnings: [String] = []
        if !container.checksumValid { warnings.append("File checksum did not match; the file may be damaged.") }

        // Images
        var images: [Int: (data: Data, w: Int, h: Int)] = [:]
        let imgStmt = try db.prepare("SELECT id, data, width, height FROM images")
        while try imgStmt.step() { images[imgStmt.int(0)] = (imgStmt.blob(1), imgStmt.int(2), imgStmt.int(3)) }

        // Items (images only), back to front
        var board = Board()
        var assets: [String: Data] = [:]
        let itemStmt = try db.prepare("""
            SELECT i.parent, i.transform, ii.image, ii.image_transform
            FROM items i JOIN items_images ii ON ii.id = i.id
            ORDER BY i.z, i.id
            """)
        while try itemStmt.step() {
            guard let img = images[itemStmt.int(2)] else { continue }
            let m = try QtVariant.readTransform(itemStmt.qtBytes(1))
            let it = try QtVariant.readTransform(itemStmt.qtBytes(3))
            if itemStmt.int(0) != -1 { warnings.append("An image inside a group was imported without its group transform.") }

            // Image rectangle centre in item space, then to scene space.
            let cx = it[6] + Double(img.w) / 2, cy = it[7] + Double(img.h) / 2
            let key = "pur\(itemStmt.int(2))"
            assets[key] = img.data
            let scale = (m[3] * m[3] + m[4] * m[4]).squareRoot()
            board.items.append(BoardItem(
                asset: key,
                x: m[0] * cx + m[3] * cy + m[6],
                y: m[1] * cx + m[4] * cy + m[7],
                width: Double(img.w), height: Double(img.h),
                scale: scale,
                rotation: atan2(-m[3], m[4]),
                flipped: m[0] * m[4] - m[1] * m[3] < 0))
        }

        for (table, label) in [("items_notes", "notes"), ("items_groups", "groups"), ("items_drawings", "drawings")] {
            let s = try db.prepare("SELECT COUNT(*) FROM \(table)")
            if try s.step(), s.int(0) > 0 { warnings.append("\(s.int(0)) \(label) skipped (not supported yet).") }
        }

        // Viewport
        let meta = try db.prepare("SELECT view_transform, horizontal_scroll, vertical_scroll FROM metadata LIMIT 1")
        if try meta.step(), let v = try? QtVariant.readTransform(meta.qtBytes(0)), v[0] > 0 {
            board.zoom = v[0]
            board.offsetX = -Double(meta.int(1))
            board.offsetY = -Double(meta.int(2))
        }
        return ImportResult(board: board, assets: assets, warnings: warnings)
    }

    // MARK: Write

    private static let schema = [
        "CREATE TABLE images (id INTEGER PRIMARY KEY,source_type INTEGER,origin TEXT,source TEXT,format TEXT,checksum TEXT,data BLOB,width INTEGER,height INTEGER)",
        "CREATE TABLE metadata (id INTEGER PRIMARY KEY,scene_rect TEXT,application_version TEXT,view_transform TEXT,thumbnail BLOB,horizontal_scroll INTEGER,vertical_scroll INTEGER,last_save_path TEXT,last_load_path TEXT,last_load_checksum TEXT,saved INTEGER)",
        "CREATE TABLE items (parent INTEGER,id INTEGER PRIMARY KEY,name TEXT,transform BLOB,sort_order BLOB,z REAL,opacity REAL,locked INTEGER,comment INTEGER)",
        "CREATE TABLE items_images (image INTEGER,playback_speed REAL,id INTEGER PRIMARY KEY,playback_state INTEGER,image_transform BLOB,image_bounds BLOB,playback_frame INTEGER,flags INTEGER)",
        "CREATE TABLE items_drawings (id INTEGER PRIMARY KEY,strokes BLOB)",
        "CREATE TABLE items_notes (text_color TEXT,id INTEGER PRIMARY KEY,fixed_size TEXT,background_color TEXT,text TEXT,style INTEGER)",
        "CREATE TABLE items_groups (id INTEGER PRIMARY KEY,background_color TEXT,lock_mode INTEGER)"
    ]

    /// Every asset used by the board must be PNG or JPEG data.
    public static func write(board: Board, assets: [String: Data], thumbnail: Data? = nil) throws -> Data {
        let tmp = FileManager.default.temporaryDirectory.appendingPathComponent("pur-\(UUID().uuidString).db")
        defer { try? FileManager.default.removeItem(at: tmp) }

        do {
            let db = try SQLiteDB(path: tmp.path, readOnly: false)
            try db.exec("PRAGMA page_size = 4096")
            try db.exec("PRAGMA journal_mode = DELETE")
            try db.exec("PRAGMA user_version = \(userVersion)")
            try schema.forEach { try db.exec($0) }
            try db.exec("BEGIN")

            // Images, one row per distinct asset
            var imageIDs: [String: Int] = [:]
            var pixelSize: [String: (w: Int, h: Int)] = [:]
            let insImage = try db.prepare("INSERT INTO images (id, source_type, origin, source, format, checksum, data, width, height) VALUES (?,?,?,?,?,?,?,?,?)")
            for item in board.items where imageIDs[item.asset] == nil {
                guard let data = assets[item.asset], let info = ImageInfo.probe(data) else { throw PURError.unsupportedImage }
                let id = imageIDs.count
                imageIDs[item.asset] = id
                pixelSize[item.asset] = (info.width, info.height)
                insImage.reset()
                insImage.bind(1, int: id)
                insImage.bind(2, int: 0)
                insImage.bind(3, text: "")
                insImage.bind(4, text: "")
                insImage.bind(5, text: info.format == .png ? "PNG" : "JPEG")
                insImage.bind(6, text: MD5.hex(data))
                insImage.bind(7, blob: data)
                insImage.bind(8, int: info.width)
                insImage.bind(9, int: info.height)
                try insImage.step()
            }

            // Items
            let insItem = try db.prepare("INSERT INTO items (parent, id, name, transform, sort_order, z, opacity, locked, comment) VALUES (-1,?,?,?,?,?,1.0,0,NULL)")
            let insImg = try db.prepare("INSERT INTO items_images (image, playback_speed, id, playback_state, image_transform, image_bounds, playback_frame, flags) VALUES (?,1.0,?,0,?,?,0,1)")
            var minX = Double.infinity, minY = Double.infinity, maxX = -Double.infinity, maxY = -Double.infinity

            for (n, item) in board.items.enumerated() {
                let px = pixelSize[item.asset]!
                let w = Double(px.w), h = Double(px.h)
                let s = item.scale * item.width / w
                let f = item.flipped ? -1.0 : 1.0
                let c = cos(item.rotation), sn = sin(item.rotation)
                let m = [s * f * c, s * f * sn, 0, -s * sn, s * c, 0, item.x, item.y, 1]

                insItem.reset()
                insItem.bind(1, int: n)
                insItem.bind(2, text: "Image \(n + 1)")
                insItem.bind(3, qtBytes: QtVariant.transform(m))
                insItem.bind(4, qtBytes: QtVariant.bigRational(n + 1))
                insItem.bind(5, double: Double(n + 1))
                try insItem.step()

                insImg.reset()
                insImg.bind(1, int: imageIDs[item.asset]!)
                insImg.bind(2, int: n)
                insImg.bind(3, qtBytes: QtVariant.transform([1, 0, 0, 0, 1, 0, -w / 2, -h / 2, 1]))
                insImg.bind(4, qtBytes: QtVariant.rectPath(x: -w / 2, y: -h / 2, w: w, h: h))
                try insImg.step()

                for (px, py) in [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)] {
                    let x = m[0] * px + m[3] * py + m[6], y = m[1] * px + m[4] * py + m[7]
                    minX = min(minX, x); maxX = max(maxX, x); minY = min(minY, y); maxY = max(maxY, y)
                }
            }
            if board.items.isEmpty { minX = -100; minY = -100; maxX = 100; maxY = 100 }

            // Metadata
            let thumb = thumbnail ?? PURContainer.placeholderThumbnail
            let meta = try db.prepare("INSERT INTO metadata (id, scene_rect, application_version, view_transform, thumbnail, horizontal_scroll, vertical_scroll, last_save_path, last_load_path, last_load_checksum, saved) VALUES (0,?,?,?,?,?,?,NULL,NULL,NULL,0)")
            meta.bind(1, qtBytes: QtVariant.rectF(x: minX, y: minY, w: maxX - minX, h: maxY - minY))
            meta.bind(2, text: PURContainer.appVersion)
            meta.bind(3, qtBytes: QtVariant.transform([board.zoom, 0, 0, 0, board.zoom, 0, 0, 0, 1]))
            meta.bind(4, blob: thumb)
            meta.bind(5, int: Int((-board.offsetX).rounded()))
            meta.bind(6, int: Int((-board.offsetY).rounded()))
            try meta.step()

            try db.exec("COMMIT")
        }

        let dbBytes = try Data(contentsOf: tmp)
        return try PURContainer.wrap(database: dbBytes, thumbnail: thumbnail ?? PURContainer.placeholderThumbnail)
    }
}
#endif
