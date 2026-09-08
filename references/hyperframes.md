# Optional HyperFrames Backend

FFmpeg is the primary backend. HyperFrames is experimental until it produces a real output.

## Minimal test

1. Serve a known MP4 and a licensed local SVG through HTTP on `127.0.0.1`.
2. Verify `Content-Type: video/mp4`, byte-range support, and SVG bytes.
3. Load MP4 + SVG + text in the smallest valid HyperFrames composition.
4. Capture complete stdout/stderr and the output path.
5. Inspect an extracted output frame.

Test progressively:

```text
HTML only → HTML + SVG → HTML + MP4 → HTML + SVG + MP4 + text
```

`VIDEO_SOURCE_UNRENDERABLE`, missing entry files, or no output keeps the backend blocked. Browser detection or HTTP 200 alone is not a render result.
