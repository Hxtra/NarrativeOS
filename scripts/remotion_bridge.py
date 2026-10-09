"""Bridge from the multi-track compiler to the Remotion template project.

The compiler renders graphics (registry templates over transparency) and recipe transitions (the TransitionStack
between two real shots) as short segments, then composites them in its single FFmpeg pass. This module:

- reports whether Remotion can run here (node + the project's node_modules) and why not;
- reads the template, recipe and style registries (scripts/export_registry.mjs), cached by a hash of src/;
- stages project media under public/_nos (gitignored) so templates can staticFile() it;
- renders a batch of segments with scripts/render_segments.mjs, streaming its progress events.

Segments are cached by content key in the project's renders/segments/, so an unchanged graphic never re-renders.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
DESIGN_W, DESIGN_H = 1920, 1080  # the 16:9 design size; renders scale from the design size of their shape
DESIGNS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350)}
RECIPE_FPS = 30                   # recipe windows and layer timings are authored in 30 fps frames


class RemotionError(Exception):
    pass


def aspect_of(width: int, height: int) -> Optional[str]:
    """The design shape a canvas matches (within 1%), or None."""
    if not width or not height:
        return None
    return next((k for k, (w, h) in DESIGNS.items() if abs(width / height - w / h) < 0.01), None)


def project_dir() -> Path:
    return Path(os.environ.get("NARRATIVEOS_REMOTION_PROJECT") or REPO_ROOT / "templates" / "narrativeos-video-templates" / "project").resolve()


def available() -> tuple[bool, str]:
    proj = project_dir()
    if not shutil.which("node"):
        return False, "node is not installed"
    if not (proj / "node_modules" / "@remotion" / "renderer").is_dir():
        return False, f"the Remotion project has no node_modules (run npm install in {proj})"
    return True, ""


def src_hash() -> str:
    """Cheap identity of the Remotion sources: path, size and mtime of every file under src/ plus package.json."""
    proj = project_dir()
    h = hashlib.sha256()
    files = sorted(p for p in (proj / "src").rglob("*") if p.is_file())
    for p in files + [proj / "package.json"]:
        if p.is_file():
            st = p.stat()
            h.update(f"{p.relative_to(proj)}|{st.st_size}|{st.st_mtime_ns}\n".encode())
    return h.hexdigest()[:16]


_registry_mem: dict[str, dict] = {}


def registry() -> dict:
    """{"transitions": [...], "templates": [...], "styles": [...]} from the Remotion sources."""
    ok, why = available()
    if not ok:
        raise RemotionError(why)
    key = src_hash()
    if key in _registry_mem:
        return _registry_mem[key]
    proj = project_dir()
    cache = proj / ".nos-bundle" / f"registry-{key}.json"
    if cache.is_file():
        reg = json.loads(cache.read_text(encoding="utf-8"))
    else:
        r = subprocess.run(["node", "scripts/export_registry.mjs"], cwd=proj, capture_output=True, text=True, encoding="utf-8")
        if r.returncode:
            raise RemotionError(f"could not read the Remotion registries: {r.stderr.strip()[-800:]}")
        reg = json.loads(r.stdout)
        cache.parent.mkdir(parents=True, exist_ok=True)
        for old in cache.parent.glob("registry-*.json"):
            old.unlink(missing_ok=True)
        cache.write_text(json.dumps(reg), encoding="utf-8")
    _registry_mem[key] = reg
    return reg


def recipe(recipe_id: str) -> Optional[dict]:
    return next((r for r in registry()["transitions"] if r["id"] == recipe_id), None)


def file_identity(path: Path) -> str:
    st = path.stat()
    return hashlib.sha256(f"{path.resolve()}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()[:16]


def stage_media(path: Path) -> str:
    """Make a project file reachable by staticFile(): hard link (or copy) it into public/_nos/media. Returns the
    public-relative path."""
    rel = Path("_nos") / "media" / f"{file_identity(path)}{path.suffix.lower()}"
    dest = project_dir() / "public" / rel
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(path, dest)
        except OSError:
            shutil.copy2(path, dest)
    return rel.as_posix()


def stage_dir(key: str) -> tuple[Path, str]:
    """A scratch folder under public/_nos for one render's inputs: (absolute path, public-relative prefix)."""
    rel = Path("_nos") / "work" / key
    d = project_dir() / "public" / rel
    d.mkdir(parents=True, exist_ok=True)
    return d, rel.as_posix()


def render(segments: list[dict], on_event: Optional[Callable[[dict], None]] = None, timeout: float = 7200) -> list[dict]:
    """Render segments (dicts with key, composition, props, scale, transparent, output). Returns the events.
    Raises RemotionError naming every segment that failed."""
    if not segments:
        return []
    ok, why = available()
    if not ok:
        raise RemotionError(why)
    events: list[dict] = []
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump({"bundleKey": src_hash(), "segments": segments}, f)
        jobs = f.name
    try:
        proc = subprocess.Popen(["node", "scripts/render_segments.mjs", jobs], cwd=project_dir(), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8")
        for line in proc.stdout:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            events.append(ev)
            if on_event:
                on_event(ev)
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise RemotionError(f"Remotion render timed out after {timeout:.0f} s")
        err = proc.stderr.read() if proc.stderr else ""
    finally:
        os.unlink(jobs)
    failed = [e for e in events if e.get("type") == "error"]
    if code or failed:
        detail = "; ".join(f"{e.get('key')}: {e.get('message', '')[:600]}" for e in failed) or err.strip()[-1500:]
        raise RemotionError(f"Remotion render failed ({len(failed)} segment(s)): {detail}")
    return events
