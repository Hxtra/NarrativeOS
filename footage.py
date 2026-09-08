#!/usr/bin/env python3
"""
footage.py — Pexels / Pixabay video download with retry-safe streaming.
Part of the Flannan Isles video pipeline.

Fixed bug: the old code used aiohttp's iter_chunked() which can raise
ClientPayloadError when the connection drops mid-stream. New code uses
bounded read() with retry and validates content-length where available.
"""
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

# ---- FFmpeg/FFprobe paths (shared with rest of pipeline) ----
FFMPEG = r"C:\Users\openclaw\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build\bin\ffmpeg.exe"
FFPROBE = r"C:\Users\openclaw\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build\bin\ffprobe.exe"

PROJECT_ROOT = Path(r"C:\Users\openclaw\Desktop\flannan_isles")
DL_DIR = PROJECT_ROOT / "footage"
DL_DIR.mkdir(parents=True, exist_ok=True)

# Asset manifest: tracks every downloaded file with provenance
MANIFEST_PATH = PROJECT_ROOT / "assets.json"


def probe_video(path: Path) -> dict:
    """Return duration, dimensions, fps, codec via ffprobe."""
    import subprocess, json
    r = subprocess.run(
        [FFPROBE, "-v", "error",
         "-show_entries", "format=duration:stream=width,height,r_frame_rate,codec_name,codec_type",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=30
    )
    if r.returncode != 0:
        return {}
    data = json.loads(r.stdout)
    fmt = data.get("format", {})
    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    return {
        "duration_sec": float(fmt.get("duration", 0)),
        "width": int(video_stream.get("width", 0)),
        "height": int(video_stream.get("height", 0)),
        "fps": video_stream.get("r_frame_rate", "0/1"),
        "codec": video_stream.get("codec_name", ""),
    }


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {"assets": [], "version": "1.0"}


def save_manifest(manifest: dict):
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))


# ---- Pexels API ----
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")


def pick_pexels_file(video_json: dict) -> dict | None:
    """Pick smallest landscape file >= 720p from a Pexels video object."""
    files = video_json.get("video_files", [])
    candidates = []
    for f in files:
        w = f.get("width", 0)
        h = f.get("height", 0)
        link = f.get("link", "")
        if not link or not link.startswith("http"):
            continue
        if w < 1280 or h < 720:
            continue
        if w <= h:  # skip vertical
            continue
        if not link.lower().endswith(".mp4"):
            continue
        candidates.append((w * h, f))
    if not candidates:
        for f in files:
            link = f.get("link", "")
            if link and link.startswith("http") and link.lower().endswith(".mp4"):
                candidates.append((f.get("width", 0) * f.get("height", 0), f))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


async def download_pexels_video(session, url: str, dest: Path, timeout: int = 120) -> bool:
    """
    Download a file with retry-safe streaming.
    FIX: uses bounded read() instead of iter_chunked() to avoid
    ClientPayloadError on dropped connections.
    """
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            async with session.get(url, timeout=timeout) as resp:
                if resp.status != 200:
                    print(f"    [FAIL] HTTP {resp.status} (attempt {attempt})")
                    if resp.status == 429:
                        await asyncio.sleep(5 * attempt)
                        continue
                    return False

                total_expected = int(resp.headers.get("Content-Length", 0) or 0)
                bytes_downloaded = 0

                with open(dest, "wb") as f:
                    while True:
                        chunk = await resp.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                        bytes_downloaded += len(chunk)

                        # Progress
                        if total_expected:
                            pct = bytes_downloaded * 100 // total_expected
                            print(f"\r      [{pct:3d}% {bytes_downloaded//(1024*1024)}MB]", end="", flush=True)

                print()  # newline after progress

                # Validate: if we expected a length, check we got it all
                if total_expected and bytes_downloaded < total_expected:
                    print(f"    [WARN] Expected {total_expected}B, got {bytes_downloaded}B — retrying")
                    dest.unlink(missing_ok=True)
                    if attempt < max_retries:
                        await asyncio.sleep(2 * attempt)
                        continue
                    return False

                if bytes_downloaded < 1000:
                    print(f"    [WARN] File too small ({bytes_downloaded}B) — retrying")
                    dest.unlink(missing_ok=True)
                    if attempt < max_retries:
                        await asyncio.sleep(2 * attempt)
                        continue
                    return False

                return True

        except asyncio.TimeoutError:
            print(f"    [TIMEOUT] (attempt {attempt})")
            if attempt < max_retries:
                await asyncio.sleep(3 * attempt)
                continue
            return False
        except Exception as e:
            print(f"    [ERR] {type(e).__name__}: {e} (attempt {attempt})")
            if attempt < max_retries:
                await asyncio.sleep(2 * attempt)
                continue
            return False

    return False


async def search_pexels(query: str, per_page: int = 5) -> list[dict]:
    """Search Pexels videos, return list of video objects."""
    import aiohttp
    if not PEXELS_API_KEY:
        print(f"  [SKIP] No PEXELS_API_KEY — skipping '{query}'")
        return []

    url = (f"https://api.pexels.com/videos/search?"
           f"query={query}&per_page={per_page}&size=large&orientation=landscape")
    headers = {"Authorization": PEXELS_API_KEY}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, timeout=30) as resp:
            if resp.status != 200:
                print(f"  [SKIP] Pexels '{query}': HTTP {resp.status}")
                return []
            data = await resp.json()

        results = []
        for video in data.get("videos", []):
            chosen = pick_pexels_file(video)
            if not chosen:
                continue
            results.append({
                "id": video["id"],
                "query": query,
                "duration": video.get("duration", 0),
                "width": chosen.get("width", 0),
                "height": chosen.get("height", 0),
                "fps": chosen.get("fps", 0),
                "link": chosen["link"],
                "popularity": video.get("popularity", 0),
            })
        return results


