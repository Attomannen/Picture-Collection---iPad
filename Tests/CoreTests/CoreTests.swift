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
