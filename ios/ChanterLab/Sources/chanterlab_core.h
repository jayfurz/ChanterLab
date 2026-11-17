// C ABI of chanterlab-core (src/ffi.rs). Keep in sync by hand; it is small.
#ifndef CHANTERLAB_CORE_H
#define CHANTERLAB_CORE_H
#include <stdbool.h>
#include <stddef.h>

typedef struct ClpTracker ClpTracker;

ClpTracker *clp_tracker_new(float sample_rate, float gate_on_amp);
void clp_tracker_free(ClpTracker *t);
void clp_tracker_push(ClpTracker *t, const float *samples, size_t len);
float clp_tracker_detect_hz(ClpTracker *t);
bool clp_tracker_gate_open(const ClpTracker *t);
float clp_tracker_level(const ClpTracker *t);
void clp_tracker_set_gate(ClpTracker *t, float gate_on_amp);

#endif
