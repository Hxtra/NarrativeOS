"""Provider-independent generative media jobs with explicit cost and rights gates.

A job moves through an explicit state machine; nothing executes silently:

    REQUESTED -> QUOTED -> COST_APPROVED -> RIGHTS_APPROVED -> READY -> GENERATING -> GENERATED -> REGISTERED

Side states: DISABLED (capability off, e.g. AI video), BLOCKED_SOURCING (must search stock / cannot be
generated, e.g. factual evidence), FAILED (generator error), REJECTED (output refused in review).
A gate that does not apply (a zero-cost local model; a provider whose terms need no rights review) is
recorded as ``not_applicable`` with a reason: the state still advances through it, never around it.

No provider is built in. Adapters are chosen per kind from a providers config (see ``load_adapter``).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from continuity_bible import register_reference, resolve_continuity
from editorial_style import fingerprint
from media_semantics import generated_media_class

# Capability flags. Video is a known kind that is explicitly switched off, not merely unconfigured.
CAPABILITIES = {
    "image": {"enabled": True},
    "music": {"enabled": True},
    "sfx": {"enabled": True},
    "voice": {"enabled": True},
    "video": {"enabled": False, "reason": "AI video generation is disabled by owner decision (2026-09-29)."},
}
GENERATABLE = {k for k, v in CAPABILITIES.items() if v["enabled"]}
FLOW = ["REQUESTED", "QUOTED", "COST_APPROVED", "RIGHTS_APPROVED", "READY", "GENERATING", "GENERATED", "REGISTERED"]
QUOTE_BASES = {"provider_quote", "price_table_estimate", "local_zero_cost"}
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

# The part of a job that defines *what* is asked for. It is hashed; quotes and approvals bind to the hash.
REQUEST_KEYS = ("schema_version", "request_id", "kind", "purpose", "visual_role", "media_class", "route", "spec",
                "style_id", "direction", "continuity", "reference_images", "stock_search", "representation", "can_support_claim")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def request_hash(job: dict) -> str:
    return fingerprint({k: job.get(k) for k in REQUEST_KEYS})


def _status(state: str) -> str:
    return {"READY": "ready", "GENERATING": "generating", "GENERATED": "review_required", "REGISTERED": "registered",
            "DISABLED": "disabled", "FAILED": "failed", "REJECTED": "rejected"}.get(state, "blocked")


def _guard(job: dict) -> None:
    """Checked first by every transition: a disabled capability refuses before anything else is looked at."""
    if job.get("state") == "DISABLED" or not CAPABILITIES.get(job.get("kind"), {}).get("enabled"):
        raise ValueError(f"{job.get('kind')} generation is disabled: {CAPABILITIES.get(job.get('kind'), {}).get('reason', 'unknown kind')}")


def _move(job: dict, allowed_from: set[str], to: str, note: str) -> None:
    if job["state"] == "DISABLED":
        raise ValueError(f"{job['kind']} generation is disabled: {job['reason']}")
    if job["state"] not in allowed_from:
        raise ValueError(f"cannot move job {job['request_id']} from {job['state']} to {to}")
    if request_hash(job) != job["request_hash"]:
        raise ValueError("job request was modified after planning; re-plan it")
    job["state"], job["status"] = to, _status(to)
    job["history"].append({"state": to, "at": _now(), "note": note})


# ---------------------------------------------------------------------------------------------- planning

def _spec(need: dict, kind: str, style: dict) -> dict:
    def positive(name, integer=False, maximum=None):
        v = need.get(name)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 or (integer and int(v) != v) or (maximum and v > maximum):
            raise ValueError(f"{kind} request needs a positive {name}" + (f" <= {maximum}" if maximum else ""))
        return int(v) if integer else float(v)
    if kind == "image":
        return {"width": positive("width", True, 8192), "height": positive("height", True, 8192)}
    if kind in {"music", "sfx"}:
        return {"duration_sec": positive("duration_sec", maximum=600)}
    if kind == "voice":
        if not isinstance(need.get("text"), str) or not need["text"].strip():
            raise ValueError("voice request needs the text to speak")
        return {"text": need["text"], "voice_direction": deepcopy(style.get("narration", {}))}
    return {}


def plan_request(need: dict, style: dict, bible: dict | None = None) -> dict:
    """Plan a generation job from a need, the production's resolved style, and the continuity bible."""
    if not isinstance(need, dict) or not isinstance(need.get("request_id"), str) or not _ID.match(need["request_id"]):
        raise ValueError("need.request_id must be 1-64 letters, digits, '-' or '_'")
    kind = need.get("kind")
    if kind not in CAPABILITIES:
        raise ValueError(f"unknown generation kind {kind!r}; known: {sorted(CAPABILITIES)}")
    if not isinstance(need.get("purpose"), str) or not need["purpose"].strip():
        raise ValueError("need.purpose (the brief) is required")
    job = {"schema_version": 2, "request_id": need["request_id"], "kind": kind, "purpose": need["purpose"],
           "visual_role": need.get("visual_role"), "provider": None, "model": None, "quote": None,
           "gates": {"cost": {"state": "pending"}, "rights": {"state": "pending"}},
           "review": {"required": True, "approved": False}, "output": None, "asset": None, "history": []}
    if not CAPABILITIES[kind]["enabled"]:
        job.update(state="DISABLED", status="disabled", reason=CAPABILITIES[kind]["reason"], capability=deepcopy(CAPABILITIES[kind]))
        job["history"].append({"state": "DISABLED", "at": _now(), "note": CAPABILITIES[kind]["reason"]})
        return job

    ids = list(need.get("entity_ids", [])) + ([need["location_id"]] if need.get("location_id") else [])
    continuity = resolve_continuity(bible or {}, ids)
    direction_key = "narration" if kind == "voice" else kind
    job.update(
        media_class=generated_media_class(kind, need.get("visual_role")),
        route="generate_direct", spec=_spec(need, kind, style), style_id=style["style_id"],
        direction=deepcopy(style.get(direction_key, {})), continuity=continuity,
        reference_images=[deepcopy(r) for r in continuity["reference_inputs"]],
        stock_search=deepcopy(need.get("stock_search")),
        representation="generated_illustration_not_factual_evidence", can_support_claim=False)
    reason = "Awaiting a quote, then cost and rights approval."
    if kind == "image":
        role, search = need.get("visual_role"), need.get("stock_search") or {}
        if job["media_class"] is None:
            job["route"], reason = "blocked_factual_evidence", "This visual role needs real recorded media; generated images never stand in for evidence."
        elif role == "illustration":
            rejected = search.get("rejections", [])
            searched = search.get("status") == "no_suitable_assets" and search.get("search_id") and rejected and all(r.get("asset_id") and r.get("reason") for r in rejected)
            if searched:
                job["route"] = "generate_fallback"
            else:
                job["route"], reason = "stock_search_required", "Search stock/archive first and record why candidates were rejected."
    state = "REQUESTED" if job["route"] in {"generate_direct", "generate_fallback"} else "BLOCKED_SOURCING"
    job.update(state=state, status=_status(state), reason=reason)
    job["request_hash"] = request_hash(job)
    job["prompt"] = compose_prompt(job)
    job["history"].append({"state": state, "at": _now(), "note": reason})
    return job


