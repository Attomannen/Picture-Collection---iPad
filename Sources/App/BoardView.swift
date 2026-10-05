import SwiftUI
import PhotosUI
import UniformTypeIdentifiers
import PicBoardCore

struct BoardView: View {
    @StateObject var model: BoardModel
    @Environment(\.scenePhase) private var scenePhase
    @State private var pickerItems: [PhotosPickerItem] = []
    @State private var importingFiles = false

    init(model: BoardModel) { _model = StateObject(wrappedValue: model) }

    var body: some View {
        GeometryReader { geo in
            canvas
                .onAppear { model.viewSize = geo.size; if model.board.offsetX == 0 && model.board.offsetY == 0 { model.fitAll() } }
                .onChange(of: geo.size) { _, new in model.viewSize = new }
        }
        .ignoresSafeArea(edges: .bottom)
        .navigationTitle(model.url.deletingPathExtension().lastPathComponent)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar { toolbar }
        .onChange(of: pickerItems) { _, items in loadPicked(items) }
        .onChange(of: scenePhase) { _, phase in if phase != .active { model.saveNow() } }
        .onDisappear { model.saveNow() }
        .fileImporter(isPresented: $importingFiles, allowedContentTypes: [.image],
                      allowsMultipleSelection: true) { result in
            guard case .success(let urls) = result else { return }
            for url in urls {
                let access = url.startAccessingSecurityScopedResource()
                if let data = try? Data(contentsOf: url) { model.addImage(data: data) }
                if access { url.stopAccessingSecurityScopedResource() }
            }
        }
    }

    // MARK: Canvas

    private var canvas: some View {
        let board = model.board
        return ZStack {
            Color(white: 0.16)
            ForEach(board.items) { item in
                if let img = model.image(for: item.asset) {
                    ItemView(item: item, image: img, board: board, selected: item.id == model.selection)
                }
            }
        }
        .clipped()
        .contentShape(Rectangle())
        .gesture(
            DragGesture(minimumDistance: 0)
                .onChanged { model.dragChanged(start: $0.startLocation, translation: $0.translation) }
                .onEnded { _ in model.dragEnded() }
                .simultaneously(with:
                    MagnifyGesture()
                        .onChanged { model.magnifyChanged($0.magnification) }
                        .onEnded { _ in model.magnifyEnded() })
                .simultaneously(with:
                    RotateGesture()
                        .onChanged { model.rotateChanged($0.rotation.radians) }
                        .onEnded { _ in model.rotateEnded() })
        )
        .onDrop(of: [.image], isTargeted: nil) { providers, location in
            for p in providers {
                p.loadDataRepresentation(forTypeIdentifier: UTType.image.identifier) { data, _ in
                    guard let data else { return }
                    Task { @MainActor in model.addImage(data: data, at: location) }
                }
            }
            return true
        }
    }

    // MARK: Toolbar

    @ToolbarContentBuilder
    private var toolbar: some ToolbarContent {
        ToolbarItemGroup(placement: .primaryAction) {
            PhotosPicker(selection: $pickerItems, matching: .images) {
                Label("Photos", systemImage: "photo")
            }
            Button { importingFiles = true } label: { Label("Files", systemImage: "folder") }
            Button { model.paste() } label: { Label("Paste", systemImage: "doc.on.clipboard") }
            Button { model.fitAll() } label: { Label("Fit", systemImage: "arrow.up.left.and.down.right.magnifyingglass") }
            Button { model.undo() } label: { Label("Undo", systemImage: "arrow.uturn.backward") }
                .disabled(!model.canUndo)
        }
        ToolbarItemGroup(placement: .bottomBar) {
            if model.selection != nil {
                Button { model.flipSelected() } label: { Label("Flip", systemImage: "arrow.left.and.right.righttriangle.left.righttriangle.right") }
                Button { model.duplicateSelected() } label: { Label("Duplicate", systemImage: "plus.square.on.square") }
                Button { model.bringToFront() } label: { Label("To Front", systemImage: "square.3.layers.3d.top.filled") }
                Button { model.sendToBack() } label: { Label("To Back", systemImage: "square.3.layers.3d.bottom.filled") }
                Button(role: .destructive) { model.deleteSelected() } label: { Label("Delete", systemImage: "trash") }
            }
        }
    }

    private func loadPicked(_ items: [PhotosPickerItem]) {
        guard !items.isEmpty else { return }
        Task {
            for item in items {
                if let data = try? await item.loadTransferable(type: Data.self) {
                    model.addImage(data: data)
                }
            }
            pickerItems = []
        }
    }
}

private struct ItemView: View {
    let item: BoardItem
    let image: UIImage
    let board: Board
    let selected: Bool

    var body: some View {
        let w = item.width * item.scale * board.zoom
        let h = item.height * item.scale * board.zoom
        Image(uiImage: image)
            .resizable()
            .frame(width: w, height: h)
            .scaleEffect(x: item.flipped ? -1 : 1, y: 1)
            .overlay(Rectangle().strokeBorder(Color.accentColor, lineWidth: 2).opacity(selected ? 1 : 0))
            .rotationEffect(.radians(item.rotation))
            .position(x: item.x * board.zoom + board.offsetX,
                      y: item.y * board.zoom + board.offsetY)
            .allowsHitTesting(false)
    }
}