async def download_pexels(query: str, per_page: int = 5) -> list[dict]:
    """Search + download Pexels videos for a query. Returns list of downloaded asset records."""
    import aiohttp
    manifest = load_manifest()
    existing_urls = {a["download_url"] for a in manifest["assets"]}

    print(f"\n  Pexels search: '{query}'")
    videos = await search_pexels(query, per_page)
    if not videos:
        return []

    print(f"    Found {len(videos)} candidates")

    downloaded = []
    async with aiohttp.ClientSession() as session:
        for i, vid in enumerate(videos):
            link = vid["link"]
            name = link.split("/")[-1]
            if not name.lower().endswith(".mp4"):
                name = f"pexels_{vid['id']}.mp4"
            dest = DL_DIR / name

            if dest.exists() and dest.stat().st_size > 1000:
                print(f"    [{i+1}/{len(videos)}] [SKIP] already have {name} "
                      f"({dest.stat().st_size // (1024*1024)}MB)")
                downloaded.append(vid)
                continue

            print(f"    [{i+1}/{len(videos)}] downloading {name} "
                  f"({vid['width']}x{vid['height']}, {vid['duration']}s)...")
            success = await download_pexels_video(session, link, dest)
            if success:
                probe = probe_video(dest)
                sha = sha256_file(dest)
                sz = dest.stat().st_size
                print(f"      -> {name}: {sz//(1024*1024)}MB, "
                      f"{probe.get('width','')}x{probe.get('height','')}, "
                      f"SHA256:{sha[:12]}...")
                vid["local_path"] = str(dest)
                vid["download_url"] = link
                vid["sha256"] = sha
                vid["file_size"] = sz
                vid["probe"] = probe
                downloaded.append(vid)

                # Record in manifest
                manifest["assets"].append({
                    "provider": "pexels",
                    "asset_id": vid["id"],
                    "query": vid["query"],
                    "local_path": str(dest),
                    "download_url": link,
                    "sha256": sha,
                    "file_size": sz,
                    "probe": probe,
                    "license": "Pexels License",
                    "license_url": "https://www.pexels.com/license/",
                    "retrieved_at": asyncio.get_event_loop().time() if hasattr(asyncio.get_event_loop(), 'time') else "unknown",
                    "rights_state": "approved",
                })
                save_manifest(manifest)

                # Pace downloads to avoid hammering
                await asyncio.sleep(0.5)
            else:
                print(f"    [{i+1}/{len(videos)}] FAILED: {name}")

    return downloaded


# ---- Pixabay API (fallback) ----
PIXABAY_API_KEY = os.environ.get("PIXABAY_API_KEY", "")


async def search_pixabay(query: str, per_page: int = 5) -> list[dict]:
    """Search Pixabay videos. Returns list of video objects."""
    import aiohttp
    if not PIXABAY_API_KEY:
        print(f"  [SKIP] No PIXABAY_API_KEY — skipping '{query}'")
        return []

    url = (f"https://pixabay.com/api/videos/?key={PIXABAY_API_KEY}"
           f"&q={query}&per_page={per_page}&order=latest")
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=30) as resp:
            if resp.status != 200:
                print(f"  [SKIP] Pixabay '{query}': HTTP {resp.status}")
                return []
            data = await resp.json()

        results = []
        for vid in data.get("hits", []):
            vid_obj = vid.get("videos", {})
            # Pixabay returns different sizes; pick the largest landscape
            chosen = None
            for size_name in ["large", "medium", "small"]:
                candidate = vid_obj.get(size_name)
                if candidate and candidate.get("width", 0) >= 1280:
                    chosen = candidate
                    break
            if not chosen:
                for size_name in ["large", "medium", "small"]:
                    candidate = vid_obj.get(size_name)
                    if candidate:
                        chosen = candidate
                        break
            if not chosen:
                continue
            results.append({
                "id": vid["id"],
                "query": query,
                "duration": vid.get("duration", 0),
                "width": chosen.get("width", 0),
                "height": chosen.get("height", 0),
                "link": chosen.get("link", ""),
            })
        return results


# ---- Main download orchestration ----
async def download_all(queries: list[str], per_page: int = 5) -> list[dict]:
    """Download footage for all queries. Returns all downloaded asset records."""
    all_downloaded = []

    for query in queries:
        # Try Pexels first
        pexels_results = await download_pexels(query, per_page)
        all_downloaded.extend(pexels_results)

        # If Pexels returned nothing, try Pixabay
        if not pexels_results:
            print(f"  Pexels returned nothing for '{query}' — trying Pixabay...")
            pixabay_results = await search_pixabay(query, per_page)
            print(f"    Pixabay found {len(pixabay_results)} candidates")

    manifest = load_manifest()
    total_mb = sum(a.get("file_size", 0) for a in manifest["assets"]) / (1024 * 1024)
    print(f"\n  Total footage: {len(manifest['assets'])} files, {total_mb:.2f} MB")
    return all_downloaded


if __name__ == "__main__":
    import asyncio
    queries = [
        "lighthouse storm night sea",
        "rocky island atlantic waves",
        "foggy coast cliffs",
        "lighthouse beam dark",
        "storm waves crashing rocks",
        "empty room lamp light",
        "old clock face",
        "ocean fog mist",
    ]
    asyncio.run(download_all(queries))
