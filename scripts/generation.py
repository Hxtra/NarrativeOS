"""Provider-neutral generation requests. No provider is selected or called by default."""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
from continuity_bible import generation_context
from editorial_style import fingerprint


def plan_request(need: dict, style: dict, bible: dict) -> dict:
    if need.get("kind") not in {"image", "music", "sfx"}:
        raise ValueError("AI video and unknown generation kinds are disabled")
    context = generation_context(bible, need.get("entity_ids", []), need.get("location_id"))
    references = []
    for item in [*context["entities"], context["location"] or {}]:
        for ref in item.get("reference_images", []):
            if ref not in references:
                references.append(deepcopy(ref))
    result = {"schema_version": 1, "request_id": need["request_id"], "kind": need["kind"],
              "purpose": need["purpose"], "status": "blocked", "route": "generate_direct",
              "reason": "Provider configuration, versioned quote, cost and rights approvals required.",
              "style_id": style["style_id"], "direction": deepcopy(style[need["kind"]]),
              "continuity": context, "reference_images": references,
              "representation": "generated_illustration_not_factual_evidence", "can_support_claim": False}
    search = deepcopy(need.get("stock_search"))
    result["stock_search"] = search
    if need["kind"] in {"music", "sfx"} and need.get("duration_sec"):
        result["duration_sec"] = float(need["duration_sec"])
    if need["kind"] == "image":
        role = need.get("visual_role")
        if role not in {"conceptual", "illustration"}:
            result["route"] = "blocked_factual_evidence"
        elif role != "conceptual":
            rejected = (search or {}).get("rejections", [])
            evidence = search and search.get("status") == "no_suitable_assets" and search.get("search_id") and rejected and all(r.get("asset_id") and r.get("reason") for r in rejected)
            result["route"] = "generate_fallback" if evidence else "stock_search_required"
    result["request_hash"] = fingerprint(result)
    return result


def execute_request(request: dict, quote: dict, approval: dict, adapter) -> dict:
    """Explicit opt-in callable adapter; no built-in network/provider execution."""
    import hashlib
    import math
    import subprocess
    import json
    from pathlib import Path
    if request.get("kind") not in {"image", "music", "sfx"}:
        raise ValueError("AI video and unknown generation kinds are disabled")
    body = {k: v for k, v in request.items() if k != "request_hash"}
    if fingerprint(body) != request.get("request_hash") or request.get("route") not in {"generate_direct", "generate_fallback"}:
        raise ValueError("Invalid request or sourcing route")
    amount = quote.get("amount")
    if (not quote.get("version") or not quote.get("provider") or not quote.get("model")
            or not quote.get("currency") or not quote.get("rights_terms")
            or not isinstance(amount, (float, int)) or isinstance(amount, bool) or not math.isfinite(amount) or amount < 0
            or quote.get("request_hash") != request["request_hash"]
            or approval.get("quote_hash") != fingerprint(quote)
            or approval.get("cost_approved") is not True or approval.get("rights_approved") is not True):
        raise ValueError("Versioned quote and matching cost/rights approval required")
    for ref in request.get("reference_images", []):
        path = Path(ref.get("local_path", ""))
        if (ref.get("rights_status") != "verified" or ref.get("use_approved") is not True
                or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != ref.get("sha256")):
            raise ValueError("Reference bytes or rights unverified")
    supplied = adapter(deepcopy(request), deepcopy(quote))
    path = Path(supplied.get("path", ""))
    if not path.is_file() or not path.stat().st_size or hashlib.sha256(path.read_bytes()).hexdigest() != supplied.get("sha256"):
        raise ValueError("Output bytes unverified")
    for key in ("provider", "model", "request_hash", "rights_terms"):
        if supplied.get(key) != quote[key]:
            raise ValueError("Output provenance does not match quote")
    if request["kind"] == "image":
        from PIL import Image
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            if getattr(image, "n_frames", 1) != 1:
                raise ValueError("Animated/video generation disabled")
    else:
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)], capture_output=True, text=True, check=True)
        streams = json.loads(probe.stdout).get("streams", [])
        if not streams or any(s.get("codec_type") != "audio" for s in streams):
            raise ValueError("Expected audio-only bytes; AI video disabled")
        subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"], capture_output=True, check=True)
    return {**deepcopy(supplied), "status": "review_required", "byte_verified": True,
            "review": {"required": True, "approved": False}, "can_support_claim": False,
            "request": deepcopy(request), "quote": deepcopy(quote), "approval": deepcopy(approval)}


GENERATABLE = {"image", "music", "sfx"}


