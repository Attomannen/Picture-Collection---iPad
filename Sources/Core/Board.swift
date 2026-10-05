import Foundation

/// One image placed on the canvas. Coordinates are in "world" space;
/// (x, y) is the centre of the image.
public struct BoardItem: Codable, Identifiable, Equatable {
    public var id: UUID
    /// Key into the board's asset table (the original image bytes).
    public var asset: String
    public var x: Double
    public var y: Double
    /// Natural size in world units at scale 1.
    public var width: Double
    public var height: Double
    public var scale: Double
    /// Radians, clockwise.
    public var rotation: Double
    public var flipped: Bool

    public init(id: UUID = UUID(), asset: String, x: Double, y: Double,
                width: Double, height: Double, scale: Double = 1,
                rotation: Double = 0, flipped: Bool = false) {
        self.id = id; self.asset = asset; self.x = x; self.y = y
        self.width = width; self.height = height; self.scale = scale
        self.rotation = rotation; self.flipped = flipped
    }

    /// Is a world-space point inside this (rotated, scaled) item?
    public func contains(worldX: Double, worldY: Double) -> Bool {
        let dx = worldX - x, dy = worldY - y
        let c = cos(-rotation), s = sin(-rotation)
        let lx = dx * c - dy * s, ly = dx * s + dy * c
        return abs(lx) <= width * scale / 2 && abs(ly) <= height * scale / 2
    }
}

/// The whole scene. Array order is z-order (last = on top).
public struct Board: Codable, Equatable {
    public var items: [BoardItem] = []
    /// Screen position of the world origin, and zoom factor.
    public var offsetX: Double = 0
    public var offsetY: Double = 0
    public var zoom: Double = 1

    public init() {}

    public func topItem(atWorldX x: Double, y: Double) -> BoardItem? {
        items.last { $0.contains(worldX: x, worldY: y) }
    }
}
