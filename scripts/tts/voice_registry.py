from __future__ import annotations

DEFAULTS={
    "documentary_investigative": {"provider":"openrouter","model":"deepgram/flux-tts:free","voice":""},
    "documentary_reflective": {"provider":"openrouter","model":"deepgram/flux-tts:free","voice":""},
    "prototype_fish": {"provider":"openrouter","model":"fish-audio/s2.1-pro-free:free","voice":""}
}

def resolve(profile: str, overrides: dict | None=None) -> dict:
    result=dict(DEFAULTS.get(profile, DEFAULTS["documentary_investigative"]))
    result.update(overrides or {})
    return result
