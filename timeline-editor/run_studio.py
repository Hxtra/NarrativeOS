#!/usr/bin/env python3
"""Open NarrativeOS Studio on this computer.

    python timeline-editor/run_studio.py --projects "C:/path/to/projects" [--port 8420] [--no-browser]

Serves on 127.0.0.1 only (never the network). --projects is the folder that holds project folders.
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import webbrowser
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--projects", required=True, help="folder containing NarrativeOS project folders")
    ap.add_argument("--port", type=int, default=8420)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    root = Path(a.projects).expanduser().resolve()
    if not root.is_dir():
        print(f"no such folder: {root}", file=sys.stderr)
        return 1
    os.environ["NARRATIVEOS_PROJECT_ROOT"] = str(root)
    sys.path.insert(0, str(Path(__file__).resolve().parent / "server"))
    import uvicorn
    from timeline_api_server import app

    url = f"http://127.0.0.1:{a.port}/studio/"
    print(f"NarrativeOS Studio: {url}  (projects: {root})")
    if not a.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
