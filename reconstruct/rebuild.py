"""Rebuild a stretch of the reference from its measured layers, render it with Kdenlive's MLT (melt), and compare
it with the reference frame by frame (VERIFIED or not, with numbers).

Inputs are measurements only: each layer's source file, source time, active picture area, per-frame corners
(reconstruct.layers) and a colour LUT fitted from source/reference pixel pairs. Nothing is placed by eye.
The comparison is per frame: mean absolute error (0-255) and the share of pixels within 12 levels, with an optional
mask (text not yet rebuilt is excluded and said so).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape

import cv2
import numpy as np

MELT = r"C:\Program Files\kdenlive\bin\melt.exe"
LUT_N = 17


def rgb(video: Path, t: float, size: tuple[int, int] | None = None) -> np.ndarray:
    vf = f"scale={size[0]}:{size[1]}" if size else "null"
    png = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.4f}", "-i", str(video), "-frames:v", "1", "-vf", vf, "-f", "image2pipe",
                          "-vcodec", "png", "-"], capture_output=True, check=True).stdout
    return cv2.cvtColor(cv2.imdecode(np.frombuffer(png, np.uint8), 1), cv2.COLOR_BGR2RGB)


def active_area(video: Path, t: float) -> tuple[int, int, int, int]:
    """(x, y, w, h) of the picture inside black bars (pillar/letterbox), MEASURED from a few frames."""
    acc = None
    for dt in (0.0, 0.5, 1.0):
        g = rgb(video, t + dt).max(axis=2)
        acc = g if acc is None else np.maximum(acc, g)
    cols, rows = np.where(acc.max(axis=0) > 24)[0], np.where(acc.max(axis=1) > 24)[0]
    return int(cols[0]), int(rows[0]), int(cols[-1] - cols[0] + 1), int(rows[-1] - rows[0] + 1)


def fit_lut(src_px: np.ndarray, ref_px: np.ndarray, path: Path) -> dict:
    """A 3D LUT (LUT_N^3) mapping source colours to reference colours, fitted by averaging the reference colour of
    the source pixels falling in each cell; cells with no samples take a global affine fit. MEASURED fit error."""
    s = src_px.reshape(-1, 3).astype(np.float32) / 255
    r = ref_px.reshape(-1, 3).astype(np.float32) / 255
    A = np.c_[s, np.ones(len(s))]
    affine, *_ = np.linalg.lstsq(A, r, rcond=None)
    idx = np.clip(np.round(s * (LUT_N - 1)).astype(int), 0, LUT_N - 1)
    flat = idx[:, 0] * LUT_N * LUT_N + idx[:, 1] * LUT_N + idx[:, 2]
    sums = np.zeros((LUT_N ** 3, 3)); counts = np.zeros(LUT_N ** 3)
    np.add.at(sums, flat, r); np.add.at(counts, flat, 1)
    g = np.linspace(0, 1, LUT_N)
    R, G, B = np.meshgrid(g, g, g, indexing="ij")
    grid = np.stack([R, G, B], -1).reshape(-1, 3)
    table = np.c_[grid, np.ones(len(grid))] @ affine
    have = counts >= 8
    table[have] = sums[have] / counts[have][:, None]
    table = np.clip(table, 0, 1)
    # .cube order: red fastest
    t = table.reshape(LUT_N, LUT_N, LUT_N, 3).transpose(2, 1, 0, 3).reshape(-1, 3)
    path.write_text(f"LUT_3D_SIZE {LUT_N}\n" + "\n".join(f"{a:.5f} {b:.5f} {c:.5f}" for a, b, c in t) + "\n", encoding="ascii")
    pred = table[flat]
    return {"cells_from_samples": int(have.sum()), "fit_error": round(float(np.abs(pred - r).mean() * 255), 2), "samples": int(len(s))}


def rect_of(corners: list[list[float]], crop: tuple[int, int, int, int], src_size: tuple[int, int]) -> tuple[float, float, float, float]:
    """Axis-aligned rect (x, y, w, h) in edit pixels of the source's active area, from the full-frame corners."""
    sw, sh = src_size
    cx, cy, cw, ch = crop
    H = cv2.getPerspectiveTransform(np.float32([[0, 0], [sw, 0], [sw, sh], [0, sh]]), np.float32(corners))
    pts = cv2.perspectiveTransform(np.float32([[cx, cy], [cx + cw, cy], [cx + cw, cy + ch], [cx, cy + ch]]).reshape(-1, 1, 2), H).reshape(-1, 2)
    x0, y0 = pts[:, 0].min(), pts[:, 1].min()
    return float(x0), float(y0), float(pts[:, 0].max() - x0), float(pts[:, 1].max() - y0)


