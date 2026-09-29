# Generative media: planner, gates, semantics, continuity

Code:
- `scripts/generation.py` (jobs and state machine)
- `scripts/generation_cli.py` (one command per transition)
- `scripts/media_semantics.py` (what media is and whether it can be evidence)
- `scripts/continuity_bible.py` (recurring people, places, objects and environments)

The planner is provider-independent. No vendor is built in, and nothing
executes silently.

## Capabilities

| Kind | Status |
|---|---|
| image | IMPLEMENTED: needs `width` and `height` |
| music | IMPLEMENTED: needs `duration_sec` |
| sfx | IMPLEMENTED: needs `duration_sec` |
| voice | IMPLEMENTED: needs `text`; takes the production's narration direction |
| video | **DISABLED** by a capability flag (`CAPABILITIES["video"]`). A video job is planned in state `DISABLED`, and every transition, quote and adapter load refuses it, even when a video provider is configured. Enabling it later is a flag plus media verification, with no redesign. |

**Providers.** A providers config maps each kind to an adapter.
IMPLEMENTED:
- the `command` adapter, for any local generator CLI (Stable Diffusion /
  ComfyUI, MusicGen, a TTS engine);
- price-table quotes (`build_quote`).

PLANNED: adapters for hosted APIs (for example OpenAI, FAL, ElevenLabs).
They need keys and an owner's choice. None is configured today, so real
generation is BLOCKED until a provider is added.

## State machine

```
REQUESTED -> QUOTED -> COST_APPROVED -> RIGHTS_APPROVED -> READY -> GENERATING -> GENERATED -> REGISTERED
side states: DISABLED, BLOCKED_SOURCING, FAILED, REJECTED
```

- **Planning.** Planning hashes the request: kind, purpose, spec, style,
  continuity and references.
- **Quotes.** A quote must match that hash. It must carry provider, model,
  amount, currency, basis (`provider_quote`, `price_table_estimate` or
  `local_zero_cost`) and rights terms.
- **Approvals.** Cost and rights approvals must carry the hash of the
  current quote. Re-quoting resets both gates.
- **Gates that don't apply are recorded, never skipped:**
  - `waive_cost` works only for a zero-cost quote;
  - `rights_not_applicable` works only when the quote states
    `rights_review_required: false`.

  Either way the job still passes through COST_APPROVED and
  RIGHTS_APPROVED, with the gate recorded as `not_applicable`.
- **READY** requires:
  - an enabled capability;
  - a route that allows generation;
  - both gates settled;
  - verified reference-image bytes and rights.
- **GENERATED** requires verified output bytes whose provenance matches the
  quote. Images are checked as single still images; audio is checked as
  audio-only.
- **REGISTERED** requires an approved review. It produces an asset record
  with provenance: provider, model, quote version, prompt and reference
  hashes.
- **History.** Every step is appended to `history`.

## Media semantics: generated is never evidence

- **Classes:**
  - evidence-capable: `EVIDENCE`, `ARCHIVAL`, `DOCUMENTARY_PHOTO`;
  - illustrative: `STOCK`, `ILLUSTRATION`, `ABSTRACT`;
  - generated: `GENERATED_RECONSTRUCTION`, `GENERATED_CONCEPT`,
    `GENERATED_MUSIC`, `GENERATED_SFX`, `GENERATED_VOICE`.
- **Image roles.** A request's `visual_role` sets its class:
  - `conceptual` → GENERATED_CONCEPT;
  - `reconstruction` → GENERATED_RECONSTRUCTION;
  - `illustration` → ILLUSTRATION, and requires a recorded stock search
    first;
  - `abstract` → ABSTRACT;
  - any evidence role → BLOCKED_SOURCING. It can't be generated.
- **The evidence rule.** `can_satisfy_evidence(asset)` accepts only
  evidence-capable classes with verified rights, a source and a checksum.
  Anything generated (flag, class or provenance) is refused, even when it is
  mislabelled as archival.
- **Enforcement.** `evidence_links.py` applies the rule: a claim is
  `evidence_supported` only by such media. Otherwise it is
  `illustrative_only`.

## Continuity bible

Each recurring `person`, `location`, `object` or `environment` is one
explicit record:
- `visual_description`;
- `appearance_constraints`, `environment_constraints` and
  `style_constraints`;
- `reference_assets`;
- `approved_reference`;
- `generation_history`.

The bible also holds a production-wide `style_lock`.

- `resolve_continuity(bible, ids)` resolves everything from ids alone.
  Unknown ids raise, so a new identity or place is never guessed.
- Reference assets are passed to the generator as structured inputs (the
  approved reference first, marked `approved_reference`), not only as prompt
  text.
- `register_generated_reference` makes an approved, registered image the
  entity's approved reference and appends it to the history. The next
  request for that entity picks it up automatically.
- Older bibles (`attributes`, `reference_images`, a separate `locations`
  list) are read transparently.

## CLI walk-through

```bash
P=my_project
python scripts/generation_cli.py plan  --project $P --need need.json --profile profile.json --bible bible.json
python scripts/generation_cli.py quote --project $P --id IMG1 --providers providers.json --version q1
python scripts/generation_cli.py show  --project $P --id IMG1          # read quote_hash
python scripts/generation_cli.py approve-cost   --project $P --id IMG1 --by owner --quote-hash <hash>
python scripts/generation_cli.py approve-rights --project $P --id IMG1 --by owner --quote-hash <hash>
python scripts/generation_cli.py ready    --project $P --id IMG1
python scripts/generation_cli.py run      --project $P --id IMG1 --providers providers.json
python scripts/generation_cli.py review   --project $P --id IMG1 --by owner --approve
python scripts/generation_cli.py register --project $P --id IMG1 --bible bible.json --entity NYC_STREET
```

`tests/test_integration_flows.py` runs this exact flow end to end, with a
local stand-in generator.
