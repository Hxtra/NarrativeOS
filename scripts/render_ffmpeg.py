#!/usr/bin/env python3
"""Render an approved timeline with FFmpeg, optional motion, and real audio."""
from __future__ import annotations
import argparse, json, shutil, subprocess, tempfile
from pathlib import Path

def load(p): return json.loads(p.read_text(encoding='utf-8'))
def run(cmd): return subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--project',type=Path,required=True); ap.add_argument('--timeline',default='timeline.json'); ap.add_argument('--output',default='renders/preview.mp4'); ap.add_argument('--audio',default=''); args=ap.parse_args()
    ff=shutil.which('ffmpeg'); probe=shutil.which('ffprobe')
    if not ff or not probe: raise SystemExit('ffmpeg and ffprobe are required')
    p=args.project; tl=load(p/args.timeline); assets=load(p/'assets.json'); registry={a.get('asset_id'):a for a in assets.get('assets',[])}; shots=tl.get('shots',[])
    if not shots: raise SystemExit('timeline has no shots')
    size=tl.get('output',{}); w=int(size.get('width',1280)); h=int(size.get('height',720)); fps=int(size.get('fps',24)); out=p/args.output; out.parent.mkdir(parents=True,exist_ok=True)
    audio=Path(args.audio) if args.audio else None; audio=(p/audio if audio and not audio.is_absolute() else audio)
    with tempfile.TemporaryDirectory(prefix='hermes_render_',dir=p) as td:
        parts=[]
        for i,s in enumerate(shots):
            if s.get('status')!='approved': raise SystemExit(f"shot {s.get('shot_id')} is not approved")
            asset=registry.get(s.get('asset_id'))
            if not asset or asset.get('status')!='approved': raise SystemExit(f"asset not approved: {s.get('asset_id')}")
            src=Path(asset.get('local_path','')); src=src if src.is_absolute() else p/src
            if not src.is_file(): raise SystemExit(f'missing asset: {src}')
            dur=float(s['end'])-float(s['start']); source=float(s.get('source_start',0)); motion=s.get('motion','static'); part=Path(td)/f'part_{i:04d}.mp4'; ext=src.suffix.lower(); image=ext in {'.png','.jpg','.jpeg','.webp'}
            base=f'scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1'
            if image and motion in {'slow_zoom_in','slow_zoom_out'}:
                zoom='zoom+0.0015' if motion=='slow_zoom_in' else 'zoom-0.0015'
                vf=f'zoompan=z={zoom}:x=iw/2-iw/zoom/2:y=ih/2-ih/zoom/2:d={max(1,int(dur*fps))}:s={w}x{h}:fps={fps},format=yuv420p'
                cmd=[ff,'-y','-loop','1','-i',str(src),'-t',f'{dur:.3f}','-vf',vf,'-an','-c:v','libx264','-pix_fmt','yuv420p','-preset','veryfast','-movflags','+faststart',str(part)]
            else:
                vf=base
                cmd=[ff,'-y']
                if image: cmd += ['-loop','1','-i',str(src),'-t',f'{dur:.3f}']
                else: cmd += ['-ss',str(source),'-i',str(src),'-t',f'{dur:.3f}']
                cmd += ['-vf',vf,'-r',str(fps),'-an','-c:v','libx264','-pix_fmt','yuv420p','-preset','veryfast','-movflags','+faststart',str(part)]
            r=run(cmd)
            if r.returncode: raise SystemExit(r.stderr[-3000:])
            parts.append(part)
        concat=Path(td)/'concat.txt'; concat.write_text(''.join(f"file '{x.as_posix()}'\n" for x in parts),encoding='utf-8'); video=Path(td)/'video.mp4'; r=run([ff,'-y','-f','concat','-safe','0','-i',str(concat),'-c','copy',str(video)])
        if r.returncode: raise SystemExit(r.stderr[-3000:])
        if audio:
            if not audio.is_file(): raise SystemExit(f'missing audio: {audio}')
            r=run([ff,'-y','-i',str(video),'-i',str(audio),'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-shortest','-movflags','+faststart',str(out)])
        else: r=run([ff,'-y','-i',str(video),'-c','copy',str(out)])
        if r.returncode: raise SystemExit(r.stderr[-3000:])
    probe_r=run([probe,'-v','error','-show_streams','-show_format','-of','json',str(out)])
    if probe_r.returncode: raise SystemExit(probe_r.stderr)
    data=json.loads(probe_r.stdout); manifest={'status':'passed','output_path':str(out.relative_to(p)),'size_bytes':out.stat().st_size,'has_audio':any(x.get('codec_type')=='audio' for x in data.get('streams',[])),'motion_presets_used':sorted({s.get('motion','static') for s in shots}),'ffprobe':data}
    (p/'renders/render_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8'); print(json.dumps(manifest,indent=2))
if __name__=='__main__': main()
