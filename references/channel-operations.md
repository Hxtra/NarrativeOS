# Channel operations: profiles, creative memory, the production graph, packaging and publishing

This layer came from the owner's research on Rookcast (`Rookcast__Deep_Research_on_How_It_Works.md`, 28 Sep 2026,
kept outside the repo). I checked its key claims against rookcast.com on 5 Oct 2026. The research's conclusion
holds:

- **Rookcast's strength is orchestration.** It runs a channel-level agent with persistent memory, a pipeline
  where "every generation step is a visible node you can inspect, approve or revise", pause and redirect, a
  hard human sign-off before publishing, provider keys you can bring yourself, and packaging plus upload.
- **Its music intelligence is undocumented.** NarrativeOS borrows the orchestration pattern and keeps its own
  evidence model.

## What exists now

| Piece | Where | Status |
|---|---|---|
| Channel profile: voice, pacing, visual language, audience promise, cadence, music policy, packaging, QA thresholds. Every change is a new immutable version with a reason. Stored outside the repo (`$NARRATIVEOS_CHANNELS`, default `~/NarrativeOS-Channels`). | `scripts/channel.py`, `schemas/channel_profile.schema.json` | IMPLEMENTED |
| A project pins an exact profile version and hash (`channel.py apply`). STYLE_LOCK refuses a pin that was edited by hand. | `channel.py`, `controller.py` | IMPLEMENTED |
| Creative memory: accepted, rejected or corrected decisions, with stage, target, before/after, reason and tags. A rejection or correction must give its reason. Precedents are **advisory**. | `scripts/creative_memory.py` | IMPLEMENTED |
| Channel rules come only from an explicit `promote` of ≥ 2 decisions. They must come from ≥ 2 different videos, share one stage and agree with each other. A promote writes a new profile version; `retire` removes a rule the same way. One correction is never silently turned into a rule. | `creative_memory.py` | IMPLEMENTED |
| Visible production graph: every stage with its status (passed / **stale** / blocked / current / pending), its artifacts (sha256 now vs. at pass), blocking evidence, revisions and what it feeds (`controller.py --graph`). | `controller.py` | IMPLEMENTED |
| Staleness: a passed stage whose artifacts changed afterwards, or whose upstream passed again later, is stale and blocks everything that depends on it. This answers the research's reproducibility gap, "can a later change silently alter an approved result?" | `controller.py` | IMPLEMENTED |
| Pause (with a reason), resume, and `--revise STAGE --reason`. Revise reopens that stage and everything downstream and logs why. | `controller.py` | IMPLEMENTED |
| Provenance lineage per output: profile pin, script, narration provider and model, every generation job (provider, model, request hash, output hash), analysis artifacts, timeline, renderer, QA, approvals, disclosure. Missing items are `unknown` with the reason. | `scripts/build_provenance.py` | IMPLEMENTED |
| Publish package checked against platform limits, with an approval bound to the package hash (any edit voids it). | `scripts/publish_package.py` | IMPLEMENTED |
| `containsSyntheticMedia` derived from the provenance of the assets actually in the cut. Realistic generated media (reconstructions, generated voice) gives `true`. Generated media that is only conceptual is flagged for review. | `publish_package.py` + `media_semantics.py` | IMPLEMENTED |
| Repetition guard: script wording (5-gram MinHash; the history stores the signature, never the text), shot structure, transition sequence, reused assets and title against the channel's earlier videos. Above the thresholds the result is `review_required`. | `scripts/repetition_guard.py` | IMPLEMENTED |
| Explicit restraint: a strong music event (impact, section change, breakdown) that no rule acted on becomes a **NO_OP** event, with reasons taken from the actual settings. It compiles to a `deliberate_no_op` marker. | `director_brain.py`, `event_graph.py` | IMPLEMENTED |
| YouTube publish plan: the exact `videos.insert` body and `thumbnails.set` call, all gates checked, quota accounted. | `scripts/publish_youtube.py` | IMPLEMENTED (dry run) |
| Real upload | `publish_youtube.py` | **BLOCKED**: needs the owner's OAuth client and channel consent. Nothing is sent, and `publish_manifest.json` is only written by a real upload. |

