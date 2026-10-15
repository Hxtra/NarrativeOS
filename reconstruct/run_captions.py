"""Measured captions for a reference, end to end: per-frame reading -> caption runs -> second white-only pass for
spoken words still without a caption -> font per word (render-and-compare) -> per-word layout.

    python -m reconstruct.run_captions VIDEO WORKDIR TRANSCRIPT.json

Writes WORKDIR/captions_measured.json and prints the coverage of spoken words.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from . import caption_faces as CF
from . import captions as C
from .rebuild import frames_of


def run(video: Path, work: Path, transcript: Path, fps: float = 29.97) -> dict:
    rows = [json.loads(line) for line in (work / "ocr_frames.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    words = json.loads(transcript.read_text(encoding="utf-8"))["words"]
    runs = C.assemble(rows, words, fps)
    caps = [c for c in runs if c["status"].startswith("CAPTION")]
    miss1 = C.uncovered_words(caps, words, fps)
    extra = C.second_pass(video, miss1, words, fps)
    caps += extra
    miss2 = C.uncovered_words(caps, words, fps)
    # watcher styles as the labelled fallback for words whose face could not be measured
    watched = []
    for f in sorted((work / "watch").glob("w*_*.json")):
        watched += json.loads(f.read_text(encoding="utf-8")).get("text", [])
    out = []
    for c in sorted(caps, key=lambda c: (c["first"], c["box"][0])):
        n = c["last"] - c["first"] + 1
        fr = frames_of(video, c["first"], n, fps, (C.W, C.H)).astype(np.uint8)
        frames = {c["first"] + k: f for k, f in enumerate(fr)}
        r = CF.classify_run(frames, c)
        c["faces"] = r
        words_out = []
        if r.get("method") == "per word":
            for w in r["words"]:
                img = frames[w.get("frame", r["frame"])]
                mask, (ox, oy) = CF.white_mask(img, c["box"])
                cols = mask[:, w["x"][0] - ox:w["x"][1] - ox + 1]
                ys = np.nonzero(cols)[0]
                face, status = w["face"], w["status"]
                if status == "UNCERTAIN":
                    hint = next((t for t in watched if t["first"] <= c["last"] and t["last"] >= c["first"] and w["text"].lower() in t["words"].lower()), None)
                    if hint:
                        face = "serif" if ("serif" in hint.get("style", "").lower() and "sans" not in hint.get("style", "").lower()) else "sans"
                        status = "UNCERTAIN (face from watcher, OBSERVED)"
                if len(ys):
                    words_out.append(CF.word_layout(w["text"], face, tuple(w["x"]), (oy + int(ys.min()), oy + int(ys.max())))
                                     | {"status": status, "ink_x": list(w["x"]), "ink_bottom": oy + int(ys.max())})
        c["words"] = words_out
        out.append(c)
    # The edit uses one fixed size per face (MEASURED from the confidently measured words). Every word is then set at
    # its face's fixed size; an UNCERTAIN word's face is decided by its ink width at those sizes.
    import statistics
    fixed = {f: round(statistics.median([w["size"] for c in out for w in c["words"] if w["status"] == "MEASURED" and w["face"] == f]), 1)
             for f in ("serif", "sans")}
    for c in out:
        for w in c["words"]:
            ink_w = w["ink_x"][1] - w["ink_x"][0] + 1
            if w["status"] != "MEASURED":
                fw = CF.face_by_width(w["text"], ink_w, fixed)
                w["face"], w["status"], w["width_error"] = fw["face"], fw["status"] if fw["status"] != "UNCERTAIN" else w["status"], fw["width_error"]
            w.update(CF.word_layout_fixed(w["text"], w["face"], fixed[w["face"]], tuple(w["ink_x"]), w["ink_bottom"]))
        if c["words"]:   # one baseline per caption line (the median), not one per noisy word measurement
            line = statistics.median(w["baseline"] for w in c["words"])
            for w in c["words"]:
                w["baseline"] = round(float(line), 1)
    spoken = [w for w in words if C._letters(w["text"])]
    report = {"captions": len(out), "from_first_pass": len(out) - len(extra), "from_white_only_pass": len(extra),
              "spoken_words": len(spoken), "uncovered_after_first_pass": len(miss1), "uncovered_after_second_pass": len(miss2),
              "uncovered": miss2, "faces_measured_words": sum(1 for c in out for w in c["words"] if w["status"] == "MEASURED"),
              "faces_uncertain_words": sum(1 for c in out for w in c["words"] if w["status"] != "MEASURED"),
              "captions_without_word_layout": sum(1 for c in out if not c["words"]), "fixed_sizes": fixed,
              "faces_by_width_words": sum(1 for c in out for w in c["words"] if w["status"].startswith("MEASURED (width"))}
    (work / "captions_measured.json").write_text(json.dumps({"report": report, "captions": out}, indent=1, ensure_ascii=False, default=float),
                                                encoding="utf-8")
    return report


if __name__ == "__main__":
    rep = run(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
    print(json.dumps({k: v for k, v in rep.items() if k != "uncovered"}, indent=1))
    print("still uncovered:", [(w["text"], round(w["start"], 2)) for w in rep["uncovered"]])
