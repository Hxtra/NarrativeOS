"""Realistic AI voiceover with Gemini TTS, following a working creator's method (Isaac's "How I Actually Make AI Voice Sound
Real", Oct 2026; notes in skills/narrativeos-voiceover/SKILL.md):

1. what makes a voice human: changes of tone and speed, pauses on important points, emphasis on key words, a human-written script;
2. pick ONE voice and keep it (a brand); audition before choosing;
3. generate a few sentences at a time, several takes each: every generation differs slightly in tone and speed, and combining
   different takes is what removes the uncanny, same-every-time feel;
4. choose the best take per chunk, then edit: cut dead air, keep intentional pauses on the important beats;
5. change speed with pitch kept; then EQ: high-pass, cut boxy and echoey frequencies.

Commands:
  python scripts/voiceover.py audition --out DIR [--voices A,B,...] [--line "..."]
  python scripts/voiceover.py takes SCRIPT.txt --out DIR --voice NAME [--n 3] [--direction "..."]
  python scripts/voiceover.py pick --out DIR [--wpm 165]
  python scripts/voiceover.py assemble --out DIR [--gap 0.28] [--pause 0.7] [--wpm 165]

SCRIPT.txt: one chunk per line (one or two sentences). Mark a beat with "||" at the end of a line for a longer pause after it.
The script stays human-written. The machine cannot hear: picks are made from measurements (speech-to-text accuracy, pace, pitch
movement, clean edges) and must be confirmed by a person listening. Gemini key: ~/.narrativeos/gemini.key (never printed).
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import subprocess
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

import numpy as np

MODEL = "gemini-3.8-flash-tts"
FALLBACK = ["gemini-3.1-flash-tts-preview", "gemini-2.5-flash-preview-tts", "gemini-3.8-flash-lite-tts"]   # free-tier quota is per model
SR = 24000
KEY = Path.home() / ".narrativeos" / "gemini.key"
# Gemini TTS reads a long direction ALOUD (MEASURED Oct 18: a 22-word line came out 27 s long with the whole brief spoken).
# The documented form is a SHORT style cue ending in a colon, then the text.
DIRECTION = "Narrate warmly, with quiet curiosity, like telling a friend a true story:"
VOICES = ["Algieba", "Charon", "Iapetus", "Sadaltager", "Orus", "Gacrux", "Achird", "Schedar"]
# Cartesia (paid credits, about one credit per character): the owner's chosen AVEN voice, "Ronald - Thinker" (public voice).
# No style cue is sent, so nothing is read aloud before the script. Raw PCM at the same 24 kHz as Gemini, so the rest of the
# pipeline is unchanged. Every Cartesia run states its character cost first and needs --spend to go ahead.
CARTESIA_KEY = Path.home() / ".narrativeos" / "cartesia.key"
CARTESIA_MODEL = "sonic-3"
CARTESIA_VOICE = "5ee9feff-1265-424a-9d7f-8e4d431a12c7"


def tts_cartesia(text: str, voice: str = CARTESIA_VOICE, model: str = CARTESIA_MODEL, retries: int = 4) -> np.ndarray:
    body = {"model_id": model, "transcript": text, "voice": {"mode": "id", "id": voice}, "language": "en",
            "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": SR}}
    headers = {"X-API-Key": CARTESIA_KEY.read_text().strip(), "Cartesia-Version": "2025-04-16", "Content-Type": "application/json"}
    for a in range(retries):
        req = urllib.request.Request("https://api.cartesia.ai/tts/bytes", data=json.dumps(body).encode(), headers=headers)
        try:
            return np.frombuffer(urllib.request.urlopen(req, timeout=120).read(), dtype="<i2").astype(np.float32) / 32768.0
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:200]
            if e.code in (429, 500, 503) and a < retries - 1:
                time.sleep(8 * (a + 1)); continue
            raise RuntimeError(f"Cartesia {e.code}: {msg}") from None
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            if a < retries - 1:
                time.sleep(5 * (a + 1)); continue
            raise RuntimeError(f"Cartesia network error: {e}") from None
    raise RuntimeError("Cartesia TTS failed")


def speak(text: str, voice: str, provider: str, direction: str = DIRECTION) -> np.ndarray:
    return tts_cartesia(text, voice) if provider == "cartesia" else tts(text, voice, direction)


def credit_gate(provider: str, texts: list[str], spend: bool) -> None:
    """Cartesia bills per character: say what a run costs and stop unless --spend was given."""
    if provider != "cartesia" or not texts:
        return
    chars = sum(len(t) for t in texts)
    print(f"Cartesia: {len(texts)} generations, about {chars} credits (characters).", flush=True)
    if not spend:
        raise SystemExit("Not generated. Re-run with --spend to use these credits.")


def tts(text: str, voice: str, direction: str = DIRECTION, model: str = MODEL, retries: int = 6) -> np.ndarray:
    body = {"contents": [{"parts": [{"text": f"{direction} {text}"}]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}
    key = KEY.read_text().strip()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    for a in range(retries):
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "x-goog-api-key": key})
        try:
            r = json.load(urllib.request.urlopen(req, timeout=120))
            data = r["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
            return np.frombuffer(base64.b64decode(data), dtype="<i2").astype(np.float32) / 32768.0
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:200]
            if e.code == 429 and model != FALLBACK[-1]:   # out of quota: same voice on the next model
                nxt = FALLBACK[0] if model not in FALLBACK else FALLBACK[FALLBACK.index(model) + 1]
                print(f"  quota on {model}, trying {nxt}", flush=True)
                return tts(text, voice, direction, nxt, retries)
            if e.code in (429, 500, 503) and a < retries - 1:
                time.sleep(8 * (a + 1)); continue
            raise RuntimeError(f"TTS {e.code}: {msg}") from None
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:   # unstable network: retry
            if a < retries - 1:
                time.sleep(5 * (a + 1)); continue
            raise RuntimeError(f"TTS network error: {e}") from None
    raise RuntimeError("TTS failed")


def write_wav(path: Path, y: np.ndarray, sr: int = SR) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((np.clip(y, -1, 1) * 32767).astype("<i2").tobytes())


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0


def trim(y: np.ndarray, thr_db: float = -45, pad: float = 0.04) -> np.ndarray:
    hop = int(0.01 * SR)
    lv = np.array([20 * np.log10(np.sqrt(np.mean(y[i:i + hop] ** 2)) + 1e-9) for i in range(0, max(len(y) - hop, 1), hop)])
    on = np.where(lv > thr_db)[0]
    if not len(on):
        return y
    a, b = max(0, on[0] * hop - int(pad * SR)), min(len(y), (on[-1] + 1) * hop + int(pad * SR))
    return y[a:b]


ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
ORD = {"one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth", "nine": "ninth", "twelve": "twelfth"}


def _n2w(n: int) -> str:
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ("" if n % 10 == 0 else " " + ONES[n % 10])
    if 1100 <= n <= 1999 and n % 100 == 0:
        return _n2w(n // 100) + " hundred"
    if 1000 <= n <= 2099:                                       # years: 1823 -> eighteen twenty three
        return _n2w(n // 100) + " " + (("oh " + ONES[n % 100]) if n % 100 < 10 and n % 100 else _n2w(n % 100) if n % 100 else "hundred")
    return " ".join(ONES[int(d)] for d in str(n))


def words_norm(s: str) -> list[str]:
    """Lower-case words with digits spelled out, so "97%" matches "ninety-seven percent" (the script spells numbers out)."""
    import re
    s = s.lower().replace("%", " percent").replace("-", " ")
    def rep(m):
        n, suf = int(m.group(1)), m.group(2) or ""
        w = _n2w(n)
        if suf == "s":
            w += "s"
        elif suf in ("th", "st", "nd", "rd"):
            last = w.split()[-1]; w = " ".join(w.split()[:-1] + [ORD.get(last, last.rstrip("y") + "ieth" if last.endswith("y") else last + "th")])
        return " " + w + " "
    s = re.sub(r"(\d+)(s|th|st|nd|rd)?", rep, s)
    s = re.sub(r"(\d+)(s|th|st|nd|rd)?(?![a-z])", rep, s)
    return re.sub(r"[^a-z ]", " ", s).split()


def to16k(y: np.ndarray) -> np.ndarray:
    """faster-whisper expects 16 kHz; TTS returns 24 kHz. Passing 24 kHz made every timestamp 1.5x too late and
    hurt recognition (MEASURED Oct 18: words at 19 s in a 14 s take)."""
    import soxr
    return soxr.resample(y, SR, 16000).astype(np.float32)


def spoken_start(y: np.ndarray, expected: str, asr, cue: str = DIRECTION) -> float:
    """Where the scripted text starts in the take, in seconds. Some models speak the style cue first (MEASURED Oct 18:
    every fallback-model take from line 6 on). The cue's last word ("story") marks its end; cut just after it.
    Matching the script's first words instead picked common words ("the", "a") too late (MEASURED)."""
    segs, _ = asr.transcribe(to16k(y), language="en", vad_filter=False, word_timestamps=True)
    flat = [(w.start, w.end, x) for s in segs for w in s.words for x in words_norm(w.word)]
    last = words_norm(cue)[-1]
    n_exp = len(words_norm(expected))
    for i, (st, en, x) in enumerate(flat):
        if x == last and len(flat) - (i + 1) >= 0.6 * n_exp and i < len(flat) - 1:
            return max(0.0, (en + flat[i + 1][0]) / 2)        # the gap between the cue and the script
    return 0.0


