from __future__ import annotations
from dataclasses import dataclass
from typing import Any

@dataclass
class AudioResult:
    segment_id: str
    status: str
    output_path: str | None = None
    provider: str | None = None
    model: str | None = None
    error: str | None = None
    metadata: dict[str, Any] | None = None

class TTSProvider:
    name = "base"
    def synthesize(self, segment: dict, output_path) -> AudioResult:
        raise NotImplementedError
