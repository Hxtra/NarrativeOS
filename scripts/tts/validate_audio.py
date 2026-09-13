from __future__ import annotations
import json, subprocess
from pathlib import Path

def validate_audio(path: Path) -> dict:
    result={"path":str(path),"exists":path.is_file(),"nonempty":path.is_file() and path.stat().st_size>0,"ffprobe":None,"errors":[]}
    if not result["exists"] or not result["nonempty"]:
        result["errors"].append("audio file missing or empty"); result["status"]="blocked"; return result
    try:
        proc=subprocess.run(["ffprobe","-v","error","-show_streams","-of","json",str(path)],capture_output=True,text=True,timeout=20)
        result["ffprobe"]={"returncode":proc.returncode,"streams":json.loads(proc.stdout or "{}").get("streams",[])}
        if proc.returncode or not any(s.get("codec_type")=="audio" for s in result["ffprobe"]["streams"]): result["errors"].append("no verified audio stream")
    except (FileNotFoundError, subprocess.SubprocessError, json.JSONDecodeError) as exc: result["errors"].append(str(exc))
    result["status"]="passed" if not result["errors"] else "blocked"; return result
