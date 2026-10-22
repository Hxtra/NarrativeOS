"""The NarrativeOS catalog: what the system knows (studied references) and what it can do (capabilities), as JSON an app,
a CLI or an agent can list. Every record follows a schema in schemas/.

  python scripts/catalog.py list studies|capabilities [--area A] [--status S]
  python scripts/catalog.py show ID
  python scripts/catalog.py scan                       refresh catalog/capabilities.json from the code (curated entries kept)
  python scripts/catalog.py add-study ID --from DIR --title T [--creator C] [--kind K] [--url U] [--findings FINDINGS.md]
                                       [--picked-by-owner] [--used-for AVEN] [--excerpt "0-120"] [--date YYYY-MM-DD]
  python scripts/catalog.py build                      regenerate catalog/studies/index.json and catalog/README.md
  python scripts/catalog.py check                      schemas, files, and the rights rule (no media, no local paths)

Layout:
  catalog/capabilities.json               every command, script, module and skill: what it does, status, tests
  catalog/third_party.json                everything NarrativeOS uses but did not build: tools, libraries, models, services,
                                          data sources, assets, with licence and status (hand-kept; schemas/third_party.schema.json)
  catalog/studies/<id>/study.json         one studied reference: measurements by department, observations, labels
  catalog/studies/<id>/FINDINGS.md        the written findings (measurements and observations only)
  catalog/studies/index.json, README.md   generated
The full local analysis (frames, stems, curves) stays in NARRATIVEOS_HOME/analysis/<id>/: a reference's footage, frames, words
and transcript never enter the repo (CLAUDE.md).
"""
from __future__ import annotations

import argparse
import ast
import datetime
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAT = ROOT / "catalog"
STUDIES = CAT / "studies"
CAPS = CAT / "capabilities.json"
MEDIA = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mov", ".mkv", ".webm", ".wav", ".mp3", ".flac", ".ogg", ".m4a",
         ".aac", ".npz", ".npy", ".pt", ".safetensors"}
LOCAL_PATH = re.compile(r"((?<![A-Za-z])[A-Za-z]:[\\/]|/Users/|/home/|/c/Users/)")   # not the "s:/" of "https://"
LABELS = ("MEASURED = a tool's number (the tool is named); OBSERVED = seen on frames by a person or Claude; "
          "INFERRED = reasoning from the evidence. Watcher descriptions are never evidence.")


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def save(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def strip_paths(x):
    """Local paths (the owner's machine) never enter the public repo: keep the file name only."""
    if isinstance(x, dict):
        return {k: strip_paths(v) for k, v in x.items()}
    if isinstance(x, list):
        return [strip_paths(v) for v in x]
    if isinstance(x, str) and LOCAL_PATH.search(x):
        return re.sub(r"[A-Za-z]:[\\/][^\s'\"]*[\\/]|/(?:c/)?Users/[^\s'\"]*/|/home/[^\s'\"]*/", "", x)
    return x


# ---------------------------------------------------------------- capabilities
def _doc_line(path: Path) -> str:
    try:
        doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))
    except (SyntaxError, UnicodeDecodeError):
        doc = None
    if not doc:
        return ""
    first = " ".join(doc.strip().split("\n\n")[0].split())
    return first[:300]


def _tests_importing(name: str, pkg: str | None = None) -> list[str]:
    out = []
    pat = re.compile(rf"^\s*(from\s+[\w.]*\b{name}\b|import\s+[\w., ]*\b{name}\b|from\s+{pkg}\s+import\s+[\w, ]*\b{name}\b)" if pkg
                     else rf"^\s*(from\s+[\w.]*\b{name}\b|import\s+[\w., ]*\b{name}\b)", re.M)
    for t in sorted((ROOT / "tests").glob("test_*.py")):
        txt = t.read_text(encoding="utf-8", errors="replace")
        if pat.search(txt) or re.search(rf"\b{name}\.py\b", txt):
            out.append(f"tests/{t.name}")
    return out


