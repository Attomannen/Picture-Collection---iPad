import SwiftUI
import UIKit
import PicBoardCore

@MainActor
final class BoardModel: ObservableObject {
    @Published var board: Board { didSet { scheduleSave() } }
    @Published var selection: UUID?
    @Published private(set) var canUndo = false

    let url: URL
    var viewSize: CGSize = .zero

    private var assets: [String: Data] = [:]
    private var images: [String: UIImage] = [:]
    private var undoStack: [Board] = []
    private var saveTask: Task<Void, Never>?

    init(url: URL) {
        self.url = url
        if let data = try? Data(contentsOf: url), !data.isEmpty,
           let decoded = try? BoardArchive.decode(data) {
            board = decoded.board
            assets = decoded.assets
        } else {
            board = Board()
        }
    }

    // MARK: Persistence

    private func scheduleSave() {
        saveTask?.cancel()
        saveTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 800_000_000)
            if !Task.isCancelled { self?.saveNow() }
        }
    }

    func saveNow() {
        saveTask?.cancel()
        guard let data = try? BoardArchive.encode(board: board, assets: assets) else { return }
        try? data.write(to: url, options: .atomic)
    }

    // MARK: Images

    func image(for asset: String) -> UIImage? {
        if let img = images[asset] { return img }
        guard let data = assets[asset], let img = UIImage(data: data) else { return nil }
        images[asset] = img
        return img
    }

    /// Adds an image at `screenPoint` (defaults to the middle of the view).
    func addImage(data: Data, at screenPoint: CGPoint? = nil) {
        guard let img = UIImage(data: data) else { return }
        pushUndo()
        let key = UUID().uuidString
        assets[key] = data
        images[key] = img

        let px = CGSize(width: img.size.width * img.scale, height: img.size.height * img.scale)
        let fit = 400 / max(px.width, px.height, 1)
        let p = screenPoint ?? CGPoint(x: viewSize.width / 2, y: viewSize.height / 2)
        let w = worldPoint(p)
        let jitter = Double(board.items.count % 6) * 20
        let item = BoardItem(asset: key, x: w.x + jitter, y: w.y + jitter,
                             width: px.width * fit, height: px.height * fit)
        board.items.append(item)
        selection = item.id
    }

    func paste() {
        let pb = UIPasteboard.general
        if let data = pb.data(forPasteboardType: "public.png") ?? pb.data(forPasteboardType: "public.jpeg") {
            addImage(data: data)
        } else if let img = pb.image, let data = img.pngData() {
            addImage(data: data)
        }
    }

    // MARK: Coordinates

    func worldPoint(_ p: CGPoint) -> (x: Double, y: Double) {
        ((p.x - board.offsetX) / board.zoom, (p.y - board.offsetY) / board.zoom)
    }

    // MARK: Undo

    private func pushUndo() {
        undoStack.append(board)
        if undoStack.count > 50 { undoStack.removeFirst() }
        canUndo = true
    }

    func undo() {
        guard let prev = undoStack.popLast() else { return }
        // Undo restores content but keeps the current viewport.
        var restored = prev
        restored.offsetX = board.offsetX; restored.offsetY = board.offsetY; restored.zoom = board.zoom
        board = restored
        if let s = selection, !board.items.contains(where: { $0.id == s }) { selection = nil }
        canUndo = !undoStack.isEmpty
    }

    // MARK: Gestures

    private enum DragTarget {
        case item(UUID, startX: Double, startY: Double)
        case canvas(startX: Double, startY: Double)
    }
    private var dragTarget: DragTarget?
    private var magnifyBase: Double?
    private var rotateBase: Double?

    private func index(of id: UUID) -> Int? { board.items.firstIndex { $0.id == id } }

    func dragChanged(start: CGPoint, translation: CGSize) {
        if dragTarget == nil {
            let w = worldPoint(start)
            if let hit = board.topItem(atWorldX: w.x, y: w.y) {
                selection = hit.id
                pushUndo()
                dragTarget = .item(hit.id, startX: hit.x, startY: hit.y)
            } else {
                selection = nil
                dragTarget = .canvas(startX: board.offsetX, startY: board.offsetY)
            }
        }
        switch dragTarget {
        case .item(let id, let sx, let sy):
            if let i = index(of: id) {
                board.items[i].x = sx + translation.width / board.zoom
                board.items[i].y = sy + translation.height / board.zoom
            }
        case .canvas(let sx, let sy):
            board.offsetX = sx + translation.width
            board.offsetY = sy + translation.height
        case nil: break
        }
    }

    func dragEnded() { dragTarget = nil }

    func magnifyChanged(_ factor: Double) {
        if let id = selection, let i = index(of: id) {
            if magnifyBase == nil { pushUndo(); magnifyBase = board.items[i].scale }
            board.items[i].scale = min(max(magnifyBase! * factor, 0.02), 50)
        } else {
            if magnifyBase == nil { magnifyBase = board.zoom }
            let newZoom = min(max(magnifyBase! * factor, 0.05), 20)
            // Zoom about the middle of the view.
            let c = CGPoint(x: viewSize.width / 2, y: viewSize.height / 2)
            let wx = (c.x - board.offsetX) / board.zoom, wy = (c.y - board.offsetY) / board.zoom
            board.zoom = newZoom
            board.offsetX = c.x - wx * newZoom
            board.offsetY = c.y - wy * newZoom
        }
    }

    func magnifyEnded() { magnifyBase = nil }

    func rotateChanged(_ radians: Double) {
        guard let id = selection, let i = index(of: id) else { return }
        if rotateBase == nil { pushUndo(); rotateBase = board.items[i].rotation }
        board.items[i].rotation = rotateBase! + radians
    }

    func rotateEnded() { rotateBase = nil }

    // MARK: Item commands

    func deleteSelected() {
        guard let id = selection, let i = index(of: id) else { return }
        pushUndo(); board.items.remove(at: i); selection = nil
    }

    func duplicateSelected() {
        guard let id = selection, let i = index(of: id) else { return }
        pushUndo()
        var copy = board.items[i]
        copy.id = UUID(); copy.x += 30; copy.y += 30
        board.items.append(copy)
        selection = copy.id
    }

    func flipSelected() {
        guard let id = selection, let i = index(of: id) else { return }
        pushUndo(); board.items[i].flipped.toggle()
    }

    func bringToFront() {
        guard let id = selection, let i = index(of: id) else { return }
        pushUndo(); board.items.append(board.items.remove(at: i))
    }

    func sendToBack() {
        guard let id = selection, let i = index(of: id) else { return }
        pushUndo(); board.items.insert(board.items.remove(at: i), at: 0)
    }

    /// Zoom and pan so every item is visible.
    func fitAll() {
        guard !board.items.isEmpty, viewSize.width > 0 else {
            board.zoom = 1; board.offsetX = viewSize.width / 2; board.offsetY = viewSize.height / 2
            return
        }
        var minX = Double.infinity, minY = Double.infinity
        var maxX = -Double.infinity, maxY = -Double.infinity
        for it in board.items {
            let hw = it.width * it.scale / 2, hh = it.height * it.scale / 2
            let c = cos(it.rotation), s = sin(it.rotation)
            for (cx, cy) in [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)] {
                let px = it.x + cx * c - cy * s, py = it.y + cx * s + cy * c
                minX = min(minX, px); maxX = max(maxX, px)
                minY = min(minY, py); maxY = max(maxY, py)
            }
        }
        let margin = 0.9
        let zoom = min(viewSize.width * margin / max(maxX - minX, 1),
                       viewSize.height * margin / max(maxY - minY, 1))
        board.zoom = min(max(zoom, 0.05), 20)
        board.offsetX = viewSize.width / 2 - (minX + maxX) / 2 * board.zoom
        board.offsetY = viewSize.height / 2 - (minY + maxY) / 2 * board.zoom
    }
}