def mlt_xml(layers: list[dict], first: int, last: int, size: tuple[int, int], fps: tuple[int, int]) -> str:
    """layers back to front: {id, source, src_in_frame (source frame at the layer's first edit frame), start, end,
    crop (x,y,w,h), lut (path or None), rects {edit_frame: (x,y,w,h)}}."""
    W, H = size
    n = last - first + 1
    out = [f'<?xml version="1.0" encoding="utf-8"?>\n<mlt LC_NUMERIC="C" version="7.37.0">',
           f'<profile description="ref" width="{W}" height="{H}" progressive="1" sample_aspect_num="1" sample_aspect_den="1" '
           f'display_aspect_num="{W}" display_aspect_den="{H}" frame_rate_num="{fps[0]}" frame_rate_den="{fps[1]}" colorspace="709"/>',
           f'<producer id="black" in="0" out="{n - 1}"><property name="mlt_service">color</property><property name="resource">#000000</property></producer>',
           f'<playlist id="pl_black"><entry producer="black" in="0" out="{n - 1}"/></playlist>']
    for L in layers:
        cx, cy, cw, ch = L["crop"]
        filters = [f'<filter><property name="mlt_service">crop</property><property name="left">{cx}</property><property name="top">{cy}</property>'
                   f'<property name="right">{L["src_size"][0] - cx - cw}</property><property name="bottom">{L["src_size"][1] - cy - ch}</property></filter>']
        if L.get("lut"):
            filters.append(f'<filter><property name="mlt_service">avfilter.lut3d</property><property name="av.file">{escape(str(L["lut"]))}</property>'
                           f'<property name="av.interp">tetrahedral</property></filter>')
        length = L["end"] - L["start"] + 1
        out.append(f'<producer id="{L["id"]}" in="{L["src_in_frame"]}" out="{L["src_in_frame"] + length - 1}"><property name="mlt_service">avformat</property>'
                   f'<property name="resource">{escape(str(L["source"]))}</property>{"".join(filters)}</producer>')
        blank = L["start"] - first
        out.append(f'<playlist id="pl_{L["id"]}">' + (f'<blank length="{blank}"/>' if blank else "") +
                   f'<entry producer="{L["id"]}" in="{L["src_in_frame"]}" out="{L["src_in_frame"] + length - 1}"/></playlist>')
    out.append('<tractor id="main"><multitrack><track producer="pl_black"/>' + "".join(f'<track producer="pl_{L["id"]}"/>' for L in layers) + "</multitrack>")
    for k, L in enumerate(layers, 1):
        keys = ";".join(f"{f - first}={x:.2f} {y:.2f} {w:.2f} {h:.2f} 1" for f, (x, y, w, h) in sorted(L["rects"].items()))
        out.append(f'<transition><property name="mlt_service">qtblend</property><property name="a_track">0</property><property name="b_track">{k}</property>'
                   f'<property name="in">{L["start"] - first}</property><property name="out">{L["end"] - first}</property>'
                   f'<property name="rect">{keys}</property><property name="distort">1</property><property name="compositing">0</property></transition>')
    out.append("</tractor></mlt>")
    return "\n".join(out)


def render(mlt: Path, out: Path) -> None:
    subprocess.run([MELT, str(mlt), "-consumer", f"avformat:{out}", "vcodec=libx264", "crf=10", "preset=fast", "an=1", "pix_fmt=yuv420p"],
                   check=True, capture_output=True)


def frames_of(video: Path, first: int, count: int, fps: float, size: tuple[int, int]) -> np.ndarray:
    W, H = size
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{first / fps:.4f}", "-i", str(video), "-frames:v", str(count), "-vf", f"scale={W}:{H}",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3).astype(np.float32)


def compare(ref_video: Path, fps: float, first: int, render_path: Path, mask: np.ndarray | None = None, size: tuple[int, int] = (1276, 718)) -> list[dict]:
    got = frames_of(render_path, 0, 10 ** 6, fps, size)
    ref = frames_of(ref_video, first, len(got), fps, size)
    out = []
    for k in range(min(len(got), len(ref))):
        d = np.abs(ref[k] - got[k]).mean(axis=2)
        m = mask if mask is not None else np.ones(d.shape, bool)
        out.append({"frame": first + k, "mae": round(float(d[m].mean()), 2), "within_12": round(float((d[m] <= 12).mean()), 3)})
    return out
