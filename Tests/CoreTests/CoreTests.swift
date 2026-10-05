import XCTest
@testable import PicBoardCore

final class CoreTests: XCTestCase {
    func testArchiveRoundTrip() throws {
        var board = Board()
        board.zoom = 2
        board.items = [
            BoardItem(asset: "a", x: 10, y: 20, width: 100, height: 50, rotation: 0.5, flipped: true),
            BoardItem(asset: "b", x: -5, y: 7, width: 30, height: 30)
        ]
        let assets = ["a": Data([1, 2, 3]), "b": Data([9, 8]), "unused": Data([0])]
        let blob = try BoardArchive.encode(board: board, assets: assets)
        let (b2, a2) = try BoardArchive.decode(blob)
        XCTAssertEqual(b2, board)
        XCTAssertEqual(a2, ["a": Data([1, 2, 3]), "b": Data([9, 8])])
    }

    func testBadMagic() {
        XCTAssertThrowsError(try BoardArchive.decode(Data("nope-nope".utf8)))
    }

    func testHitTestRespectsRotation() {
        let item = BoardItem(asset: "a", x: 0, y: 0, width: 100, height: 10, rotation: .pi / 2)
        XCTAssertTrue(item.contains(worldX: 0, worldY: 40))   // long axis now vertical
        XCTAssertFalse(item.contains(worldX: 40, worldY: 0))
    }
}

final class PURTests: XCTestCase {
    private func fixture(_ name: String) throws -> Data {
        let url = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .appendingPathComponent("Fixtures/\(name).pur")
        return try Data(contentsOf: url)
    }

    func testMD5() {
        XCTAssertEqual(MD5.hex(Data()), "d41d8cd98f00b204e9800998ecf8427e")
        XCTAssertEqual(MD5.hex(Data("The quick brown fox jumps over the lazy dog".utf8)), "9e107d9d372bb6826bd81d3542a419d6")
    }

    func testContainerChecksumAndRewrapIsByteIdentical() throws {
        for name in ["Empty", "Brick1", "Brick3"] {
            let file = try fixture(name)
            let u = try PURContainer.unwrap(file)
            XCTAssertTrue(u.checksumValid, name)
            XCTAssertEqual(Array(u.database.prefix(15)), Array("SQLite format 3".utf8), name)
            let rewrapped = try PURContainer.wrap(database: u.database, thumbnail: u.thumbnail)
            XCTAssertEqual(rewrapped, file, name)
        }
    }

    func testReadBrick1() throws {
        let r = try PUR.read(try fixture("Brick1"))
        XCTAssertEqual(r.board.items.count, 1)
        let it = r.board.items[0]
        XCTAssertEqual(it.x, 52, accuracy: 1e-9)
        XCTAssertEqual(it.y, -11, accuracy: 1e-9)
        XCTAssertEqual(it.width, 256); XCTAssertEqual(it.height, 256)
        XCTAssertEqual(it.scale, 1, accuracy: 1e-9)
        XCTAssertEqual(it.rotation, 0, accuracy: 1e-9)
        XCTAssertFalse(it.flipped)
        XCTAssertEqual(ImageInfo.probe(r.assets[it.asset]!)?.width, 256)
    }

    func testReadBrick3() throws {
        let r = try PUR.read(try fixture("Brick3"))
        XCTAssertEqual(r.board.items.count, 3)
        // Back-to-front by z: ids 0 (z1), 3 (z2), 2 (z3).
        XCTAssertEqual(r.board.items.map { $0.x.rounded() }, [52, -313, 466])
    }

    func testReadEmpty() throws {
        XCTAssertTrue(try PUR.read(try fixture("Empty")).board.items.isEmpty)
    }

    func testWriteThenReadRoundTrip() throws {
        let src = try PUR.read(try fixture("Brick1"))
        var board = src.board
        board.items[0].rotation = 0.6
        board.items[0].scale = 1.5
        board.items[0].flipped = true
        board.items.append(BoardItem(asset: board.items[0].asset, x: -300, y: 40, width: 256, height: 256, scale: 0.5))

        let file = try PUR.write(board: board, assets: src.assets)
        let back = try PUR.read(file)
        XCTAssertTrue(try PURContainer.unwrap(file).checksumValid)
        XCTAssertEqual(back.board.items.count, 2)
        for (a, b) in zip(board.items, back.board.items) {
            XCTAssertEqual(a.x, b.x, accuracy: 1e-6)
            XCTAssertEqual(a.y, b.y, accuracy: 1e-6)
            XCTAssertEqual(a.scale, b.scale, accuracy: 1e-6)
            XCTAssertEqual(a.rotation, b.rotation, accuracy: 1e-6)
            XCTAssertEqual(a.flipped, b.flipped)
        }
        XCTAssertEqual(back.assets.count, 1, "identical image should be stored once")
    }

    func testWrittenFileMatchesPureRefLayout() throws {
        // Same scene as the Brick1 sample: one 256px image centred at (52, -11).
        let src = try PUR.read(try fixture("Brick1"))
        let file = try PUR.write(board: src.board, assets: src.assets)
        let u = try PURContainer.unwrap(file)
        XCTAssertEqual(u.database.count % 4096, 0)
    }
}
