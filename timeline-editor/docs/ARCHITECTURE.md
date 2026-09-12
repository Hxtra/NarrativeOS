# Architecture

## State adapter, not a second pipeline

The server reads JSON artifacts that `scripts/*.py` already produced. It
does not run research, asset acquisition, or narration itself, and it does
not maintain its own copy of production state beyond what's on disk at
request time.

```
scripts/simulate_documentary.py  (or scripts/controller.py, staged)
    ↓ writes
timeline.json, approved_assets.json, shot_specs.json, ... (on disk)
    ↓ read fresh on every request, no caching
server/timeline_api_server.py
    ↓ serves JSON over REST, pushes revision events over WebSocket
ui/src/TimelineEditor.tsx
```

Every artifact the server returns is wrapped as `{present, data, error?}`.
A missing artifact and an empty artifact are different facts and the API
does not conflate them — see README.md for the concrete case
(`assets.json` genuinely does not exist for a fresh simulation project).

## Two real project shapes, one server

`scripts/simulate_documentary.py` and `scripts/controller.py --init`
produce different file layouts (flat `qa_plan.json` vs. nested
`qa/technical_qa.json`, presence/absence of `assets.json` and
`events.jsonl`). The server probes for both and does not assume either is
present. This was verified by actually running both, not inferred from
reading the scripts.

## Evidence computation

`evidence_status_for_shot()` in `timeline_api_server.py` is the single
place that decides red/yellow/green. It requires, from
`approved_assets.json`:

- `len(evidence_frame_paths) >= 3`
- `rights_status in ("verified", "public-domain-simulation")`
- `status in ("approved", "simulation_approved")`

A shot with `status: simulation_approved` but zero evidence frames is
**red**, not yellow — `simulation_approved` describes how the simulation
labeled it, not whether real evidence exists. This distinction is
covered by an explicit test
(`test_simulation_shots_flagged_red_due_to_zero_evidence_frames`).

## The one write path: shot revision

```
POST /api/project/{id}/revision {shot_id, new_start?, new_end?, reason}
    ↓
reject immediately if end <= start (no file touched)
    ↓
write timeline.json with the change applied
    ↓
run scripts/timeline_ir.py --project {path}
    ↓
if it exits non-zero: restore the exact pre-write file bytes, return 422
if it exits zero: append an event to events.jsonl, broadcast over WebSocket, return 200
```

The "restore exact bytes" behavior is asserted with a string equality
check in tests, not just a status-code check, specifically to catch a
partial-write bug where the revert logic writes *something* back but not
byte-identically what was there before.

The server does not decide whether revision requests should be accepted
right now (i.e., whether the project is in `EDITORIAL_QA`). That decision
belongs to whatever orchestrates the pipeline and knows the current
`state.json["current_stage"]`. The React component takes `editingEnabled`
as a prop for the same reason — it is not this component's job to
reimplement `scripts/controller.py`'s stage machine.

## What is not built yet

There is no Research, Claims, Audio, or QA panel. There is one panel:
Timeline, plus a per-shot detail view. Expanding to more panels means
adding more read-only endpoints following the same `{present, data}`
pattern — it does not require changing how the existing endpoints work.
