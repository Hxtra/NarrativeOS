"""Expose the local VFX library to Remotion as public/vfx without copying clips into the repo.

    python scripts/link_vfx_library.py            # uses $NARRATIVEOS_VFX_LIBRARY or ~/NarrativeOS-VFX-Library
    python scripts/link_vfx_library.py <library>
    python scripts/link_vfx_library.py --unlink

On Windows this makes a directory junction (no admin rights needed); elsewhere a symlink.
public/vfx is gitignored. With no link, overlay recipes fall back to procedural layers.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

LINK = Path(__file__).resolve().parent.parent / "public" / "vfx"


def is_link(p: Path) -> bool:
    return p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())


def unlink() -> None:
    if is_link(LINK):
        os.unlink(LINK) if LINK.is_symlink() else os.rmdir(LINK)
        print(f"removed {LINK}")


def main() -> int:
    if "--unlink" in sys.argv:
        unlink()
        return 0
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    target = Path(arg or os.environ.get("NARRATIVEOS_VFX_LIBRARY") or Path.home() / "NarrativeOS-VFX-Library").expanduser().resolve()
    if not (target / "vfx_catalog.json").is_file():
        print(f"{target} has no vfx_catalog.json; run vfx-library/tools/vfx_ingest.py first", file=sys.stderr)
        return 1
    if LINK.exists() and not is_link(LINK):
        print(f"{LINK} is a real directory; refusing to replace it", file=sys.stderr)
        return 1
    unlink()
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(target), str(LINK))
    else:
        LINK.symlink_to(target, target_is_directory=True)
    print(f"linked {LINK} -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