AREAS = [("analysis", ("perception",)), ("voice", ("voice", "tts")), ("sound", ("sound", "audio", "sfx", "earshot", "music", "beat")),
         ("picture", ("frame", "vision", "visual", "grade", "contact", "graphics", "caption", "extract")),
         ("render", ("timeline", "compile", "render", "remotion", "retime", "validate_render")),
         ("editing", ("director", "editorial", "edit_patch", "editing", "talking_head", "signature", "variants", "shotspec", "repair")),
         ("publishing", ("publish", "channel", "repetition", "delivery")),
         ("knowledge", ("catalog", "creative_memory", "continuity", "research", "claims", "contradictions", "evidence", "media_semantics")),
         ("pipeline", ("controller", "generation", "model_provider", "cost", "quote", "provenance", "ingest", "acquire", "review", "qa",
                       "simulate", "event_graph", "narration", "script", "word_times", "align"))]


def _area(name: str) -> str | None:
    """A rough grouping by name, for listing; curated entries set their own."""
    for area, keys in AREAS:
        if any(k in name for k in keys):
            return area
    return None


def scan() -> list[dict]:
    caps = []
    for p in sorted((ROOT / "scripts").glob("*.py")):
        src = p.read_text(encoding="utf-8", errors="replace")
        is_cli = "argparse" in src or "__main__" in src
        tests = _tests_importing(p.stem)
        caps.append({"id": f"script.{p.stem}", "kind": "script" if is_cli else "module", "entry": f"scripts/{p.name}",
                     "command": f"python scripts/{p.name} --help" if is_cli else None, "does": _doc_line(p) or "(no docstring)", "area": _area(p.stem),
                     "status": "TESTED" if tests else "IMPLEMENTED", "tests": tests})
    main = (ROOT / "style_intel" / "__main__.py").read_text(encoding="utf-8")
    behind = {"analyze": ["dna"], "profile": ["profile"], "breakdown": ["breakdown"], "compare": ["compare"], "departments": ["departments"],
              "motion": ["motion"], "avsync": ["av_sync", "av_layers"], "soundtags": ["sound_tags"]}       # the module(s) behind each command
    for name, help_ in re.findall(r'add_parser\(\s*"(\w+)"(?:,\s*help="([^"]*)")?', main):
        tests = sorted({t for m in behind.get(name, []) for t in _tests_importing(m, "style_intel")})
        caps.append({"id": f"style_intel.{name}", "kind": "command", "entry": "style_intel/__main__.py",
                     "command": f"python -m style_intel {name} --help", "does": help_ or f"style_intel {name}",
                     "area": "analysis", "status": "TESTED" if tests else "IMPLEMENTED", "tests": tests})
    for p in sorted((ROOT / "style_intel").glob("*.py")):
        if p.name.startswith("__"):
            continue
        tests = _tests_importing(p.stem, "style_intel")
        caps.append({"id": f"module.style_intel.{p.stem}", "kind": "module", "entry": f"style_intel/{p.name}", "command": None,
                     "does": _doc_line(p) or "(no docstring)", "area": "analysis", "status": "TESTED" if tests else "IMPLEMENTED", "tests": tests})
    for sk in sorted(list((ROOT / "skills").glob("*/SKILL.md")) + [ROOT / "SKILL.md", ROOT / "templates" / "narrativeos-video-templates" / "SKILL.md"]):
        if not sk.is_file():
            continue
        head = sk.read_text(encoding="utf-8").split("---")
        meta = head[1] if len(head) > 2 else ""
        name = (re.search(r"^name:\s*(.+)$", meta, re.M) or [None, sk.parent.name])[1].strip()
        desc = (re.search(r"^description:\s*(.+)$", meta, re.M) or [None, ""])[1].strip()
        caps.append({"id": f"skill.{name}", "kind": "skill", "entry": str(sk.relative_to(ROOT)).replace("\\", "/"), "command": None,
                     "does": desc[:300] or name, "area": "skill", "status": "DOCUMENTED", "tests": []})
    old = {c["id"]: c for c in (load(CAPS) if CAPS.is_file() else [])}
    merged = []
    for c in caps:
        o = old.get(c["id"])
        if o and o.get("curated"):
            merged.append(o)                                       # a person checked it: never overwritten
        else:
            c["curated"] = False
            if o:
                for k in ("area", "inputs", "outputs", "docs"):
                    if o.get(k) and not c.get(k):
                        c[k] = o[k]
            merged.append(c)
    gone = [i for i in old if i not in {c["id"] for c in caps}]
    for i in gone:
        print(f"note: {i} is no longer in the code; dropped", file=sys.stderr)
    return merged


