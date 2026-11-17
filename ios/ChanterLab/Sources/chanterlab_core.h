// C ABI of chanterlab-core (src/ffi.rs). Keep in sync by hand; it is small.
#ifndef CHANTERLAB_CORE_H
#define CHANTERLAB_CORE_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

// ── Pitch tracker (one thread at a time) ────────────────────────────────────
typedef struct ClpTracker ClpTracker;

ClpTracker *clp_tracker_new(float sample_rate, float gate_on_amp);
void clp_tracker_free(ClpTracker *t);
void clp_tracker_push(ClpTracker *t, const float *samples, size_t len);
float clp_tracker_detect_hz(ClpTracker *t);
bool clp_tracker_gate_open(const ClpTracker *t);
float clp_tracker_level(const ClpTracker *t);
void clp_tracker_set_gate(ClpTracker *t, float gate_on_amp);

// ── Tuning grid (main thread). Returned strings: clp_string_free. ───────────
typedef struct ClpGrid ClpGrid;

void clp_string_free(char *s);
ClpGrid *clp_grid_new(void);
ClpGrid *clp_grid_from_json(const char *json);
void clp_grid_free(ClpGrid *g);
char *clp_grid_to_json(const ClpGrid *g);
char *clp_grid_cells_json(const ClpGrid *g);
double clp_grid_moria_to_hz(const ClpGrid *g, int32_t moria);
double clp_grid_ref_ni_hz(const ClpGrid *g);
void clp_grid_set_ref_ni_hz(ClpGrid *g, double hz);
bool clp_grid_apply_pthora(ClpGrid *g, int32_t moria, const char *genus, const char *degree);
bool clp_grid_apply_custom_genus(ClpGrid *g, int32_t moria, const char *degree, const char *name,
                                 const char *intervals_json, const char *canonical_root);
bool clp_grid_apply_symbol_drop(ClpGrid *g, const char *json);
bool clp_grid_remove_pthora(ClpGrid *g, int32_t moria);
void clp_grid_set_accidental(ClpGrid *g, int32_t moria, int32_t accidental);
int32_t clp_grid_toggle_cell(ClpGrid *g, int32_t moria);
void clp_grid_clear_override(ClpGrid *g, int32_t moria);

// ── Synth. clp_synth_render: audio thread. Everything else: one control
//    thread; calls are queued lock-free and apply at the next render. ────────
typedef struct ClpSynth ClpSynth;

ClpSynth *clp_synth_new(float sample_rate);
void clp_synth_free(ClpSynth *s);
void clp_synth_render(const ClpSynth *s, float *out, size_t len);
void clp_synth_note_on(const ClpSynth *s, int32_t id, float hz, float velocity);
void clp_synth_note_off(const ClpSynth *s, int32_t id);
void clp_synth_retune(const ClpSynth *s, int32_t id, float hz);
void clp_synth_all_notes_off(const ClpSynth *s);
void clp_synth_ison(const ClpSynth *s, float hz, float volume);
void clp_synth_set_voicing(const ClpSynth *s, uint8_t index);
void clp_synth_set_master(const ClpSynth *s, float level);
void clp_synth_click(const ClpSynth *s, float hz, float volume);
void clp_synth_metronome(const ClpSynth *s, float bpm, float volume, uint8_t beats_per_bar);
// Scheduled notes run on the synth clock (samples rendered so far).
uint64_t clp_synth_frames(const ClpSynth *s);
void clp_synth_note_at(const ClpSynth *s, float hz, float velocity, uint64_t start, uint32_t frames,
                       uint8_t voicing);
void clp_synth_clear_scheduled(const ClpSynth *s);

// ── Sampled instrument. Fill a bank, then share it; after that it must not
//    change and must outlive every synth. Voicing 6 in clp_synth_note_at. ────
typedef struct ClpBank ClpBank;

ClpBank *clp_bank_new(void);
void clp_bank_add(ClpBank *bank, float root_midi, float sample_rate, const float *samples, size_t len);
void clp_synth_set_bank(const ClpSynth *s, const ClpBank *bank);

// ── Recording rings: one thread pushes, one pops; never blocks. ─────────────
typedef struct ClpRing ClpRing;

ClpRing *clp_ring_new(size_t capacity);
void clp_ring_free(ClpRing *r);
size_t clp_ring_push(const ClpRing *r, const float *samples, size_t len);
size_t clp_ring_pop(const ClpRing *r, float *out, size_t len);
size_t clp_ring_len(const ClpRing *r);
uint64_t clp_ring_dropped(const ClpRing *r);

// ── Scores and scoring (JSON in, JSON out; free with clp_string_free) ───────
char *clp_score_parse(const char *xml, uint32_t verse);
char *clp_score_lap(const char *targets_json, const char *samples_json, bool strict);

#endif
