"""The whole remake as one EffectCraft project (TEST: shows what is rebuilt and what is not, in a real timeline).

Structure (After Effects style, so a person can scrub and open each part):
- comp "Shots": every measured shot at its frames. A shot with a measured rebuild gets its real layers (footage,
  transforms, masks, LUTs); every other shot is a labelled placeholder solid naming what it should show.
- comp "Captions": one text layer per caption line, at its frames, in the measured font, size and position.
- comp "Remake": the reference's own audio (test only), "Shots", and "Captions" three times with the fitted glow
  (halo blur 60, glow blur 38, sharp blur 2.5; MEASURED on the 42.1 s shot).
"""
from __future__ import annotations

import json
from pathlib import Path

from .effectcraft import js_path

SERIF = "CenturySchoolbook-BoldItalic"
SANS = "FranklinGothic-Heavy"
GLOW = [("halo", 60.0, 100), ("glow", 38.0, 100), ("sharp", 2.5, 100)]   # (name, Gaussian blur, opacity) MEASURED


def _q(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def script(work: Path, captions: list[dict], rebuilt: dict[int, list[dict]], audio: Path | None, save_to: Path,
           size=(1276, 718), fps=29.97) -> str:
    """captions: [{text, first, last, face: serif|sans, x, y, size}]; rebuilt: first frame -> layer dicts (as
    effectcraft.shot_script, with start relative to that shot)."""
    c = json.loads((work / "cuts.json").read_text(encoding="utf-8"))
    n = c["frames"]
    W, H = size
    L = [f"var F = {fps}; var N = {n};",
         f'var shots = app.project.items.addComp("Shots", {W}, {H}, 1, N/F, F);',
         f'var caps = app.project.items.addComp("Captions", {W}, {H}, 1, N/F, F);',
         f'var main = app.project.items.addComp("Remake", {W}, {H}, 1, N/F, F);',
         "function span(l, a, b) { l.startTime = 0; l.inPoint = a / F; l.outPoint = (b + 1) / F; }"]
    describe = _describer(work)
    covered = set()
    for first, layers in rebuilt.items():
        for k, Ly in enumerate(layers):
            i = f"r{first}_{k}"
            st = (first + Ly["start"]) / fps
            L += [f'var f_{i} = app.project.importFile(new ImportOptions(new File({_q(js_path(Ly["src"]))})));',
                  f'var {i} = shots.layers.add(f_{i}); {i}.name = {_q(f"{first}: {Ly["id"]}")};',
                  f'{i}.startTime = {st - Ly["t0"]:.6f}; {i}.inPoint = {st:.6f}; {i}.outPoint = {(first + Ly["frames"]) / fps:.6f};',
                  f'var t_{i} = {i}.property("Transform"); t_{i}.property("Anchor Point").setValue([0, 0]);',
                  f't_{i}.property("Position").setValue([{Ly["x"]:.3f}, {Ly["y"]:.3f}]); t_{i}.property("Scale").setValue([{Ly["sx"]:.4f}, {Ly["sy"]:.4f}]);']
            if Ly.get("mask"):
                a, b, cc, d = Ly["mask"]
                L += [f'var m_{i} = {i}.property("Masks").addProperty("Mask"); var s_{i} = new Shape();',
                      f's_{i}.vertices = [[{a:.2f},{b:.2f}],[{cc:.2f},{b:.2f}],[{cc:.2f},{d:.2f}],[{a:.2f},{d:.2f}]]; s_{i}.closed = true; m_{i}.property("Mask Path").setValue(s_{i});']
            if Ly.get("lut"):
                L += [f'{i}.property("Effects").addProperty("Apply Color LUT");']
        covered.update(range(first, first + layers[0]["frames"]))
    for s in c["shots"]:
        if all(f in covered for f in range(s["first"], s["last"] + 1)):
            continue
        label = f'{s["id"]} {s["first"]}-{s["last"]} SOURCE NOT FOUND: {describe(s)}'[:150]
        L += [f'var p = shots.layers.addSolid([0.11, 0.11, 0.12], {_q(label)}, {W}, {H}, 1); span(p, {s["first"]}, {s["last"]});',
              f'var pt = shots.layers.addText({_q(label)}); span(pt, {s["first"]}, {s["last"]}); pt.name = {_q("label " + s["id"])};',
              f'var pd = pt.property("Source Text").value; pd.fontSize = 18; pd.fillColor = [0.9, 0.47, 0.35]; pd.justification = ParagraphJustification.LEFT_JUSTIFY; pt.property("Source Text").setValue(pd);',
              f'pt.property("Transform").property("Position").setValue([24, {H - 30}]);']
    for k, cap in enumerate(captions):
        L += [f'var c{k} = caps.layers.addText({_q(cap["text"])}); span(c{k}, {cap["first"]}, {cap["last"]});',
              f'var d{k} = c{k}.property("Source Text").value; d{k}.font = {_q(SERIF if cap["face"] == "serif" else SANS)};',
              f'd{k}.fontSize = {cap["size"]}; d{k}.fillColor = [1, 1, 1]; d{k}.justification = ParagraphJustification.CENTER_JUSTIFY;',
              f'c{k}.property("Source Text").setValue(d{k}); c{k}.property("Transform").property("Position").setValue([{cap["x"]:.1f}, {cap["y"]:.1f}]);']
    if audio:
        L += [f'var au = main.layers.add(app.project.importFile(new ImportOptions(new File({_q(js_path(audio))})))); au.name = "reference audio (TEST ONLY)";']
    L += ['var sh = main.layers.add(shots); sh.name = "Shots";']
    for name, blur, op in GLOW:
        L += [f'var g_{name} = main.layers.add(caps); g_{name}.name = "Captions {name}";',
              f'g_{name}.property("Effects").addProperty("Gaussian Blur").property(1).setValue({blur});',
              f'g_{name}.property("Transform").property("Opacity").setValue({op});']
    L += [f'app.project.save(new File({_q(js_path(save_to))})); writeLn("saved " + main.numLayers + " layers in Remake");']
    return "\n".join(L)


def _describer(work: Path):
    import glob
    watched = []
    for f in sorted(glob.glob(str(work / "watch" / "w*_*.json"))):
        watched += json.loads(Path(f).read_text(encoding="utf-8"))["shots"]

    def describe(s):
        best = max(watched, key=lambda w: min(w["last"], s["last"]) - max(w["first"], s["first"]), default=None)
        if best and min(best["last"], s["last"]) >= max(best["first"], s["first"]):
            return best["content"]
        return "not watched"
    return describe