# ---------------------------------------------------------------------------------------------- gates

def attach_quote(job: dict, quote: dict) -> dict:
    """REQUESTED (or QUOTED, to re-quote) -> QUOTED. The quote binds to this exact request."""
    _guard(job)
    amount = quote.get("amount")
    if (not all(isinstance(quote.get(k), str) and quote[k] for k in ("version", "provider", "model", "currency", "rights_terms"))
            or quote.get("basis") not in QUOTE_BASES
            or isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount < 0
            or (quote["basis"] == "local_zero_cost" and amount != 0)
            or quote.get("request_hash") != job.get("request_hash")):
        raise ValueError("quote needs version, provider, model, currency, rights_terms, a known basis, a finite amount >= 0, and this job's request_hash")
    _move(job, {"REQUESTED", "QUOTED"}, "QUOTED", f"{quote['basis']}: {amount} {quote['currency']} via {quote['provider']}/{quote['model']}")
    job.update(quote=deepcopy(quote), provider=quote["provider"], model=quote["model"])
    job["gates"] = {"cost": {"state": "pending"}, "rights": {"state": "pending"}}
    return job


def _bound(job: dict, quote_hash: str) -> None:
    if quote_hash != fingerprint(job["quote"]):
        raise ValueError("approval does not match the current quote")


def approve_cost(job: dict, approved_by: str, quote_hash: str) -> dict:
    _guard(job)
    _bound(job, quote_hash)
    _move(job, {"QUOTED"}, "COST_APPROVED", f"cost approved by {approved_by}")
    job["gates"]["cost"] = {"state": "approved", "by": approved_by, "at": _now(), "quote_hash": quote_hash}
    return job