# ---------------------------------------------------------------- studies
def _summ_motion(m: dict) -> dict:
    s = m.get("summary", {})
    n = sum(s.get("transitions", {}).values()) if s.get("transitions") else None
    dur = round(m.get("frames", 0) / m["fps"], 2) if m.get("fps") else None        # each block carries the span it measured
    return {"tool": "style_intel.motion", "duration_s": dur,
            "transitions_per_min": round(60 * n / dur, 1) if n and dur else None, "transitions": s.get("transitions"), "gradual_median_frames": s.get("gradual_median_frames"),
            "camera": s.get("camera"), "easing": s.get("easing"), "drawing_rate": s.get("drawing_rate"),
            "push_zoom_median": s.get("push_zoom_median"), "move_seconds_median": s.get("move_seconds_median"), "transitions_total": n}


def _summ_layers(r: dict) -> dict:
    s = r.get("strategy", {})
    return {"tool": "style_intel.avsync (av_layers)", "duration_s": round(r.get("frames", 0) / max(r.get("fps") or 1, 1), 2),
            "strategy": s.get("strategy"), "why": s.get("why"), "borderline": s.get("borderline", []),
            "evidence": s.get("evidence"), "mapping": s.get("mapping"), "grid": r.get("grid"), "camera": r.get("camera"),
            "tempo_bpm": r.get("tempo_bpm"), "layers": r.get("layers"), "uncertainty": r.get("uncertainty")}


def _summ_earshot(rows: list[dict]) -> dict:
    out = {"tool": "script.earshot_bridge (Earshot 0.3.0)"}
    for row in rows:
        if not row.get("ok"):
            continue
        r = row["result"]
        if row["op"] == "timeline":
            sync = (r.get("sync") or {}).get("cuts", {}).get("stats", {})
            out["timeline"] = {"loudness": r.get("loudness"), "duration": r.get("duration"),
                               "cut_sync": {k: sync.get(k) for k in ("n", "hit_within_1_frame", "hit_within_100ms", "chance_within_1_frame",
                                                                       "accent_within_1_frame", "accent_chance_within_1_frame", "median_abs_offset_ms")}}
        elif row["op"] == "realness":
            out["realness"] = {"verdict": r.get("verdict"), "p_real": r.get("p_real")}
        elif row["op"] == "critique":
            key = "critique_" + str(row.get("id", "")).replace("critique_", "")
            out[key] = {"verdict": r.get("verdict"), "score": r.get("score"), "in_range": r.get("in_range"), "scored": r.get("scored"),
                        "profile_n": r.get("profile_n"),
                        "metrics": {m["metric"]: {"value": m.get("value"), "unit": m.get("unit"), "typical": m.get("typical"), "status": m.get("status")}
                                    for m in r.get("metrics", [])}}
    return out


def add_study(sid: str, src: Path, a) -> Path:
    if not re.match(r"^[a-z0-9][a-z0-9_-]{1,63}$", sid):
        raise SystemExit(f"bad id {sid!r}: lower-case letters, digits, - and _")
    meas, tools = {}, []
    found = {p.name: p for p in src.rglob("*.json")}
    if "motion.json" in found:
        meas["picture"] = _summ_motion(load(found["motion.json"])); tools.append("style_intel.motion")
    if "av_layers.json" in found:
        meas["sync"] = _summ_layers(load(found["av_layers.json"])); tools.append("style_intel.avsync")
    for name in ("ear_out.json", "earshot.json"):
        if name in found:
            meas["sound"] = _summ_earshot(load(found[name])); tools.append("script.earshot_bridge")
    if not meas:
        raise SystemExit(f"no measurement files (motion.json, av_layers.json, ear_out.json) under {src}")
    fmt = {"duration_s": None, "width": None, "height": None, "fps": None, "excerpt": a.excerpt}
    spans = [b.get("duration_s") or 0 for b in (meas.get("picture", {}), meas.get("sync", {}))]
    fmt["duration_s"] = max(spans) if any(spans) else None                          # the longest span measured
    if "av_layers.json" in found:
        fmt["fps"] = load(found["av_layers.json"]).get("fps")
    if meas.get("sound", {}).get("timeline", {}).get("duration"):
        fmt["duration_s"] = meas["sound"]["timeline"]["duration"]
    if fmt["duration_s"] is None:
        fmt["duration_s"] = 0
    if a.width:
        fmt["width"], fmt["height"] = a.width, a.height
    study = {"schema_version": 1, "id": sid, "title": a.title, "creator": a.creator,
             "source": {"platform": a.platform, "url": a.url, "owner_supplied_file": True}, "kind": a.kind,
             "picked_by_owner": bool(a.picked_by_owner), "used_for": a.used_for or [], "format": fmt,
             "studied": a.date or datetime.date.today().isoformat(), "tools": sorted(set(tools)), "measurements": strip_paths(meas),
             "observations": [o for o in (a.observation or [])], "labels": LABELS,
             "findings_doc": None, "local_data": f"analysis/{src.name}"}
    out = STUDIES / sid
    if a.findings:
        text = Path(a.findings).read_text(encoding="utf-8")
        if re.search(r"!\[[^\]]*\]\(|\.(jpg|jpeg|png|gif|webp)\b", text, re.I):
            text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "(frame kept locally)", text)
        if LOCAL_PATH.search(text):
            text = strip_paths(text)
        out.mkdir(parents=True, exist_ok=True); (out / "FINDINGS.md").write_text(text, encoding="utf-8")
        study["findings_doc"] = f"catalog/studies/{sid}/FINDINGS.md"
    save(out / "study.json", study)
    return out / "study.json"