def measure(y: np.ndarray, expected: str, asr=None, cue: str | None = DIRECTION) -> dict:
    """Pace, pitch movement (semitone spread of voiced frames), clean edges, and speech-to-text agreement.
    cue=None for providers that get no style cue (Cartesia): nothing to cut from the start."""
    import librosa
    start = 0.0
    if asr is not None and cue:
        start = spoken_start(y, expected, asr, cue)
        y = y[int(start * SR):]
    yt = trim(y); dur = len(yt) / SR
    f0, voiced, _ = librosa.pyin(yt, fmin=60, fmax=400, sr=SR, frame_length=1024)
    st = 12 * np.log2(f0[voiced] / 100.0) if voiced.any() else np.array([0.0])
    words = len(words_norm(expected))
    out = {"start_sec": round(start, 3), "seconds": round(dur, 2), "wpm": round(60 * words / max(dur, 0.1)),
           "pitch_spread_st": round(float(np.percentile(st, 90) - np.percentile(st, 10)), 2),
           "median_pitch_hz": round(float(100 * 2 ** (np.median(st) / 12)), 1), "peak": round(float(np.abs(y).max()), 3)}
    if asr is not None:
        segs, _ = asr.transcribe(to16k(yt), language="en", vad_filter=False)
        heard = " ".join(s.text for s in segs)
        a, b = words_norm(expected), words_norm(heard)
        common = sum(min(a.count(w), b.count(w)) for w in set(a))
        out["asr_match"] = round(common / max(len(a), 1), 2); out["heard"] = heard.strip()
        out["extra_words"] = max(0, len(b) - len(a))
    return out