def waive_cost(job: dict, reason: str) -> dict:
    """Only a zero-cost quote may skip cost approval; the waiver is recorded, not implied."""
    _guard(job)
    if not job.get("quote") or job["quote"]["amount"] != 0:
        raise ValueError("cost approval can only be marked not applicable for a zero-cost quote")
    _move(job, {"QUOTED"}, "COST_APPROVED", f"cost not applicable: {reason}")
    job["gates"]["cost"] = {"state": "not_applicable", "reason": reason, "at": _now()}
    return job


def approve_rights(job: dict, approved_by: str, quote_hash: str) -> dict:
    _guard(job)
    _bound(job, quote_hash)
    _move(job, {"COST_APPROVED"}, "RIGHTS_APPROVED", f"rights/usage approved by {approved_by}")
    job["gates"]["rights"] = {"state": "approved", "by": approved_by, "at": _now(), "terms": job["quote"]["rights_terms"]}
    return job


def rights_not_applicable(job: dict, reason: str) -> dict:
    """Only when the quote itself states that no rights review is required."""
    _guard(job)
    if not job.get("quote") or job["quote"].get("rights_review_required") is not False:
        raise ValueError("rights review can only be marked not applicable when the quote says rights_review_required: false")
    _move(job, {"COST_APPROVED"}, "RIGHTS_APPROVED", f"rights review not applicable: {reason}")
    job["gates"]["rights"] = {"state": "not_applicable", "reason": reason, "terms": job["quote"]["rights_terms"], "at": _now()}
    return job


def mark_ready(job: dict) -> dict:
    """RIGHTS_APPROVED -> READY once every precondition for spending/generating holds."""
    _guard(job)
    if not CAPABILITIES[job["kind"]]["enabled"]:
        raise ValueError(f"{job['kind']} generation is disabled")
    if job.get("route") not in {"generate_direct", "generate_fallback"}:
        raise ValueError("sourcing route does not allow generation")
    if any(g["state"] not in {"approved", "not_applicable"} for g in job["gates"].values()):
        raise ValueError("cost and rights gates must be approved or not applicable")
    for ref in job.get("reference_images", []):
        path = Path(ref.get("local_path", ""))
        if (ref.get("rights_status") != "verified" or ref.get("use_approved") is not True
                or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != ref.get("sha256")):
            raise ValueError("reference bytes or rights unverified")
    _move(job, {"RIGHTS_APPROVED"}, "READY", "all gates passed")
    return job


# ---------------------------------------------------------------------------------------------- execution

def run(job: dict, adapter) -> dict:
    """READY -> GENERATING -> GENERATED (verified bytes + provenance) or FAILED."""
    _guard(job)
    _move(job, {"READY"}, "GENERATING", f"calling {job['provider']}/{job['model']}")
    try:
        supplied = adapter(deepcopy(job), deepcopy(job["quote"]))
        path = Path(supplied.get("path", ""))
        if not path.is_file() or not path.stat().st_size or hashlib.sha256(path.read_bytes()).hexdigest() != supplied.get("sha256"):
            raise ValueError("Output bytes unverified")
        for key in ("provider", "model", "request_hash", "rights_terms"):
            if supplied.get(key) != (job["request_hash"] if key == "request_hash" else job["quote"][key]):
                raise ValueError("Output provenance does not match quote")
        _verify_media(job["kind"], path)
    except Exception as exc:
        job["error"] = str(exc)
        _move(job, {"GENERATING"}, "FAILED", str(exc))
        raise
    job["output"] = {"path": str(path), "sha256": supplied["sha256"], "bytes": path.stat().st_size}
    job["provenance"] = {"generator": True, "provider": job["provider"], "model": job["model"], "request_hash": job["request_hash"],
                         "quote_version": job["quote"]["version"], "prompt": supplied.get("prompt", job["prompt"]),
                         "reference_sha256": [r["sha256"] for r in job.get("reference_images", [])], "generated_at": _now()}
    job["byte_verified"] = True
    _move(job, {"GENERATING"}, "GENERATED", "output verified; awaiting review")
    return job


