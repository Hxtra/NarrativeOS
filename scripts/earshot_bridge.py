"""Bridge to Earshot ("ears for coding agents", MIT, https://github.com/Leonxlnx/earshot): NarrativeOS runs a batch of listening
jobs in Earshot's own Python 3.12 environment, in ONE process, so the CLAP and AudioSet models load once (each CLI call loads
them again, 20-40 s).

  python scripts/earshot_bridge.py JOBS.json OUT.json

JOBS.json: [{"id": "creak", "op": "match", "args": ["file.mp3", "a wooden creak"], "kwargs": {"alts": ["a mouse squeak"]}}, ...]
ops: describe, match, rank, find, compare, ab, realness, realness_many, timeline, critique, profile, measure,
     sfx_list, sfx_render, sfx_check (the names of earshot.api). Never llm_critique: it uploads audio (only with the owner's
     explicit consent, per Earshot itself).
Each result is {"id", "op", "ok", "result" | "error"}; one failing job does not stop the batch.

Where Earshot lives: EARSHOT_PY (its venv's python), default NarrativeOS-Data/tools/earshot/.venv/Scripts/python.exe
(installed Oct 22 at commit 925ebe5 = v0.3.0). What Earshot can and cannot judge: its docs/LIMITS.md, summarised in
skills/narrativeos-sound-design/SKILL.md.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HOME = Path(os.environ.get("NARRATIVEOS_HOME", Path.home() / "NarrativeOS-Data"))
EARSHOT_PY = Path(os.environ.get("EARSHOT_PY", HOME / "tools" / "earshot" / ".venv" / "Scripts" / "python.exe"))
ALLOWED = {"describe", "match", "rank", "find", "compare", "ab", "realness", "realness_many", "timeline", "critique", "profile",
           "measure", "sfx_list", "sfx_render", "sfx_check"}

RUNNER = r'''
import json, sys, traceback
from earshot import api
jobs = json.load(open(sys.argv[1], encoding="utf-8")); out = []
def plain(x):
    try:
        json.dumps(x); return x
    except TypeError:
        if isinstance(x, dict): return {str(k): plain(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)): return [plain(v) for v in x]
        if hasattr(x, "tolist"): return x.tolist()
        return str(x)
for j in jobs:
    try:
        r = getattr(api, j["op"])(*j.get("args", []), **j.get("kwargs", {}))
        out.append({"id": j.get("id"), "op": j["op"], "ok": True, "result": plain(r)})
    except Exception as e:
        out.append({"id": j.get("id"), "op": j["op"], "ok": False, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-600:]})
    print(f"{len(out)}/{len(jobs)} {j['op']} {j.get('id', '')}", file=sys.stderr, flush=True)
json.dump(out, open(sys.argv[2], "w", encoding="utf-8"), indent=1)
'''


def run(jobs: list[dict], out: Path, timeout: int = 7200) -> list[dict]:
    bad = [j.get("op") for j in jobs if j.get("op") not in ALLOWED]
    if bad:
        raise SystemExit(f"not allowed: {bad} (llm_critique uploads audio and is never run from here)")
    if not EARSHOT_PY.is_file():
        raise SystemExit(f"Earshot is not installed at {EARSHOT_PY} (set EARSHOT_PY); see skills/narrativeos-sound-design/SKILL.md")
    out = Path(out); out.parent.mkdir(parents=True, exist_ok=True)
    jf = out.with_suffix(".jobs.json"); jf.write_text(json.dumps(jobs), encoding="utf-8")
    rf = out.with_suffix(".runner.py"); rf.write_text(RUNNER, encoding="utf-8")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    local = EARSHOT_PY.parents[2] / "models_local"            # the pinned model files, fetched with curl when the Hugging Face
    for var, sub in (("EARSHOT_CLAP", "clap"), ("EARSHOT_AST", "ast")):     # client stalled (MEASURED Oct 22: 0 bytes in 10 min)
        if var not in env and (local / sub / "model.safetensors").is_file():
            env[var] = str(local / sub)
    subprocess.run([str(EARSHOT_PY), "-I", str(rf), str(jf), str(out)], check=True, timeout=timeout, env=env)
    rf.unlink(missing_ok=True)
    return json.loads(out.read_text(encoding="utf-8"))


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    res = run(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")), Path(sys.argv[2]))
    print(f"{sum(r['ok'] for r in res)}/{len(res)} jobs ok -> {sys.argv[2]}")


if __name__ == "__main__":
    main()