def build() -> None:
    rows = []
    for p in sorted(STUDIES.glob("*/study.json")):
        s = load(p); sync = s["measurements"].get("sync", {}); pic = s["measurements"].get("picture", {})
        snd = s["measurements"].get("sound", {}).get("timeline", {}).get("cut_sync", {})
        dur = s["format"].get("duration_s") or 0
        rows.append({"id": s["id"], "title": s["title"], "creator": s.get("creator"), "kind": s["kind"], "duration_s": dur,
                     "studied": s["studied"], "sync_strategy": sync.get("strategy"),
                     "transitions_per_min": pic.get("transitions_per_min"),
                     # a STRONG accent on the transition against chance: "any sound within 100 ms" is near-certain in a busy mix
                     "accent_on_transitions": snd.get("accent_within_1_frame") if snd else None,
                     "accent_chance": snd.get("accent_chance_within_1_frame") if snd else None,
                     "salient_hit_on_transitions": s["measurements"].get("sound", {}).get("critique_docs", {}).get("metrics", {})
                                                    .get("cut_hit_frac", {}).get("value"),
                     "used_for": s.get("used_for", [])})
    save(STUDIES / "index.json", rows)
    lines = ["# Studied references", "", "Generated by `python scripts/catalog.py build` from `catalog/studies/*/study.json`. Measurements only:",
             "the references' footage stays on the owner's machine.", "",
             "| id | title | kind | length | sync strategy | transitions/min | strong accent on transitions (chance) | salient hit within 100 ms |",
             "|---|---|---|---|---|---|---|---|"]
    pct = lambda v: "-" if v is None else f"{round(100 * v)}%"
    for r in rows:
        accent = "-" if r["accent_on_transitions"] is None else f"{pct(r['accent_on_transitions'])} ({pct(r['accent_chance'])})"
        rate = "-" if r["transitions_per_min"] is None else r["transitions_per_min"]
        lines.append(f"| [{r['id']}]({r['id']}/study.json) | {r['title']} | {r['kind']} | {r['duration_s']:.0f} s | {r['sync_strategy'] or '-'} | "
                     f"{rate} | {accent} | {pct(r['salient_hit_on_transitions'])} |")
    (STUDIES / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p.relative_to(CAT.parent))


