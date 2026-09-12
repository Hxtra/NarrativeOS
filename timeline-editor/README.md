# Timeline Editor

Read-only state adapter and narrow revision endpoint for NarrativeOS production artifacts.

## What this is

A FastAPI server plus a React/TypeScript component that display the real
JSON artifacts a NarrativeOS project produces — `timeline.json`,
`approved_assets.json`, `shot_specs.json`, `claim_visual_links.json`, and
so on. It does not run its own production pipeline. It reads what
`scripts/` already wrote to disk.

During `EDITORIAL_QA`, the API also accepts a single kind of write: a shot
timing revision. That revision is applied, re-validated with
`scripts/timeline_ir.py`, and reverted automatically if validation fails.
The API enforces `state.json.current_stage == "EDITORIAL_QA"` for writes.
The component's `editingEnabled` prop controls the UI affordance, but is not
the security boundary.

## What was actually verified before this was written

Both known NarrativeOS project shapes were inspected by running the real
scripts, not by reading source and guessing:

```bash
python3 scripts/simulate_documentary.py --project /tmp/sim_test
```

This surfaced concrete, load-bearing facts that shaped the implementation:

- `assets.json` is **not created** by `simulate_documentary.py`. It only
  exists as an empty stub if you run `scripts/controller.py --init`
  first. The API reports it as `present: false` in the simulation case
  rather than fabricating `{"assets": []}`.
- `approved_assets.json` entries have `shot_id`, `asset_id`, `status`,
  `rights_status`, `evidence_frame_paths`, `usable_interval`. They do
  **not** have `sha256` or `source_url` — those live on
  `asset_candidates.json` / `assets.json` in the manual-acquisition path
  only. The evidence panel does not claim to show a hash it never
  received.
- `events.jsonl` is **not created** by `simulate_documentary.py`, because
  the simulation calls stage scripts directly rather than going through
  `scripts/controller.py`'s `run()`, which is the only code path that
  appends to it. A fresh simulation project genuinely has no event log
  until the timeline-editor's revision endpoint writes the first entry.
- `qa_plan.json` (flat, simulation path) and `qa/technical_qa.json` +
  `qa/editorial_qa.json` (nested, controller-driven path) are two
  different artifacts, not the same file in different locations.
- Every real shot from a fresh simulation has `evidence_frame_paths: []`
  — zero frames — even though its `status` is `simulation_approved`.
  The evidence-level computation treats this as **red / blocked**, not
  green, regardless of the `simulation_approved` status string. A
  simulated approval is not evidence.

## Automated verification

### Backend

```bash
cd timeline-editor
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest tests/ -v
```

26 tests, all running against the real output of
`scripts/simulate_documentary.py` inside a pytest fixture — not hand-written
JSON fixtures. Covered:

- every artifact correctly reported present/absent
- evidence computed correctly for every shot, matching the real
  zero-frame simulation output
- path traversal rejected for `..`, absolute paths, and nested traversal
- a valid revision is applied, persisted to disk, and logged to
  `events.jsonl`
- an invalid revision (`end <= start`) is rejected before any file write
- a revision that would create non-monotonic timing is applied, caught by
  `scripts/timeline_ir.py`, and the file is reverted to its exact
  pre-revision bytes (asserted with a byte-for-byte string comparison,
  not just a status code check)
- WebSocket ping/pong and rejection of unsupported message types

### Frontend

```bash
cd timeline-editor/ui
npm install
npm run typecheck   # tsc --strict, zero errors
npm test            # 10 component tests
npm run build       # emits dist/TimelineEditor.js + .d.ts
```

The test fixtures in `ui/src/__fixtures__/` are not hand-written. They
were captured by calling the real server's `TestClient` against real
simulation output, then saved as JSON. If the API response shape drifts,
these fixtures need regenerating — that's intentional, so schema drift
fails the test suite instead of passing silently against stale fixtures.

## NarrativeOS integration

This directory is integrated under the NarrativeOS repository root. The API
uses `NARRATIVEOS_REPO_ROOT` when set and otherwise resolves the repository
from the checkout layout. Read-only inspection remains available for
simulation projects, while missing evidence and media are shown as blocked or
absent.

## Known limitation

The server was exercised via FastAPI's `TestClient`, which drives the
same ASGI application, routing, and Pydantic validation a real Uvicorn
process would, but does not open a real OS socket. In this development
environment, backgrounded long-running processes did not reliably survive
across tool-call boundaries, so a live `curl` against a real bound port
could not be captured as evidence here. Before relying on this in
production, run it yourself:

```bash
python server/timeline_api_server.py
# in another terminal:
curl http://127.0.0.1:8420/api/health
```

## What this does not do

- Does not perform real research, asset acquisition, or narration —
  those are separate, unimplemented pipeline stages in the parent
  project.
- Does not run the full production pipeline. It reads artifacts and exposes a
  narrow, stage-gated timeline revision endpoint.
- Does not reimplement `scripts/controller.py`'s stage machine. A caller
  wiring this into an agent or a page should consult `state.json` itself
  to decide whether to render editing controls (`editingEnabled` prop).
- Does not invent evidence. If `evidence_frame_paths` is empty, the shot
  is shown blocked, even if some upstream script marked it
  `simulation_approved`.

## Files

```
timeline-editor/
├── README.md                  (this file)
├── requirements.txt           (pinned runtime deps)
├── requirements-dev.txt       (adds pytest + httpx for tests)
├── server/
│   └── timeline_api_server.py
├── tests/
│   └── test_timeline_api_server.py
├── ui/
│   ├── package.json           (pinned, verified-compatible versions)
│   ├── tsconfig.json          (strict, noEmit, for type-checking)
│   ├── tsconfig.build.json    (extends above, emits dist/)
│   ├── jest.config.js
│   └── src/
│       ├── TimelineEditor.tsx
│       ├── TimelineEditor.test.tsx
│       ├── setupTests.ts
│       └── __fixtures__/
│           ├── project_response.json   (captured from real server run)
│           └── evidence_response.json  (captured from real server run)
└── docs/
    └── ARCHITECTURE.md
```

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `NARRATIVEOS_PROJECT_ROOT` | `/tmp/narrativeos-projects` | Directory containing one subfolder per project |
| `NARRATIVEOS_REPO_ROOT` | checkout-derived | NarrativeOS repository containing `scripts/` |

## Running the server

```bash
cd timeline-editor
pip install -r requirements.txt
export NARRATIVEOS_PROJECT_ROOT=/path/to/your/projects
python server/timeline_api_server.py
# listens on 127.0.0.1:8420
```

## Using the component

```tsx
import { TimelineEditor } from "./TimelineEditor";

<TimelineEditor
  apiBaseUrl="http://127.0.0.1:8420"
  projectId="my_project"
  editingEnabled={currentStage === "EDITORIAL_QA"}
/>
```

`editingEnabled` controls the UI affordance. The API independently checks
`state.json` and rejects revision writes outside `EDITORIAL_QA`.
