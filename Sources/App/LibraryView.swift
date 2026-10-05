import SwiftUI
import UniformTypeIdentifiers
import PicBoardCore

extension UTType {
    static let picboard = UTType(filenameExtension: "picboard", conformingTo: .data) ?? .data
}

/// Lists the boards stored in the app's Documents/Boards folder.
@MainActor
final class Library: ObservableObject {
    @Published var boards: [URL] = []

    let folder: URL = {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let dir = docs.appendingPathComponent("Boards", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }()

    init() { reload() }

    func reload() {
        let urls = (try? FileManager.default.contentsOfDirectory(
            at: folder, includingPropertiesForKeys: [.contentModificationDateKey])) ?? []
        boards = urls.filter { $0.pathExtension == "picboard" }.sorted {
            let a = (try? $0.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
            let b = (try? $1.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
            return a > b
        }
    }

    func uniqueURL(base: String) -> URL {
        var url = folder.appendingPathComponent(base).appendingPathExtension("picboard")
        var n = 2
        while FileManager.default.fileExists(atPath: url.path) {
            url = folder.appendingPathComponent("\(base) \(n)").appendingPathExtension("picboard")
            n += 1
        }
        return url
    }

    func create() -> URL {
        let url = uniqueURL(base: "Untitled Board")
        if let data = try? BoardArchive.encode(board: Board(), assets: [:]) { try? data.write(to: url) }
        reload()
        return url
    }

    func importFile(_ source: URL) {
        let access = source.startAccessingSecurityScopedResource()
        defer { if access { source.stopAccessingSecurityScopedResource() } }
        let dest = uniqueURL(base: source.deletingPathExtension().lastPathComponent)
        try? FileManager.default.copyItem(at: source, to: dest)
        reload()
    }

    func delete(_ url: URL) {
        try? FileManager.default.removeItem(at: url)
        reload()
    }
}

struct LibraryView: View {
    @StateObject private var library = Library()
    @State private var path: [URL] = []
    @State private var importing = false

    var body: some View {
        NavigationStack(path: $path) {
            List {
                ForEach(library.boards, id: \.self) { url in
                    NavigationLink(value: url) {
                        Label(url.deletingPathExtension().lastPathComponent, systemImage: "photo.on.rectangle")
                    }
                    .contextMenu { ShareLink("Export", item: url) }
                }
                .onDelete { offsets in offsets.map { library.boards[$0] }.forEach(library.delete) }
            }
            .overlay {
                if library.boards.isEmpty {
                    ContentUnavailableView("No boards yet", systemImage: "photo.on.rectangle",
                                           description: Text("Tap + to create one."))
                }
            }
            .navigationTitle("Boards")
            .navigationDestination(for: URL.self) { url in
                BoardView(model: BoardModel(url: url)).id(url)
            }
            .toolbar {
                ToolbarItemGroup(placement: .primaryAction) {
                    Button { importing = true } label: { Label("Import", systemImage: "square.and.arrow.down") }
                    Button { path.append(library.create()) } label: { Label("New", systemImage: "plus") }
                }
            }
            .fileImporter(isPresented: $importing, allowedContentTypes: [.picboard, .data]) { result in
                if case .success(let url) = result { library.importFile(url) }
            }
            .onChange(of: path) { _, _ in library.reload() }
        }
    }
}