def check() -> list[str]:
    import jsonschema
    errs = []
    ss, cs = load(ROOT / "schemas" / "study.schema.json"), load(ROOT / "schemas" / "capability.schema.json")
    for p in sorted(STUDIES.glob("*/study.json")):
        try:
            jsonschema.validate(load(p), ss)
        except jsonschema.ValidationError as e:
            errs.append(f"{_rel(p)}: {e.message}")
        s = load(p)
        if s.get("findings_doc") and not (ROOT / s["findings_doc"]).is_file():
            errs.append(f"{_rel(p)}: findings_doc {s['findings_doc']} is missing")
    for c in (load(CAPS) if CAPS.is_file() else []):
        try:
            jsonschema.validate(c, cs)
        except jsonschema.ValidationError as e:
            errs.append(f"capability {c.get('id')}: {e.message}")
        if not (ROOT / c["entry"]).is_file():
            errs.append(f"capability {c['id']}: entry {c['entry']} does not exist")
        for t in c.get("tests", []):
            if not (ROOT / t).is_file():
                errs.append(f"capability {c['id']}: test {t} does not exist")
    tps = load(ROOT / "schemas" / "third_party.schema.json"); tp = CAT / "third_party.json"
    ids = set()
    for t in (load(tp) if tp.is_file() else []):
        try:
            jsonschema.validate(t, tps)
        except jsonschema.ValidationError as e:
            errs.append(f"third_party {t.get('id')}: {e.message}")
        if t.get("id") in ids:
            errs.append(f"third_party {t['id']}: duplicate id")
        ids.add(t.get("id"))
    for p in CAT.rglob("*"):
        if p.is_file() and p.suffix.lower() in MEDIA:
            errs.append(f"{_rel(p)}: media file in the catalog (frames and audio stay in NarrativeOS-Data)")
        if p.is_file() and p.suffix.lower() in (".json", ".md") and LOCAL_PATH.search(p.read_text(encoding="utf-8", errors="replace")):
            errs.append(f"{_rel(p)}: contains a local path of the owner's machine")
    return errs


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = ap.add_subparsers(dest="cmd", required=True)
    p = s.add_parser("list"); p.add_argument("what", choices=["studies", "capabilities", "third-party"]); p.add_argument("--kind"); p.add_argument("--area"); p.add_argument("--status")
    p = s.add_parser("show"); p.add_argument("id")
    s.add_parser("scan"); s.add_parser("build"); s.add_parser("check")
    p = s.add_parser("add-study"); p.add_argument("id"); p.add_argument("--from", dest="src", required=True); p.add_argument("--title", required=True)
    p.add_argument("--creator"); p.add_argument("--kind", default="unknown"); p.add_argument("--platform"); p.add_argument("--url")
    p.add_argument("--findings"); p.add_argument("--picked-by-owner", action="store_true"); p.add_argument("--used-for", nargs="*")
    p.add_argument("--excerpt"); p.add_argument("--date"); p.add_argument("--width", type=int); p.add_argument("--height", type=int)
    p.add_argument("--observation", action="append", help="an OBSERVED/INFERRED statement (label it in the text)")
    a = ap.parse_args()
    if a.cmd == "scan":
        caps = scan(); save(CAPS, caps)
        print(f"{len(caps)} capabilities -> {CAPS.relative_to(ROOT)}  ({sum(c['status'] == 'TESTED' for c in caps)} tested, "
              f"{sum(c.get('curated', False) for c in caps)} curated)")
    elif a.cmd == "add-study":
        print("wrote", add_study(a.id, Path(a.src), a).relative_to(ROOT)); build()
    elif a.cmd == "build":
        build(); print("built", (STUDIES / "index.json").relative_to(ROOT))
    elif a.cmd == "check":
        errs = check(); print("\n".join(errs) or "catalog OK"); sys.exit(1 if errs else 0)
    elif a.cmd == "list":
        if a.what == "third-party":
            for t in load(CAT / "third_party.json"):
                if (a.kind and t["kind"] != a.kind) or (a.status and t["status"] != a.status):
                    continue
                print(f"{t['id']:20s} {t['kind']:15s} {t['status']:12s} {t['name'][:40]:40s} {t['licence'][:40]}")
        elif a.what == "studies":
            for r in (load(STUDIES / "index.json") if (STUDIES / "index.json").is_file() else []):
                print(f"{r['id']:28s} {r['kind']:20s} {r['duration_s']:6.0f} s  {r['sync_strategy'] or '-':24s} {r['title']}")
        else:
            for c in load(CAPS):
                if (a.area and c.get("area") != a.area) or (a.status and c["status"] != a.status):
                    continue
                print(f"{c['id']:40s} {c['status']:11s} {c['does'][:90]}")
    elif a.cmd == "show":
        for p in [STUDIES / a.id / "study.json"]:
            if p.is_file():
                print(json.dumps(load(p), indent=1, ensure_ascii=False)); return
        c = next((c for c in load(CAPS) if c["id"] == a.id), None)
        print(json.dumps(c, indent=1, ensure_ascii=False) if c else f"no study or capability {a.id!r}")


if __name__ == "__main__":
    main()