def _verify_media(kind: str, path: Path) -> None:
    if kind == "image":
        from PIL import Image
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            if getattr(image, "n_frames", 1) != 1:
                raise ValueError("Animated output refused: video generation is disabled")
        return
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)], capture_output=True, text=True, check=True)
    streams = json.loads(probe.stdout).get("streams", [])
    if not streams or any(s.get("codec_type") != "audio" for s in streams):
        raise ValueError("Expected audio-only bytes; video generation is disabled")
    subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"], capture_output=True, check=True)


def review(job: dict, reviewer: str, approved: bool, note: str = "") -> dict:
    _guard(job)
    if job["state"] != "GENERATED":
        raise ValueError("only a GENERATED job can be reviewed")
    job["review"] = {"required": True, "approved": bool(approved), "by": reviewer, "at": _now(), "note": note}
    if not approved:
        _move(job, {"GENERATED"}, "REJECTED", f"rejected by {reviewer}: {note}")
    return job


def register(job: dict) -> dict:
    """GENERATED + approved review -> REGISTERED, producing a media asset record that can never be evidence."""
    _guard(job)
    if job["state"] == "GENERATED" and job["review"].get("approved") is not True:
        raise ValueError("generated output must be approved in review before registration")
    path = Path(job["output"]["path"]) if job.get("output") else None
    if path is None or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != job["output"]["sha256"]:
        raise ValueError("generated bytes changed since verification")
    _move(job, {"GENERATED"}, "REGISTERED", "registered as a generated asset")
    job["asset"] = {"asset_id": f"gen_{job['request_id']}", "kind": job["kind"], "media_class": job["media_class"],
                    "generated": True, "can_support_claim": False, "local_path": job["output"]["path"], "sha256": job["output"]["sha256"],
                    "rights_status": "verified", "rights_terms": job["quote"]["rights_terms"], "use_approved": True,
                    "provenance": deepcopy(job["provenance"]), "style_id": job["style_id"]}
    return job


def register_generated_reference(bible: dict, job: dict, entity_ids: list[str] = (), location_id: str | None = None) -> dict:
    """Make a REGISTERED generated image the approved reference for its entities, so later requests match it."""
    if job.get("state") != "REGISTERED" or job.get("kind") != "image":
        raise ValueError("only a REGISTERED generated image can become a continuity reference (review and register it first)")
    ids = list(entity_ids) + ([location_id] if location_id else [])
    return register_reference(bible, ids, job["asset"], job["request_id"])


def execute_request(request: dict, quote: dict, approval: dict, adapter) -> dict:
    """One-shot convenience over the state machine: quote -> cost -> rights -> ready -> run. Works on a copy."""
    job = deepcopy(request)
    attach_quote(job, quote)
    if approval.get("cost_approved") is not True or approval.get("rights_approved") is not True:
        raise ValueError("Versioned quote and matching cost/rights approval required")
    by = approval.get("by", "approval-record")
    approve_cost(job, by, approval.get("quote_hash"))
    approve_rights(job, by, approval.get("quote_hash"))
    mark_ready(job)
    return run(job, adapter)


# ---------------------------------------------------------------------------------------------- prompts & adapters

