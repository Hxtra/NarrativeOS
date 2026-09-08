# Architecture and Artifact Contracts

The controller is deliberately ordinary Python plus JSON so it can run on Hermes installations without LangGraph or proprietary services.

## Evidence chain

```text
script → ShotSpec → candidates → frame evidence → approval → timeline → render → QA
```

A stage may be blocked, passed, or awaiting review. A blocked stage must never advance `last_successful_stage`.

## Required asset approval record

```json
{
  "shot_id": "B001-S001",
  "asset_id": "asset_001",
  "status": "approved",
  "local_path": "footage/example.mp4",
  "source_url": "https://example.org/example",
  "rights_status": "verified",
  "evidence_frame_paths": ["qa/assets/asset_001_00.png"],
  "usable_interval": [2.0, 6.0],
  "description_source": "vision-analysis",
  "sha256": "..."
}
```

## Timeline contract

Every shot must contain `shot_id`, `asset_id`, `start`, `end`, `status: approved`, `motion`, and `transition`. The renderer resolves the asset through `assets.json`; it never selects by filename order.

## Vision gate

A technical probe proves only that a file exists and is decodable. Semantic approval requires actual frame evidence and a real configured vision analyzer. If evidence is missing, retain `VISUAL_MATCHING: blocked`.

## Secrets and portability

Use environment variables for services. Never package `.env`, browser profiles, cookies, tokens, or private URLs. Use project-relative paths and `shutil.which("ffmpeg")`/`shutil.which("ffprobe")`.
