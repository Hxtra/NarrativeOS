"""Frame awareness: the camera path, mapping measured points through the crop, subject-following reframes and text
behind the subject, measured on real detections of a real face (a public-domain NASA portrait moving across a
16:9 frame). Detector tests skip when MediaPipe or its models are missing."""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
import compile_timeline as ct  # noqa: E402
import frame_awareness as fa  # noqa: E402

PORTRAIT = ROOT / "templates" / "narrativeos-video-templates" / "media-library" / "processed" / "nasa_eileen_collins_001.jpg"


# ----------------------------------------------------------------------------------------------- pure rules
def test_the_camera_holds_through_jitter_and_leads_a_real_move():
    jitter = [(i / 6, 0.5 + (0.01 if i % 2 else -0.01), 0.5) for i in range(30)]
    keys = fa.camera_keys(jitter, 0.316, 1.0)
    assert len(keys) == 1 and abs(keys[0][1] - 0.5) <= 0.011  # small wobble: one key, the camera never moves
    move = [(i / 6, 0.3 if i < 12 else 0.7, 0.5) for i in range(36)]  # the subject jumps at t = 2.0
    keys = fa.camera_keys(move, 0.316, 1.0, lead_sec=0.2, move_sec=0.5)
    assert keys[0] == [0.0, 0.3, 0.5] and keys[-1][1] == 0.7
    start = next(k[0] for k in keys if k[1] == 0.3 and k[0] > 0)
    assert start == pytest.approx(2.0 - 0.2, abs=1 / 6)  # the move starts before the subject arrives
    edge = [(i / 6, 0.98, 0.5) for i in range(12)]
    assert fa.camera_keys(edge, 0.316, 1.0)[0][1] == pytest.approx(1 - 0.316 / 2)  # the crop never leaves the frame


def test_measured_points_land_where_the_crop_puts_them():
    it = {"id": "A", "timeline_in": 0, "timeline_out": 4, "source_in": 10.0, "reframe": {"keys": [[10.0, 0.3, 0.5], [12.0, 0.3, 0.5], [13.0, 0.7, 0.5]]}}
    # 16:9 source into a 9:16 frame: the crop is 0.316 of the source width, centred on the reframe position.
    assert ct.frame_point(it, 10.5, 0.3, 0.4, 16 / 9, 1080, 1920) == pytest.approx((0.5, 0.4))
    assert ct.frame_point(it, 14.0, 0.7, 0.4, 16 / 9, 1080, 1920) == pytest.approx((0.5, 0.4))
    assert ct.reframe_centre(it, 12.5) == pytest.approx((0.5, 0.5))  # half way through the eased move
    ir = {"ir_version": "3.0", "canvas": {"width": 1080, "height": 1920, "fps": 30, "sample_rate": 48000}, "tracks": [
        {"id": "v", "kind": "video", "items": [{**it, "asset_id": "raw"}]},
        {"id": "m", "kind": "graphic", "items": [{"id": "MK", "template": "anchor_marker", "timeline_in": 0.5, "timeline_out": 2,
                                                   "params": {"anchors": [{"asset_id": "raw", "src_t": 11.0, "x": 0.35, "y": 0.6, "aspect": 16 / 9},
                                                                          {"asset_id": "raw", "src_t": 99.0, "x": 0.5, "y": 0.5}]}}]}]}
    anchors = ct.resolve_dynamic(ir)["tracks"][1]["items"][0]["params"]["anchors"]
    assert anchors == [{"t": 0.5, "x": pytest.approx(0.6581, abs=1e-3), "y": 0.6}]  # the point outside every shot is dropped


# ----------------------------------------------------------------------------------------------- measured on a real face
def _vision() -> bool:
    try:
        import mediapipe  # noqa: F401
        import vision_models
        return all(v["status"] == "ready" for v in vision_models.status().values())
    except ImportError:
        return False


needs_vision = pytest.mark.skipif(not _vision(), reason="needs mediapipe and the vision models (python scripts/vision_models.py fetch)")