def compose_prompt(job: dict) -> str:
    """One deterministic brief from the job: purpose, the production's style, continuity constraints, what to avoid.

    The production's style wins over the moment: a happy scene inside a crime video keeps the crime video's look.
    """
    kind, direction, cont, spec = job["kind"], job.get("direction", {}), job.get("continuity", {}), job.get("spec", {})
    head = {"image": "Image", "music": "Instrumental music", "sfx": "Sound effect", "voice": "Voice-over"}[kind]
    lines = [f"{head}: {job['purpose']}."]
    if kind == "voice":
        lines.append(f"Script to read exactly: \"{spec['text']}\"")
    if direction.get("tone"):
        lines.append(f"Overall tone of the production: {direction['tone']}.")
    details = {k: v for k, v in direction.items() if k not in {"tone", "avoid"}}
    if details:
        lines.append("Style: " + "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in sorted(details.items())) + ".")
    for e in cont.get("entities", []):
        label = e.get("name") or e["entity_id"]
        parts = [e["visual_description"]] if e.get("visual_description") else []
        for group in ("appearance_constraints", "environment_constraints", "style_constraints"):
            parts += [f"{k}: {v}" for k, v in sorted(e.get(group, {}).items())]
        if parts:
            lines.append(f"Recurring {e['kind']} '{label}' must match earlier material: " + "; ".join(parts) + ".")
    if cont.get("style_lock"):
        lines.append("Keep consistent across every generated item: " + "; ".join(f"{k}: {v}" for k, v in sorted(cont["style_lock"].items())) + ".")
    if job.get("reference_images"):
        lines.append(f"Match the {len(job['reference_images'])} attached reference image(s) in lighting, palette and design.")
    if kind == "image":
        lines.append(f"Frame: {spec['width']}x{spec['height']}.")
    if kind in {"music", "sfx"}:
        lines.append(f"Length: {spec['duration_sec']:.1f} seconds.")
    if direction.get("avoid"):
        lines.append("Avoid: " + ", ".join(direction["avoid"]) + ".")
    return "\n".join(lines)


def command_adapter(config: dict):
    """Adapter for a locally installed generator run as a command (image, music, SFX or voice model CLI).

    config: {"provider", "model", "rights_terms", "work_dir", "command": [..."{prompt_file}"..."{out}"...],
             "output_ext": ".png", "timeout_sec": 600}
    Placeholders: {prompt_file} (brief), {refs_file} (JSON list of reference image paths), {spec_file} (JSON spec), {out}.
    """
    for key in ("provider", "model", "rights_terms", "work_dir", "command", "output_ext"):
        if not config.get(key):
            raise ValueError(f"command adapter config needs '{key}'")

    def adapter(job: dict, quote: dict) -> dict:
        work = Path(config["work_dir"]) / job["request_id"]
        work.mkdir(parents=True, exist_ok=False)  # never overwrite an earlier generation
        files = {"prompt_file": work / "prompt.txt", "refs_file": work / "references.json", "spec_file": work / "spec.json"}
        files["prompt_file"].write_text(job["prompt"], encoding="utf-8")
        files["refs_file"].write_text(json.dumps([r["local_path"] for r in job.get("reference_images", [])]), encoding="utf-8")
        files["spec_file"].write_text(json.dumps(job.get("spec", {})), encoding="utf-8")
        out = work / f"output{config['output_ext']}"
        fill = {**{k: str(v) for k, v in files.items()}, "out": str(out)}
        subprocess.run([part.format(**fill) for part in config["command"]], check=True, capture_output=True, timeout=config.get("timeout_sec", 600))
        if not out.is_file():
            raise ValueError("generator produced no output file")
        return {"path": str(out), "sha256": hashlib.sha256(out.read_bytes()).hexdigest(), "provider": config["provider"],
                "model": config["model"], "request_hash": job["request_hash"], "rights_terms": config["rights_terms"], "prompt": job["prompt"]}

    return adapter


ADAPTER_TYPES = {"command": command_adapter}


def load_adapter(providers: dict, kind: str):
    """Configured adapter for a kind. Disabled kinds (video) refuse; a missing provider is BLOCKED, never guessed."""
    if kind not in CAPABILITIES:
        raise ValueError(f"unknown generation kind {kind!r}")
    if not CAPABILITIES[kind]["enabled"]:
        raise ValueError(f"{kind} generation is disabled: {CAPABILITIES[kind]['reason']}")
    config = (providers or {}).get(kind)
    if not config:
        raise ValueError(f"No {kind} generator configured (BLOCKED): add one to the providers config")
    factory = ADAPTER_TYPES.get(config.get("type"))
    if factory is None:
        raise ValueError(f"Unsupported adapter type {config.get('type')!r}; available: {sorted(ADAPTER_TYPES)}")
    return factory(config)


def build_quote(job: dict, provider_config: dict, version: str) -> dict:
    """A quote from a provider's price table (estimate). Hosted providers can instead return their own quote."""
    _guard(job)
    price = provider_config.get("price") or {}
    per_unit, unit = price.get("amount_per_unit"), price.get("unit")
    if isinstance(per_unit, bool) or not isinstance(per_unit, (int, float)) or per_unit < 0 or unit not in {"item", "second", "character"}:
        raise ValueError("provider price needs amount_per_unit >= 0 and unit item|second|character")
    units = {"item": 1, "second": job["spec"].get("duration_sec", 0), "character": len(job["spec"].get("text", ""))}[unit]
    amount = round(per_unit * units, 6)
    quote = {"version": version, "request_hash": job["request_hash"], "provider": provider_config["provider"],
             "model": provider_config["model"], "amount": amount, "currency": price.get("currency", "USD"),
             "basis": "local_zero_cost" if amount == 0 else "price_table_estimate", "rights_terms": provider_config["rights_terms"]}
    if provider_config.get("rights_review_required") is False:
        quote["rights_review_required"] = False
    return quote
