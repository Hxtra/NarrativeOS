from __future__ import annotations
import base64, json, os, urllib.error, urllib.request
from pathlib import Path
from .base import AudioResult, TTSProvider

class OpenRouterTTS(TTSProvider):
    name="openrouter"
    def __init__(self, model: str, voice: str = "", api_key: str | None = None, endpoint: str | None = None):
        self.model=model; self.voice=voice; self.api_key=api_key or os.getenv("OPENROUTER_API_KEY"); self.endpoint=endpoint or os.getenv("OPENROUTER_TTS_ENDPOINT", "https://openrouter.ai/api/v1/audio/speech")
    def synthesize(self, segment: dict, output_path: Path) -> AudioResult:
        sid=segment.get("segment_id","")
        if not self.api_key: return AudioResult(sid,"blocked",provider=self.name,model=self.model,error="OPENROUTER_API_KEY is not configured")
        text=str(segment.get("text","")).strip()
        if not text: return AudioResult(sid,"blocked",provider=self.name,model=self.model,error="segment has no text")
        direction=segment.get("voice_direction",{})
        payload={"model":self.model,"input":text,"voice":self.voice,"response_format":"mp3","speed":direction.get("pace",1.0)}
        request=urllib.request.Request(self.endpoint,data=json.dumps(payload).encode(),headers={"Authorization":f"Bearer {self.api_key}","Content-Type":"application/json","HTTP-Referer":"https://github.com/Hxtra/NarrativeOS","X-Title":"NarrativeOS"},method="POST")
        try:
            with urllib.request.urlopen(request,timeout=120) as response:
                body=response.read(); content_type=response.headers.get("Content-Type","")
            output_path.parent.mkdir(parents=True,exist_ok=True)
            if "json" in content_type or body[:1] in (b"{",b"["):
                data=json.loads(body); encoded=data.get("audio") or data.get("data")
                if not encoded: return AudioResult(sid,"blocked",provider=self.name,model=self.model,error="provider returned JSON without audio")
                body=base64.b64decode(encoded)
            if not body: return AudioResult(sid,"blocked",provider=self.name,model=self.model,error="provider returned empty audio")
            output_path.write_bytes(body)
            return AudioResult(sid,"passed",str(output_path),self.name,self.model,metadata={"content_type":content_type})
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            return AudioResult(sid,"blocked",provider=self.name,model=self.model,error=str(exc))
