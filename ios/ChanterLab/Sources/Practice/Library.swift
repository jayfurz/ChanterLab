import Foundation
import Observation

/// A piece the singer can load.
struct Piece: Identifiable, Hashable {
    let id: String
    let title: String
    let composer: String
    let arrangement: String
    let group: String
    let sub: String
    let rank: Int
    let tone: Int?
    /// Path under the site root, or nil for the piece bundled with the app.
    let path: String?
    let pdfURL: URL?
    /// Rehearsal sections supplied by the catalog (overrides headings in the score).
    let sections: [ScoreSection]

    static func == (a: Piece, b: Piece) -> Bool { a.id == b.id }
    func hash(into hasher: inout Hasher) { hasher.combine(id) }

    /// Lowercased, accent-free text the search matches against.
    var searchText: String { Library.fold("\(title) \(composer) \(arrangement) \(sub)") }
}

/// The piece catalog: the built-in pieces plus the ingest manifest served by
/// chanterlab.com (the same one the web app reads), cached on disk.
@Observable
final class Library {
    static let site = URL(string: "https://chanterlab.com/")!
    static let prototypeGroup = "Prototype"
    static let groupOrder = ["Prototype", "Divine Liturgy", "Presanctified Liturgy", "Anastasimatarion",
                             "Vespers", "Orthros", "Triodion", "Pentecostarion", "Menaion", "Theotokia",
                             "Other services & misc"]
    /// Bundled so the app has something to practise with no network at all.
    static let bundledID = "control"
    static let preferredFirstPiece = "ingest_10B_Trisagion_Hymn-Hilko-T3-4Lang"

    private(set) var pieces: [Piece] = Library.builtIns
    private(set) var loadingCatalog = false
    private(set) var catalogError: String?

    private static let builtIns: [Piece] = [
        ("trisagion_v", "Trisagion", "antiochian.org · vector", "content/trisagion_vector.musicxml"),
        ("cherubic_v", "Cherubic Hymn", "antiochian.org · vector", "content/cherubic_vector.musicxml"),
        ("anaphora_v", "Anaphora", "antiochian.org · vector", "content/anaphora_vector.musicxml"),
        ("control", "Practice sample (SATB)", "ChanterLab", nil),
    ].enumerated().map { i, p in
        Piece(id: p.0, title: p.1, composer: p.2, arrangement: "Choral", group: prototypeGroup, sub: "",
              rank: i, tone: nil, path: p.3, pdfURL: nil, sections: [])
    }

    private struct ManifestItem: Decodable {
        let id: String
        let title: String?
        let composer: String?
        let arrangementType: String?
        let musicxml: String
        let toneClean: Int?
        let group: String?
        let sub: String?
        let rank: Int?
        let pdfUrl: String?
        let sections: [ScoreSection]?
    }

    private static var cacheDir: URL {
        let dir = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("library", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }
    private static var manifestCache: URL { cacheDir.appendingPathComponent("manifest.json") }

    static func fold(_ text: String) -> String {
        text.folding(options: [.diacriticInsensitive, .caseInsensitive], locale: nil).lowercased()
    }

    func piece(id: String) -> Piece? { pieces.first { $0.id == id } }

    /// Show the cached catalog at once, then refresh it from the site.
    func loadCatalog() async {
        if pieces.count == Self.builtIns.count, let cached = try? Data(contentsOf: Self.manifestCache) {
            adopt(manifest: cached)
        }
        guard !loadingCatalog else { return }
        loadingCatalog = true
        defer { loadingCatalog = false }
        do {
            let url = Self.site.appendingPathComponent("omr/out/ingest/manifest.json")
            let (data, response) = try await URLSession.shared.data(from: url)
            guard (response as? HTTPURLResponse)?.statusCode == 200 else { throw URLError(.badServerResponse) }
            guard adopt(manifest: data) else { throw URLError(.cannotParseResponse) }
            try? data.write(to: Self.manifestCache, options: .atomic)
            catalogError = nil
        } catch {
            // Keep whatever is already showing; only say so when that is just the built-ins.
            if pieces.count == Self.builtIns.count {
                catalogError = "The catalog could not be loaded. Check the connection and try again."
            }
        }
    }

    @discardableResult
    private func adopt(manifest data: Data) -> Bool {
        guard let items = try? JSONDecoder().decode([ManifestItem].self, from: data) else { return false }
        let catalog = items.map { item in
            Piece(id: "ingest_\(item.id)",
                  title: item.title ?? item.id,
                  composer: item.composer ?? "",
                  arrangement: item.arrangementType ?? "",
                  group: item.group ?? "Other services & misc",
                  sub: item.sub ?? "",
                  rank: item.rank ?? .max,
                  tone: item.toneClean,
                  path: "omr/" + item.musicxml,
                  pdfURL: item.pdfUrl.flatMap(URL.init(string:)),
                  sections: item.sections ?? [])
        }
        pieces = Self.builtIns + catalog
        return true
    }

    /// MusicXML text for a piece: bundled, cached, or downloaded (then cached).
    func musicXML(for piece: Piece) async throws -> String {
        guard let path = piece.path else {
            guard let url = Bundle.main.url(forResource: "control_satb", withExtension: "musicxml") else {
                throw URLError(.fileDoesNotExist)
            }
            return try String(contentsOf: url, encoding: .utf8)
        }
        let cached = Self.cacheDir.appendingPathComponent(piece.id + ".musicxml")
        if let text = try? String(contentsOf: cached, encoding: .utf8) { return text }
        let (data, response) = try await URLSession.shared.data(from: Self.site.appendingPathComponent(path))
        guard (response as? HTTPURLResponse)?.statusCode == 200, let text = String(data: data, encoding: .utf8) else {
            throw URLError(.badServerResponse)
        }
        try? data.write(to: cached, options: .atomic)
        return text
    }

    /// Pieces matching `query` and `tone`, grouped in catalog order.
    func groups(query: String, tone: Int?) -> [(name: String, pieces: [Piece])] {
        let tokens = Self.fold(query).split(separator: " ").map(String.init)
        let matches = pieces.filter { piece in
            if let tone, piece.tone != tone { return false }
            guard !tokens.isEmpty else { return true }
            let text = piece.searchText
            return tokens.allSatisfy { token in
                // Short and numeric tokens must start a word ("tone 1" is not "tone 11").
                if token.count == 1 || token.allSatisfy(\.isNumber) {
                    return text.split(whereSeparator: { !$0.isLetter && !$0.isNumber }).contains { $0.hasPrefix(token) }
                }
                return text.contains(token)
            }
        }
        let byGroup = Dictionary(grouping: matches, by: \.group)
        let order = Self.groupOrder + byGroup.keys.filter { !Self.groupOrder.contains($0) }.sorted()
        return order.compactMap { name in
            guard let items = byGroup[name] else { return nil }
            return (name, items.sorted { ($0.rank, $0.title) < ($1.rank, $1.title) })
        }
    }
}