@pytest.fixture()
def moving(tmp_path):
    """The portrait holds left (0-2 s), slides right (2-3 s), holds right (3-6 s) on a 16:9 frame."""
    (tmp_path / "media").mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x2a3340:s=1920x1080:r=30:d=6", "-loop", "1", "-t", "6", "-i", str(PORTRAIT),
                    "-filter_complex", "[1:v]scale=-2:900[p];[0:v][p]overlay=x='if(lt(t,2),120,if(lt(t,3),120+(t-2)*900,1020))':y=90:shortest=1,format=yuv420p",
                    "-c:v", "libx264", "-crf", "18", str(tmp_path / "media" / "moving.mp4")], check=True)
    (tmp_path / "assets.json").write_text(json.dumps({"assets": [{"asset_id": "mov", "local_path": "media/moving.mp4", "status": "approved"}]}))
    return tmp_path


def face_x(path: Path, fps: float = 2) -> list[tuple[float, float | None]]:
    an = fa.analyze(path, 0, 6, None, fps=fps)
    return [(s["t"], s["faces"][0]["box"][0] + s["faces"][0]["box"][2] / 2 if s["faces"] else None) for s in an["samples"]]


@needs_vision
def test_reframing_keeps_the_face_that_a_centre_crop_loses(moving):
    an = fa.analyze(moving / "media" / "moving.mp4", 0, 6, moving / "analysis")
    assert sum(1 for s in an["samples"] if s["faces"]) >= 0.9 * len(an["samples"])
    keys = fa.camera_keys(fa.subject_centres(an), (1080 * 9 / 16) / 1920, 1.0)

    def ir(reframe):
        it = {"id": "A", "asset_id": "mov", "timeline_in": 0, "timeline_out": 6, "source_in": 0, **({"reframe": {"keys": keys}} if reframe else {})}
        return {"ir_version": "3.0", "canvas": {"width": 540, "height": 960, "fps": 30, "sample_rate": 48000}, "tracks": [{"id": "v", "kind": "video", "items": [it]}]}
    ct.compile_timeline(moving, ir(False), Path("centre.mp4"))
    ct.compile_timeline(moving, ir(True), Path("follow.mp4"))
    centre, follow = face_x(moving / "centre.mp4"), face_x(moving / "follow.mp4")
    assert sum(x is None for _, x in centre) >= 8  # the centre crop loses her for most of the clip
    assert all(x is not None for _, x in follow)   # following, she is always in the frame
    assert all(abs(x - 0.5) < 0.1 for t, x in follow if t < 1.8 or t > 3.2)  # and centred whenever she is still


@needs_vision
def test_text_behind_the_subject_hides_exactly_where_the_person_is(moving):
    import remotion_bridge as rb
    if not rb.available()[0]:
        pytest.skip("Remotion not available")

    def ir(mode):
        tracks = [{"id": "v", "kind": "video", "items": [{"id": "A", "asset_id": "mov", "timeline_in": 0, "timeline_out": 1.5, "source_in": 0}]}]
        if mode:
            tracks.append({"id": "g", "kind": "graphic", "items": [{"id": "W", "template": "kinetic_captions", "timeline_in": 0, "timeline_out": 1.5,
                                                                    "behind_subject": mode == "behind",
                                                                    "params": {"words": [{"text": "BEHIND", "start": 0, "end": 1.4}], "position": "center", "fontScale": 3.2}}]})
        return {"ir_version": "3.0", "canvas": {"width": 960, "height": 540, "fps": 30, "sample_rate": 48000}, "style": "documentary_general", "tracks": tracks}
    for mode in (None, "front", "behind"):
        ct.compile_timeline(moving, ir(mode), Path(f"{mode}.mp4"))

    def gray(name):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "1.0", "-i", str(moving / f"{name}.mp4"), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                             capture_output=True, check=True).stdout
        return np.frombuffer(raw, np.uint8).reshape(540, 960).astype(float)
    plain, front, behind = gray("None"), gray("front"), gray("behind")
    # Where the person is, measured by the segmentation model on the plain frame (confident pixels only).
    fa.matte(moving / "None.mp4", 1.0, 1 / 30 + 0.01, 30, 960, 540, moving / "m.mp4")
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(moving / "m.mp4"), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    person = np.frombuffer(raw, np.uint8).reshape(540, 960) > 230
    text = np.abs(front - plain) > 40
    assert (text & person).sum() > 1000 and (text & ~person).sum() > 1000  # the word crosses the person and the background
    assert np.abs(behind - plain)[text & person].mean() < 8     # behind: hidden where she is
    assert np.abs(behind - front)[text & ~person].mean() < 8    # and drawn everywhere else