def compose_prompt(request: dict) -> str:
    """One deterministic prompt from the request: purpose, the video's style, locked continuity, and what to avoid.

    The style wins over the moment: a happy scene inside a crime video still gets the crime video's tone and look.
    """
    kind = request["kind"]
    direction = request.get("direction", {})
    context = request.get("continuity", {})
    lines = [{"image": "Image", "music": "Instrumental music", "sfx": "Sound effect"}[kind] + f": {request['purpose']}."]
    if direction.get("tone"):
        lines.append(f"Overall tone of the production: {direction['tone']}.")
    details = {k: v for k, v in direction.items() if k not in {"tone", "avoid"}}
    if details:
        lines.append("Style: " + "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in sorted(details.items())) + ".")
    for entity in context.get("entities", []):
        attrs = entity.get("attributes", {})
        if attrs:
            lines.append(f"Recurring subject {entity['entity_id']} must match earlier shots: " + "; ".join(f"{k}: {v}" for k, v in sorted(attrs.items())) + ".")
    location = context.get("location") or {}
    if location.get("attributes"):
        lines.append(f"Same place as before ({location['location_id']}): " + "; ".join(f"{k}: {v}" for k, v in sorted(location["attributes"].items())) + ".")
    lock = context.get("generation_lock") or {}
    if lock:
        lines.append("Keep consistent across every generated item: " + "; ".join(f"{k}: {v}" for k, v in sorted(lock.items())) + ".")
    if request.get("reference_images"):
        lines.append(f"Match the {len(request['reference_images'])} attached reference image(s) in lighting, palette and design.")
    if kind in {"music", "sfx"} and request.get("duration_sec"):
        lines.append(f"Length: {request['duration_sec']:.1f} seconds.")
    if direction.get("avoid"):
        lines.append("Avoid: " + ", ".join(direction["avoid"]) + ".")
    return "\n".join(lines)


def command_adapter(config: dict):
    """Adapter for a locally installed generator run as a command (e.g. a Stable Diffusion / ComfyUI / MusicGen CLI).

    config: {"provider", "model", "rights_terms", "work_dir", "command": [..."{prompt_file}"..."{out}"...],
             "output_ext": ".png", "timeout_sec": 600}
    Placeholders: {prompt_file} (prompt text), {refs_file} (JSON list of reference image paths), {out} (output path).
    """
    import hashlib
    import json
    import subprocess
    for key in ("provider", "model", "rights_terms", "work_dir", "command", "output_ext"):
        if not config.get(key):
            raise ValueError(f"command adapter config needs '{key}'")

    def adapter(request: dict, quote: dict) -> dict:
        work = Path(config["work_dir"]) / request["request_id"]
        work.mkdir(parents=True, exist_ok=False)  # never overwrite an earlier generation
        prompt_file, refs_file = work / "prompt.txt", work / "references.json"
        out = work / f"output{config['output_ext']}"
        prompt_file.write_text(compose_prompt(request), encoding="utf-8")
        refs_file.write_text(json.dumps([r["local_path"] for r in request.get("reference_images", [])]), encoding="utf-8")
        fill = {"prompt_file": str(prompt_file), "refs_file": str(refs_file), "out": str(out)}
        cmd = [part.format(**fill) for part in config["command"]]
        subprocess.run(cmd, check=True, capture_output=True, timeout=config.get("timeout_sec", 600))
        if not out.is_file():
            raise ValueError("generator produced no output file")
        return {"path": str(out), "sha256": hashlib.sha256(out.read_bytes()).hexdigest(), "provider": config["provider"],
                "model": config["model"], "request_hash": request["request_hash"], "rights_terms": config["rights_terms"],
                "prompt": prompt_file.read_text(encoding="utf-8")}

    return adapter


def load_adapter(providers: dict, kind: str):
    """Pick the configured adapter for a kind. AI video stays disabled; a missing provider is BLOCKED, not guessed."""
    if kind not in GENERATABLE:
        raise ValueError("AI video and unknown generation kinds are disabled")
    config = (providers or {}).get(kind)
    if not config:
        raise ValueError(f"No {kind} generator configured (BLOCKED): add one to the providers config")
    if config.get("type") != "command":
        raise ValueError(f"Unsupported adapter type {config.get('type')!r}; only 'command' is implemented")
    return command_adapter(config)


def register_generated_reference(bible: dict, result: dict, entity_ids: list[str] = (), location_id: str | None = None) -> dict:
    """After a generated image is approved, make it the reference for its subjects/place so later images match it.

    Returns a new bible. Refuses anything not byte-verified and human-approved.
    """
    import hashlib
    request = result.get("request", {})
    if request.get("kind") != "image":
        raise ValueError("Only generated images can become visual references")
    if result.get("byte_verified") is not True or result.get("review", {}).get("approved") is not True:
        raise ValueError("Generated image must be byte-verified and approved in review first")
    path = Path(result["path"])
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != result["sha256"]:
        raise ValueError("Generated image bytes changed since verification")
    out = deepcopy(bible)
    ref = {"asset_id": f"gen_{request['request_id']}", "local_path": str(path), "sha256": result["sha256"],
           "rights_status": "verified", "use_approved": True, "source": "generated",
           "provider": result["provider"], "model": result["model"], "request_hash": request["request_hash"],
           "representation": "generated_illustration_not_factual_evidence"}
    targets = [e for e in out.get("entities", []) if e["entity_id"] in entity_ids]
    targets += [l for l in out.get("locations", []) if l["location_id"] == location_id]
    if len(targets) != len(set(entity_ids)) + (1 if location_id else 0):
        raise ValueError("Unknown entity or location id")
    for target in targets:
        refs = target.setdefault("reference_images", [])
        if all(r.get("sha256") != ref["sha256"] for r in refs):
            refs.append(deepcopy(ref))
    lock = out.setdefault("generation_lock", {})
    lock.setdefault("style_id", request.get("style_id"))
    lock.setdefault("first_reference_sha256", ref["sha256"])
    return out