def cmd_audition(a):
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    from faster_whisper import WhisperModel
    asr = WhisperModel("base", device="cpu", compute_type="int8")
    res = {}
    voices = a.voices.split(",") if a.voices else ([CARTESIA_VOICE] if a.provider == "cartesia" else VOICES)
    credit_gate(a.provider, [a.line] * len(voices), a.spend)
    for v in voices:
        y = speak(a.line, v, a.provider); write_wav(out / f"audition_{v}.wav", y)
        res[v] = measure(y, a.line, asr, None if a.provider == "cartesia" else DIRECTION); print(v, res[v], flush=True)
    (out / "audition.json").write_text(json.dumps(res, indent=1), encoding="utf-8")


def chunks(script: Path) -> list[dict]:
    """A '||' inside a line splits it into two chunks with a beat between them. Text sent to TTS never contains '|':
    Cartesia read a mid-line '||' aloud as "vertical bar, vertical bar" (MEASURED Oct 19)."""
    out = []
    for line in script.read_text(encoding="utf-8").splitlines():
        parts = [p.strip() for p in line.split("||")]
        for k, p in enumerate(parts):
            if p:
                out.append({"text": p.replace("|", " ").strip(), "beat": k < len(parts) - 1})
    return out


def respell(text: str, out: Path) -> str:
    """Names the voice mispronounces, from OUT/pronounce.json {"Syene": "Sigh-ee-nee"}: only the text SENT to the voice
    changes; the script and the speech-to-text check keep the real spelling."""
    f = out / "pronounce.json"
    for word, said in (json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}).items():
        text = text.replace(word, said)
    return text