## Research findings used here (checked 5 Oct 2026)

- **Upload quota.** YouTube Data API v3 gives a default of 100 `videos.insert` calls per day. `thumbnails.set` costs 50 of the 10,000 daily units for other endpoints. ([quota costs](https://developers.google.com/youtube/v3/determine_quota_cost))
  - Secondary sources still quote the old figure of about 1,600 units per upload. Use the official page.
- **Private lock.** Videos uploaded by API projects created after 28 Jul 2020 that have not passed YouTube's compliance audit are forced to private, whatever `privacyStatus` says. ([videos resource](https://developers.google.cn/youtube/v3/docs/videos?hl=en)) The publish plan states this.
- **Synthetic-media disclosure.** `status.containsSyntheticMedia` was added 30 Oct 2024. It is settable on `videos.insert` and optional, and omitting it raises no warning. ([revision history](https://developers.google.com/youtube/v3/revision_history)) NarrativeOS sets it from provenance.
- **Metadata limits.**
  - Title: 1–100 characters.
  - Description: ≤ 5,000 characters. The API counts bytes, so we check bytes.
  - Tags: ≤ 500 characters in total.
  - Thumbnail: JPG or PNG, ≤ 2 MB, ≥ 640 px wide, 16:9 (1280×720 recommended).
  - No `<` or `>` in the title or description.
  - Made-for-kids must be declared.
  - ([thumbnail size](https://thumbnailtest.com/guides/youtube-thumbnail-size/), [title/description limits](https://mail.tuberanker.com/blog/youtube-title-description-character-limit))
- **Monetisation risk.** The YouTube Partner Program's "inauthentic content" policy, effective 15 Jul 2025, demonetises mass-produced and repetitive videos: templated formats, slideshow-and-robot-voice channels. ([Plagiarism Today](https://www.plagiarismtoday.com/2025/07/08/youtube-targets-inauthentic-content/), [Gulf News](https://gulfnews.com/technology/youtube-updates-monetisation-policies-ai-and-repetitive-content-ban-begins-july-15-1.500192660)) This is why the repetition guard exists. It measures; it does not predict a platform decision.

## Candidate tools for the remaining gaps (not integrated)

| Gap (currently NOT_MEASURED) | Candidate | Licence (as found) | Notes |
|---|---|---|---|
| Downbeat, meter | **Beat This!** (CPJKU, ISMIR 2024) | MIT, code and weights | Transformer beat/downbeat tracker without DBN post-processing. CPU inference is possible. |
| Song sections (intro/verse/chorus) | **allin1** (All-In-One Music Structure Analyzer) | verify before use | Gives BPM, beats, downbeats, segment boundaries and labels. |
| Music vs. SFX vs. voice | **Demucs** source separation | verify before use | Separating the music bed from effects would sharpen the breakdown's sound detection. |
| Word-level narration timing | **WhisperX** | reported MIT; verify | Forced alignment for `NARRATION_ALIGNMENT`. |
| Sound identity ("whoosh", "bird", "water") | **LAION-CLAP** (zero-shot audio-text) or PANNs (AudioSet, 527 classes) | CLAP reported Apache-2.0 / CC0; PANNs verify | Would let the breakdown name sounds; must stay labelled INFERRED. |

Each would plug in behind a provider interface (as `model_provider.py` does for reasoning), so no vendor is assumed.

## Next steps

1. **Owner decision:** whether to set up YouTube OAuth for a real (private-first) upload path, and whether to submit the project for YouTube's compliance audit.
2. **Integrate Beat This!** for downbeats. It turns the music map's `downbeat` and `meter` from NOT_MEASURED into INFERRED.
3. **A review UI over `production_graph.json`:** approve, revise and pause per node, with creative-memory capture on every correction.
4. **Feed creative-memory precedents into the Director** as advisory context, never as rules.
