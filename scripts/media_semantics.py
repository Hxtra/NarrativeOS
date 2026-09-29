"""What a piece of media is, and whether it can stand as evidence for a factual claim.

A generated image never becomes evidence, whatever it depicts. Evidence has to
be real recorded media with provenance and verified rights.
"""
from __future__ import annotations

# Visual classes the owner specified, plus explicit classes for generated audio.
MEDIA_CLASSES = {
    "EVIDENCE",                  # the record itself: document, scan, recording that proves the claim
    "ARCHIVAL",                  # authentic historical footage/photos from an archive
    "DOCUMENTARY_PHOTO",         # real photograph of the actual subject/event
    "STOCK",                     # real but generic footage/photos: illustrates, does not prove
    "GENERATED_RECONSTRUCTION",  # AI depiction of a real event/place: never evidence
    "GENERATED_CONCEPT",         # AI visualisation of an idea that has no photograph
    "ABSTRACT",                  # non-literal imagery (texture, shape, mood)
    "ILLUSTRATION",              # drawn/designed depiction (human or AI)
    "GENERATED_MUSIC",
    "GENERATED_SFX",
    "GENERATED_VOICE",
}
EVIDENCE_CLASSES = {"EVIDENCE", "ARCHIVAL", "DOCUMENTARY_PHOTO"}
GENERATED_CLASSES = {"GENERATED_RECONSTRUCTION", "GENERATED_CONCEPT", "GENERATED_MUSIC", "GENERATED_SFX", "GENERATED_VOICE"}

# Image generation: the visual role a request declares -> the class its output will carry.
IMAGE_ROLE_CLASS = {
    "conceptual": "GENERATED_CONCEPT",
    "reconstruction": "GENERATED_RECONSTRUCTION",
    "illustration": "ILLUSTRATION",
    "abstract": "ABSTRACT",
}
AUDIO_KIND_CLASS = {"music": "GENERATED_MUSIC", "sfx": "GENERATED_SFX", "voice": "GENERATED_VOICE"}


def generated_media_class(kind: str, visual_role: str | None) -> str | None:
    """Class a generated output will carry, or None when that role cannot be generated (e.g. evidence)."""
    if kind == "image":
        return IMAGE_ROLE_CLASS.get(visual_role or "")
    return AUDIO_KIND_CLASS.get(kind)


def is_generated(asset: dict) -> bool:
    return bool(asset.get("generated") or asset.get("media_class") in GENERATED_CLASSES
                or (asset.get("provenance") or {}).get("generator"))


def can_satisfy_evidence(asset: dict) -> tuple[bool, str]:
    """Can this asset be the evidence for a factual claim? Returns (ok, reason)."""
    cls = asset.get("media_class")
    if cls is not None and cls not in MEDIA_CLASSES:
        return False, f"unknown media class {cls!r}"
    if is_generated(asset):
        return False, "Generated media never counts as evidence, whatever it depicts."
    if cls not in EVIDENCE_CLASSES:
        return False, f"{cls or 'Unclassified'} media is illustrative; evidence needs EVIDENCE, ARCHIVAL or DOCUMENTARY_PHOTO."
    if asset.get("rights_status") != "verified":
        return False, "Evidence media needs verified rights."
    if not (asset.get("source_url") or (asset.get("provenance") or {}).get("source_url")) or not asset.get("sha256"):
        return False, "Evidence media needs a source and a checksum."
    return True, "Recorded media with provenance and verified rights."