def cmd_takes(a):
    out = Path(a.out); (out / "takes").mkdir(parents=True, exist_ok=True)
    cs = chunks(Path(a.script))
    voice = a.voice or (CARTESIA_VOICE if a.provider == "cartesia" else None)
    if not voice:
        raise SystemExit("--voice is required for Gemini")
    meta = {"voice": voice, "provider": a.provider, "chunks": cs}
    (out / "chunks.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    todo = [(i, k) for i in range(len(cs)) for k in range(a.n) if not (out / "takes" / f"c{i:02d}_t{k}.wav").exists()]
    said = [respell(cs[i]["text"], out) for i, _ in todo]
    credit_gate(a.provider, said, a.spend)
    for (i, k), text in zip(todo, said):
        write_wav(out / "takes" / f"c{i:02d}_t{k}.wav", speak(text, voice, a.provider, a.direction or DIRECTION))
        print("take", i, k, flush=True)


def cmd_pick(a):
    out = Path(a.out); meta = json.loads((out / "chunks.json").read_text(encoding="utf-8"))
    from faster_whisper import WhisperModel
    asr = WhisperModel("base", device="cpu", compute_type="int8")
    picks = []
    for i, c in enumerate(meta["chunks"]):
        scored = []
        for f in sorted((out / "takes").glob(f"c{i:02d}_t*.wav")):
            m = measure(read_wav(f), c["text"], asr, None if meta.get("provider") == "cartesia" else DIRECTION)
            # must be heard correctly; then prefer lively pitch and a pace near the target, never clipped
            score = (m.get("asr_match", 0) >= 0.85 and m.get("extra_words", 0) <= 2) * 10 + min(m["pitch_spread_st"], 8) - abs(m["wpm"] - a.wpm) / 15 - (m["peak"] > 0.99) * 5
            scored.append({"file": f.name, "score": round(score, 2), **m})
        if not scored:
            print(i, "no takes yet", flush=True); picks.append({"chunk": i, "text": c["text"], "beat": c["beat"], "pick": None, "takes": []}); continue
        scored.sort(key=lambda s: -s["score"])
        picks.append({"chunk": i, "text": c["text"], "beat": c["beat"], "pick": scored[0]["file"], "takes": scored})
        print(i, scored[0]["file"], scored[0]["score"], flush=True)
    (out / "picks.json").write_text(json.dumps(picks, indent=1), encoding="utf-8")


def cmd_assemble(a):
    """Concatenate the picked takes with natural gaps (longer after '||' beats), match the target pace with pitch kept,
    then the EQ chain: high-pass, cut boxiness and echo, gentle presence, compression, loudness."""
    out = Path(a.out); picks = json.loads((out / "picks.json").read_text(encoding="utf-8"))
    parts, cues, t = [], [], 0.0
    have = [p for p in picks if p["pick"]]
    sec_per_word = (sum(next(t["seconds"] for t in p["takes"] if t["file"] == p["pick"]) for p in have)) / max(1, sum(len(p["text"].split()) for p in have))
    for p in picks:
        if not p["pick"]:                                   # not generated yet: placeholder silence, marked missing
            y = np.zeros(int(len(p["text"].split()) * sec_per_word * SR), np.float32)
        else:
            y0 = read_wav(out / "takes" / p["pick"]); st = next((t.get("start_sec", 0) for t in p["takes"] if t["file"] == p["pick"]), 0)
            y = trim(y0[int(st * SR):])
        cues.append({"chunk": p["chunk"], "t0": round(t, 3), "t1": round(t + len(y) / SR, 3), "text": p["text"], "missing": not p["pick"]})
        parts.append(y); t += len(y) / SR
        gap = a.pause if p["beat"] else a.gap
        parts.append(np.zeros(int(gap * SR), np.float32)); t += gap
    y = np.concatenate(parts)
    raw = out / "vo_raw.wav"; write_wav(raw, y)
    words = sum(len(p["text"].replace("...", " ").split()) for p in picks if p["pick"])
    speech = sum(c["t1"] - c["t0"] for c in cues if not c["missing"])
    tempo = a.tempo or (1.0 if not a.wpm else max(0.9, min(1.12, a.wpm / (60 * words / speech))))
    chain = (f"atempo={tempo:.4f},highpass=f=80,equalizer=f=300:t=q:w=1.2:g=-2.5,equalizer=f=4500:t=q:w=1.5:g=2,"
             "acompressor=threshold=-20dB:ratio=3:attack=8:release=120,loudnorm=I=-16:TP=-1.5:LRA=7")
    final = out / "vo.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-af", chain, "-ar", "48000", str(final)], check=True)
    for c in cues:
        c["t0"] = round(c["t0"] / tempo, 3); c["t1"] = round(c["t1"] / tempo, 3)
    (out / "cues.json").write_text(json.dumps({"tempo": round(tempo, 4), "cues": cues}, indent=1), encoding="utf-8")
    print(f"wrote {final}  tempo x{tempo:.3f}  {len(y) / SR / tempo:.1f} s")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = ap.add_subparsers(dest="cmd", required=True)
    p = s.add_parser("audition"); p.add_argument("--out", required=True); p.add_argument("--voices")
    p.add_argument("--line", default="In the early eighteen hundreds, every lighthouse had the same problem. It burned all night... and most of that light went nowhere.")
    p.add_argument("--provider", choices=["gemini", "cartesia"], default="gemini"); p.add_argument("--spend", action="store_true")
    p = s.add_parser("takes"); p.add_argument("script"); p.add_argument("--out", required=True); p.add_argument("--voice")
    p.add_argument("--n", type=int, default=3); p.add_argument("--direction")
    p.add_argument("--provider", choices=["gemini", "cartesia"], default="gemini"); p.add_argument("--spend", action="store_true")
    p = s.add_parser("pick"); p.add_argument("--out", required=True); p.add_argument("--wpm", type=float, default=165)
    p = s.add_parser("assemble"); p.add_argument("--out", required=True); p.add_argument("--gap", type=float, default=0.28)
    p.add_argument("--pause", type=float, default=0.7); p.add_argument("--wpm", type=float, default=165)
    p.add_argument("--tempo", type=float, help="fixed speed (e.g. 0.92 = 8%% slower, pitch kept); overrides --wpm")
    a = ap.parse_args()
    {"audition": cmd_audition, "takes": cmd_takes, "pick": cmd_pick, "assemble": cmd_assemble}[a.cmd](a)


if __name__ == "__main__":
    main()
