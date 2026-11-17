import Foundation

/// One position on the scale ladder, as produced by the Rust core.
struct Cell: Decodable, Identifiable, Equatable {
    let moria: Int
    let degree: String?
    let chromaticPhase: Int?
    let etStep: Int?
    let accidental: Int
    let enabled: Bool
    let regionIdx: Int

    var id: Int { moria }
    /// Sounding position after the accidental.
    var effectiveMoria: Int { moria + accidental }
    /// A cell the scale itself defines (a degree, or a step of an equal-tempered grid).
    var isNote: Bool { degree != nil || etStep != nil }

    enum CodingKeys: String, CodingKey {
        case moria, degree, accidental, enabled
        case chromaticPhase = "chromatic_phase"
        case etStep = "et_step"
        case regionIdx = "region_idx"
    }
}

/// Swift face of the Rust `TuningGrid`. Main thread only.
final class TuningGrid {
    private var raw: OpaquePointer

    init() {
        raw = clp_grid_new()
    }

    /// Restore a grid saved with `json`; nil if the text is not a valid grid.
    init?(json: String) {
        guard let restored = clp_grid_from_json(json) else { return nil }
        raw = restored
    }

    deinit { clp_grid_free(raw) }

    private static func take(_ s: UnsafeMutablePointer<CChar>?) -> String? {
        guard let s else { return nil }
        defer { clp_string_free(s) }
        return String(cString: s)
    }

    var json: String? { Self.take(clp_grid_to_json(raw)) }

    var cells: [Cell] {
        guard let text = Self.take(clp_grid_cells_json(raw)),
              let cells = try? JSONDecoder().decode([Cell].self, from: Data(text.utf8)) else { return [] }
        return cells
    }

    var refNiHz: Double {
        get { clp_grid_ref_ni_hz(raw) }
        set { clp_grid_set_ref_ni_hz(raw, newValue) }
    }

    func hz(moria: Int) -> Double { clp_grid_moria_to_hz(raw, Int32(moria)) }

    @discardableResult
    func applyPthora(at moria: Int, genus: String, degree: String) -> Bool {
        clp_grid_apply_pthora(raw, Int32(moria), genus, degree)
    }

    @discardableResult
    func applyCustomGenus(at moria: Int, degree: String, name: String, intervals: [Int], root: String) -> Bool {
        let json = "[" + intervals.map(String.init).joined(separator: ",") + "]"
        return clp_grid_apply_custom_genus(raw, Int32(moria), degree, name, json, root)
    }

    /// Apply a chroa / general accidental the way the web palette drops it on a
    /// degree. `shading`: Zygos, Kliton, Spathi, Enharmonic, DiesisGeniki,
    /// YfesisGeniki, or "" to clear.
    @discardableResult
    func applyShading(_ shading: String, at moria: Int, degree: String) -> Bool {
        let json = #"{"type":"shading","shading":"\#(shading)","dropMoria":\#(moria),"dropDegree":"\#(degree)"}"#
        return clp_grid_apply_symbol_drop(raw, json)
    }

    @discardableResult
    func removePthora(at moria: Int) -> Bool { clp_grid_remove_pthora(raw, Int32(moria)) }

    func setAccidental(at moria: Int, _ accidental: Int) {
        clp_grid_set_accidental(raw, Int32(moria), Int32(accidental))
    }

    @discardableResult
    func toggleCell(at moria: Int) -> Bool? {
        switch clp_grid_toggle_cell(raw, Int32(moria)) {
        case 1: return true
        case 0: return false
        default: return nil
        }
    }

    func clearOverride(at moria: Int) { clp_grid_clear_override(raw, Int32(moria)) }
}
