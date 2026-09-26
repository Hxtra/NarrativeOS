"""Generate the 8 cycling grain tiles FilmTexture.tsx reads from public/grain/.

Tiles are mid-gray (128) centred noise so `mix-blend-mode: overlay` leaves
average brightness unchanged and only adds texture. Seeded, so re-running
produces byte-identical tiles.

    python scripts/make_grain.py
"""

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

TILE = 512
COUNT = 8
OUT = Path(__file__).resolve().parent.parent / "public" / "grain"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for i in range(COUNT):
        rng = np.random.default_rng(1000 + i)
        noise = rng.normal(128.0, 38.0, (TILE, TILE))
        img = Image.fromarray(np.clip(noise, 0, 255).astype(np.uint8))
        # Slight blur so grain reads as film clumps, not single-pixel digital noise.
        img = img.filter(ImageFilter.GaussianBlur(0.6))
        img.save(OUT / f"grain{i}.png", optimize=True)
    print(f"wrote {COUNT} tiles to {OUT}")


if __name__ == "__main__":
    main()
