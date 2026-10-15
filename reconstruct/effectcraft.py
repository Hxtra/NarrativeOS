"""Rebuild measured shots in EffectCraft (open-source After Effects reimplementation) and render them headless.

The measured layers (source file, source time, scale, position, mask window, colour LUT) become an EffectCraft
project through its After Effects-style JavaScript object model (`effectcraft-cli script`), and
`effectcraft-cli render` renders it. The project (.ecproj, versioned JSON) opens in the EffectCraft app for hand
edits. Placement is done by EffectCraft's own transforms and masks, so what the editor does is what gets compared.

Notes (MEASURED, Oct 15): EffectCraft 0.10.0 reads a variable-frame-rate file at its average rate (30.30 fps for a
29.97 fps CNBC upload), so such sources are first converted to constant 29.97 fps (timestamps kept).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

CLI = r"C:\Program Files\EffectCraft\effectcraft-cli.exe"


def js_path(p: Path | str) -> str:
    return str(p).replace("\\", "/")


def shot_script(name: str, size: tuple[int, int], frames: int, fps: float, layers: list[dict], save_to: Path) -> str:
    """layers back to front: {id, src, t0 (source seconds at the layer's first frame), start (comp frame),
    x, y (top-left of the source frame in comp px), sx, sy (scale %), mask (x0, y0, x1, y1 in source px) or None,
    lut (path) or None}."""
    W, H = size
    out = [f'var comp = app.project.items.addComp("{name}", {W}, {H}, 1, {frames}/{fps}, {fps});',
           f'comp.layers.addSolid([0,0,0], "black", {W}, {H}, 1);']
    for L in layers:
        i, st = L["id"], L["start"] / fps
        out += [f'var f_{i} = app.project.importFile(new ImportOptions(new File("{js_path(L["src"])}")));',
                f'var {i} = comp.layers.add(f_{i}); {i}.name = "{i}";',
                f'{i}.startTime = {st - L["t0"]:.6f}; {i}.inPoint = {st:.6f}; {i}.outPoint = {frames}/{fps};',
                f'var tr_{i} = {i}.property("Transform"); tr_{i}.property("Anchor Point").setValue([0, 0]);',
                f'tr_{i}.property("Position").setValue([{L["x"]:.3f}, {L["y"]:.3f}]);',
                f'tr_{i}.property("Scale").setValue([{L["sx"]:.4f}, {L["sy"]:.4f}]);']
        if L.get("mask"):
            a, b, c, d = L["mask"]
            out += [f'var m_{i} = {i}.property("Masks").addProperty("Mask"); var s_{i} = new Shape();',
                    f's_{i}.vertices = [[{a:.2f}, {b:.2f}], [{c:.2f}, {b:.2f}], [{c:.2f}, {d:.2f}], [{a:.2f}, {d:.2f}]]; s_{i}.closed = true;',
                    f'm_{i}.property("Mask Path").setValue(s_{i});']
        if L.get("lut"):
            out += [f'var lut_{i} = {i}.property("Effects").addProperty("Apply Color LUT");',
                    f'try {{ lut_{i}.property(1).setValue("{js_path(L["lut"])}"); writeLn("lut {i}: " + lut_{i}.property(1).value); }}',
                    f'catch (e) {{ writeLn("lut {i} FAILED " + e); }}']
    out += [f'app.project.save(new File("{js_path(save_to)}")); writeLn("saved");']
    return "\n".join(out)


def run_script(jsx: Path) -> str:
    r = subprocess.run([CLI, "script", str(jsx), "--empty"], capture_output=True, text=True, timeout=600)
    if r.returncode:
        raise RuntimeError(r.stdout[-2000:] + r.stderr[-2000:])
    return r.stdout


def render(project: Path, comp: str, out: Path) -> str:
    r = subprocess.run([CLI, "render", "--project", str(project), "--comp", comp, "--out", str(out), "--format", "h264", "--quality", "best"],
                       capture_output=True, text=True, timeout=1800)
    if r.returncode:
        raise RuntimeError(r.stdout[-2000:] + r.stderr[-2000:])
    return r.stdout
