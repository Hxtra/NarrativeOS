from __future__ import annotations
import hashlib, json
from pathlib import Path

def cache_key(segment: dict, provider: str, model: str, voice: str) -> str:
    payload={"text":segment.get("text",""),"direction":segment.get("voice_direction",{}),"provider":provider,"model":model,"voice":voice}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def cached_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / f"{key}.mp3"
