from __future__ import annotations
import argparse, json
from pathlib import Path
from .audio_cache import cache_key, cached_path
from .openrouter import OpenRouterTTS
from .validate_audio import validate_audio
from .voice_registry import resolve

def run(project: Path, profile: str, provider_override: dict | None=None) -> dict:
    plan=json.loads((project/"narration_plan.json").read_text())
    config=resolve(profile,provider_override); cache=project/"audio"/"cache"; segments=[]; blocked=[]
    for segment in plan.get("segments",[]):
        if segment.get("type") != "NARRATION":
            segments.append({"segment_id":segment.get("segment_id"),"status":"not_applicable","type":segment.get("type")}); continue
        key=cache_key(segment,config["provider"],config["model"],config.get("voice","")); path=cached_path(cache,key)
        if path.is_file() and path.stat().st_size:
            result={"segment_id":segment["segment_id"],"status":"cached","path":str(path),"cache_key":key}
        elif config["provider"]=="openrouter":
            audio=OpenRouterTTS(config["model"],config.get("voice",""),endpoint=config.get("endpoint")); ar=audio.synthesize(segment,path)
            result={"segment_id":ar.segment_id,"status":ar.status,"path":ar.output_path,"provider":ar.provider,"model":ar.model,"error":ar.error,"cache_key":key}
        else: result={"segment_id":segment["segment_id"],"status":"blocked","error":f"unsupported provider: {config['provider']}"}
        if result["status"] in {"passed","cached"}:
            result["audio_validation"]=validate_audio(Path(result["path"]))
            if result["audio_validation"]["status"]!="passed": result["status"]="blocked"
        if result["status"]=="blocked": blocked.append(result)
        segments.append(result)
    manifest={"schema_version":"1.0","status":"blocked" if blocked else "passed","provider_config":{k:v for k,v in config.items() if k!="api_key"},"segments":segments,"blocked":blocked}
    (project/"tts_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n"); return manifest

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--project",type=Path,required=True); ap.add_argument("--profile",default="documentary_investigative"); ap.add_argument("--model"); ap.add_argument("--voice",default=""); args=ap.parse_args(); overrides={"model":args.model,"voice":args.voice} if args.model else None
    result=run(args.project,args.profile,overrides); print(json.dumps({"status":result["status"],"segments":len(result["segments"]),"blocked":len(result["blocked"])},indent=2)); return 0 if result["status"]=="passed" else 1
if __name__=="__main__": raise SystemExit(main())
