# NarrativeOS Editing Brain

## Research scope and conclusion

This document translates professional editing practice into an implementation specification for NarrativeOS. It covers cutting, pacing, continuity, montage, documentary structure, sound effects, music, motion graphics, visual effects, colour, captions, accessibility, platform adaptations, timeline modeling, and quality assurance.

The central conclusion is that NarrativeOS should not encode editing as a list of isolated effects. It should encode **editorial intent**, then compile that intent into coordinated video, audio, motion, graphics, caption, and transition operations. A hard cut, a sound effect, a push-in, and a caption emphasis are not independent decisions when they occur at the same narrative moment.

Professional editing guidance consistently treats the cut as a decision about **time, space, attention, continuity, and meaning**. Adobe's editing guidance describes straight cuts, jump cuts, match cuts, smash cuts, cross-cutting, J-cuts, and L-cuts as tools that change pacing, tone, tension, and narrative relationships.[1] OpenTimelineIO provides a useful interchange model for timelines, tracks, clips, gaps, transitions, media references, and time ranges, but it does not express why an editorial decision exists.[2] NarrativeOS must therefore retain its own narrative and evidence layer above a renderer-independent timeline.

Platform guidance should be treated as a constraint layer rather than as universal artistic law. TikTok's official creative guidance recommends vertical 9:16 content, sound or music, at least 720p, UI-safe placement, a clear early proposition, captions or overlays, and continuous testing.[3] YouTube's official upload guidance specifies delivery requirements such as MP4, H.264, and AAC-LC or Opus audio.[4] These recommendations support platform adaptation, but they do not replace editorial judgment or prove that a particular pacing rule will work for every audience.

## 1. The editing-brain model

NarrativeOS should operate as five connected layers:

| Layer | Question | NarrativeOS responsibility |
|---|---|---|
| Editorial intent | What should the audience understand, feel, or anticipate? | Interpret claims, beats, emotion, stakes, and channel style. |
| Event graph | What should happen at this narrative moment? | Create events such as `REVEAL`, `COMPARE`, `EMPHASIZE`, `PAUSE`, and `PAYOFF`. |
| Operations | How should the event be expressed? | Select cuts, overlays, motion, audio responses, captions, and transitions. |
| Timeline IR | What objects occupy which tracks and time ranges? | Store executable editorial structure independently from the renderer. |
| Render and QA | Can the plan be rendered and does the result satisfy its contracts? | Compile to FFmpeg or another adapter, then inspect streams, frames, audio, captions, and evidence. |

The event graph is the key addition. It lets one editorial decision produce coordinated responses across several systems. For example, an evidence reveal can introduce a verified photograph, apply a restrained push-in, duck music, add a short impact sound, and emphasize a caption. The system must be able to explain that all of those operations came from one event supporting one claim.

## 2. Cutting and continuity

### 2.1 Cut vocabulary

NarrativeOS should represent cut types as operations with explicit intent rather than as decorative transitions.

| Operation | Editorial use | Required constraints |
|---|---|---|
| `HARD_CUT` | Move directly between shots while preserving momentum or continuity. | Check subject, screen direction, temporal logic, and evidence relevance. |
| `JUMP_CUT` | Compress time, create urgency, or expose discontinuity as a style. | Require a style permission or explicit editorial reason. |
| `MATCH_CUT` | Connect shots through shape, movement, colour, composition, or concept. | Require a verified match feature rather than filename similarity. |
| `SMASH_CUT` | Create an abrupt contrast, shock, joke, or tonal break. | Require a high-contrast narrative reason and preview review. |
| `CROSS_CUT` | Alternate simultaneous or conceptually linked actions. | Require temporal relationship metadata between sequences. |
| `CUTAWAY` | Redirect attention, hide an edit, or provide context. | The cutaway must support the current claim or beat. |
| `J_CUT` | Let incoming sound begin before the picture changes. | Audio source and overlap must be time-resolved. |
| `L_CUT` | Let outgoing sound continue over the next picture. | Preserve dialogue meaning and avoid contradictory audio. |
| `DISSOLVE` | Signal passage, association, memory, or a softer transition. | Avoid using it as a default when a hard cut is clearer. |

Adobe explicitly recommends cutting on motion, preserving handles, using J-cuts and L-cuts for dialogue flow, and reviewing cuts repeatedly.[1] NarrativeOS should make these recommendations machine-checkable where possible. A candidate cut should record whether it has handles, whether motion continuity exists, whether screen direction is preserved, and whether the audio overlap is intentional.

### 2.2 Continuity constraints

The continuity validator should inspect:

1. **Temporal continuity:** the sequence does not imply an impossible order unless the event is marked as flashback, reconstruction, or montage.
2. **Spatial continuity:** camera direction, geography, eyelines, and screen direction are not accidentally contradicted.
3. **Action continuity:** the position and phase of an action are compatible across the cut.
4. **Subject continuity:** identity, clothing, objects, and state changes are consistent with the continuity bible.
5. **Evidence continuity:** a shot does not visually contradict the narration or claim it is assigned to support.
6. **Track continuity:** ripple or retime operations update dependent captions, audio events, markers, and downstream clips.

NarrativeOS must not force continuity when discontinuity is the intended editorial meaning. The event should record the reason for the violation, such as `TIME_COMPRESSION`, `MEMORY`, `CONTRAST`, or `SUBJECTIVE_DISORIENTATION`.

## 3. Pacing, rhythm, and building

Pacing is not simply average shot duration. It is the relationship between information delivery, emotional change, visual change, sound change, and viewer expectation.

The editing brain should divide a sequence into **beats** and assign each beat a role:

| Beat role | Function | Typical editorial response |
|---|---|---|
| `HOOK` | Establish a question, threat, mystery, or promise. | High information density, immediate proposition, or controlled surprise. |
| `ORIENT` | Give the viewer the necessary who, where, and when. | Clear establishing image, lower complexity, readable narration. |
| `BUILD` | Increase knowledge, stakes, pressure, or anticipation. | Escalating visual or audio change, tighter exclusions, accumulating evidence. |
| `PAUSE` | Create comprehension space or emotional contrast. | Hold, silence, room tone, sparse movement, or a longer shot. |
| `REVEAL` | Deliver a claim, fact, object, or consequence. | Evidence-led visual entry, caption emphasis, and optional restrained accent. |
| `PAYOFF` | Resolve or transform an earlier question. | Return to a setup, contrast before and after, or simplify the edit. |
| `RESET` | Prepare the next section. | Clear transition, change of visual grammar, or new orientation. |

A sequence should be evaluated for **information rhythm**, not only cut frequency. Automated metrics may include shot count, shot-duration distribution, silence intervals, caption density, visual novelty, repeated asset count, and beat-to-beat change. These are measurements, not quality scores. NarrativeOS must not convert them into synthetic claims of audience retention.

For long-form documentary work, the system should protect comprehension and evidence clarity before maximizing density. For short-form work, the system may front-load the proposition and vary visual or textual stimuli more frequently, but it must still preserve legibility and claim integrity.

## 4. Documentary editing

Documentary editing differs from generic montage because it must preserve factual meaning, source context, uncertainty, and ethical boundaries. NarrativeOS should distinguish:

- **Observed evidence:** the source visibly shows the claimed subject or action.
- **Illustrative material:** the image explains an idea but does not prove the specific claim.
- **Reconstruction:** the material represents a past event or interpretation and must be labeled where necessary.
- **Archival material:** historical source material whose date, origin, and rights must be recorded.
- **Atmospheric material:** mood-setting footage that must not be presented as direct evidence.

A documentary shot can be visually attractive and still be editorially wrong. The evidence layer must therefore remain independent of aesthetic scoring. A candidate is not approved merely because it has a strong composition or keyword overlap.

The documentary editing brain should assemble a sequence in passes:

1. **Meaning pass:** confirm the claim, source, and narration relationship.
2. **Structure pass:** order beats and remove material that does not advance the argument.
3. **Performance pass:** select the clearest and most truthful narration or interview moment.
4. **Picture pass:** assign evidence, illustrative, archival, and atmospheric visuals.
5. **Rhythm pass:** refine holds, cuts, pauses, and transitions.
6. **Sound pass:** clean dialogue, add room tone, design effects, and balance music.
7. **Graphics pass:** add maps, diagrams, labels, captions, and source notes.
8. **Ethics and QA pass:** inspect misleading juxtaposition, anachronism, unsupported implication, and rights status.

## 5. Sound effects, dialogue, ambience, and mixing

Sound is a structural editing layer. Adobe's professional audio guidance identifies synchronization, loudness matching, speech enhancement, music editing, and ducking as practical parts of a professional mix.[5] Adobe also separates dialogue, music, sound effects, and ambience as distinct categories for standard mixing tasks.[6]

NarrativeOS should model at least these buses:

```text
DIALOGUE
MUSIC
AMBIENCE
FOLEY
SFX
GRAPHICS_AUDIO
MASTER
```

Each sound event should record:

- semantic role;
- source asset and rights status;
- source interval;
- timeline start and end;
- gain envelope;
- fade-in and fade-out;
- ducking relationship;
- masking or priority relationship;
- synchronization target;
- QA status.

The sound brain should apply the following order:

1. Make speech intelligible.
2. Remove clicks, gaps, and abrupt room changes.
3. Restore or synthesize consistent room tone only when explicitly marked as treatment.
4. Place effects on visible or narrative events.
5. Shape music around the structure rather than laying it under the entire piece without automation.
6. Duck music and ambience when dialogue or a critical effect requires priority.
7. Normalize and inspect the master according to the selected delivery profile.

Sound effects should be event responses, not arbitrary decoration. A door closing, camera shutter, impact, riser, whoosh, or bass drop should have a target event and a reason. The system should reject SFX that are unlicensed, temporally detached from the picture, louder than dialogue without an intentional impact event, or used repetitively beyond the style profile.

For broadcast-style delivery, EBU R 128 is a reference point for loudness practice, including a programme target around -23 LUFS.[7] Platform-specific delivery profiles may use different targets. NarrativeOS must store the chosen profile and measure the rendered result instead of hard-coding one universal loudness number.

## 6. Music editing and building

Music should be represented as state changes rather than a single background file:

```text
ENTER → BUILD → SUSTAIN → DUCK → DROP → RESUME → EXIT
```

A music event should be able to respond to:

- a section boundary;
- a narration phrase;
- a reveal or payoff;
- a change in emotional intensity;
- a silence opportunity;
- a user revision;
- a measured beat or musical marker.

The music policy should define whether the track is allowed to compete with dialogue, whether the style permits rhythmic cuts, whether a drop is appropriate, and whether the source interval is licensed. Music should be cut or remixed to the narrative duration rather than stretched blindly. Any beat-based timing must be derived from actual audio analysis or explicit metadata, not invented BPM values.

## 7. Motion graphics and visual effects

Adobe's effects documentation separates fixed clip properties such as motion, opacity, time remapping, and volume from standard effects such as colour correction, blur, distortion, and other modifications. It also describes animating properties with keyframes and interpolation.[8]

NarrativeOS should expose a constrained operation vocabulary:

```text
TRANSFORM(position, scale, rotation)
OPACITY(fade, dissolve, overlay)
TIME_REMAP(speed, freeze, reverse)
MASK(shape, feather, tracking)
BLUR(amount, region)
COLOUR(exposure, contrast, saturation, temperature)
TEXT(enter, exit, emphasis, layout)
COMPOSITE(layer, blend_mode, matte)
DISTORT(glitch, displacement, lens)
CAMERA_PUSH(start_scale, end_scale, easing)
```

Effects should be selected by **event and style**, not by novelty. A serious documentary profile may map `EMPHASIZE` to a subtle push, crop, contrast adjustment, or caption emphasis. A high-energy short-form profile may permit a punch-in, impact sound, shake, and faster text response. The event remains the same; the recipe changes.

Every animated property requires:

- a start value;
- an end value or keyframe list;
- an easing function;
- a time range;
- a style-compatibility check;
- a render-backend capability check;
- a visual QA check.

NarrativeOS should not claim support for particles, advanced motion blur, 3D compositing, or optical-flow retiming until an actual renderer adapter and QA test exist.

## 8. Colour, graphics, captions, and accessibility

Colour work should be separated into correction and grading. Correction establishes consistent exposure, white balance, contrast, and skin or subject appearance. Grading applies a style look after the image is technically coherent. NarrativeOS should store colour-space assumptions, correction operations, grade recipe, and output profile.

Graphics must obey a hierarchy:

1. Information required to understand the claim.
2. Labels and source context.
3. Emphasis or explanation.
4. Decorative treatment.

Decorative graphics must not obscure evidence, captions, faces, or important action. Maps, diagrams, timelines, and callouts should have a source or construction rationale where they communicate factual content.

Captions should be generated from real narration alignment or explicit reviewed timings. The system should check:

- words per caption event;
- reading speed;
- line length;
- safe-zone position;
- contrast;
- speaker identification;
- overlap with graphics;
- synchronization with audio;
- language and translation consistency.

W3C guidance treats captions and other alternatives as part of access to synchronized media, and emphasizes that time-based alternatives must match the language and information of the original content.[9] Caption QA is therefore both a technical and editorial gate.

## 9. Platform profiles

Platform profiles should alter delivery and presentation constraints without changing the underlying claim ledger.

| Profile | Primary adaptations | Do not assume |
|---|---|---|
| `DOCUMENTARY_16_9` | Longer holds, evidence clarity, restrained effects, full context, readable lower thirds. | That every beat needs a cut or sound hit. |
| `YOUTUBE_LONGFORM` | Strong opening promise, chapter rhythm, thumbnail/title alignment, clear audio, 16:9 delivery. | That retention requires constant visual noise. |
| `SHORT_VERTICAL` | 9:16 composition, UI-safe text, early proposition, stronger visual variation, concise captions. | That TikTok's advertising guidance guarantees organic performance. |
| `REELS_VERTICAL` | Vertical reframing, mobile readability, short opening, platform-safe graphics. | That a horizontal crop preserves subject meaning. |
| `SHORT_HORIZONTAL` | Compact structure, fast orientation, strong opening image, caption clarity. | That short duration eliminates the need for evidence. |

Each profile must define aspect ratio, safe zones, minimum resolution, caption layout, title-safe margins, maximum text density, permitted effect intensity, audio profile, and render settings. YouTube's official guidance should drive export compatibility, while TikTok's official guidance should drive its platform-specific layout and creative checks.[3][4]

## 10. Event graph contract

The first implementation should use a JSON event graph with explicit references and deterministic compilation. A minimal event is:

```json
{
  "event_id": "EV_042",
  "type": "EVIDENCE_REVEAL",
  "status": "planned",
  "trigger": {
    "type": "voiceover_phrase",
    "value": "1986",
    "alignment_ref": "ALIGN_017"
  },
  "beat_id": "B012",
  "claim_id": "C042",
  "style_profile": "DOCUMENTARY_16_9",
  "actions": [
    {
      "type": "video_enter",
      "asset_id": "asset_017",
      "operation": "fade",
      "duration": 0.4
    },
    {
      "type": "motion",
      "operation": "camera_push",
      "from_scale": 1.02,
      "to_scale": 1.08,
      "duration": 4.2,
      "easing": "ease_in_out"
    },
    {
      "type": "audio_response",
      "operation": "duck_music",
      "amount_db": -4.0,
      "duration": 0.4
    }
  ],
  "constraints": [
    "claim_visual_link_must_pass",
    "asset_rights_must_be_verified",
    "asset_must_have_frame_evidence",
    "must_not_overlap_caption_safe_zone"
  ],
  "provenance": {
    "claim_id": "C042",
    "shot_id": "S012",
    "source_ids": ["SRC_004"],
    "decision_reason": "historical evidence appears when the year is spoken"
  }
}
```

The compiler should reject unknown action types, missing references, unsupported renderer operations, invalid time ranges, missing evidence, and style-incompatible recipes. It should output a deterministic Timeline IR plus a compilation report that explains every generated clip, audio event, graphic, and keyframe.

## 11. Constraint and QA engine

The QA engine should contain separate checks instead of one opaque score.

| Gate | Examples of real checks |
|---|---|
| Structural | JSON schema, unique IDs, valid references, deterministic ordering. |
| Timing | Non-negative ranges, no unintended overlaps, valid source intervals, sufficient handles. |
| Evidence | Real frame paths exist, frame count meets policy, visual analysis exists, action evidence exists where required. |
| Rights | Source URL, rights status, license or user-provided ownership record. |
| Narrative | Claim-to-shot links, beat coverage, no unsupported visual implication, continuity-bible consistency. |
| Audio | Dialogue stream exists, sample rate is known, loudness measured, clipping and silence inspected, ducking events applied. |
| Captions | Timings cover narration, safe zones, contrast, reading speed, no collisions with required graphics. |
| Render | Video and audio streams exist, duration is plausible, frame samples are readable, no black-frame or frozen-frame failures. |
| Delivery | Correct container, codec, aspect ratio, captions, manifest, hashes, tool versions, and release approval. |

Metrics should be reported as measurements or categorical findings. Examples include shot count, evidence-frame count, missing-artifact count, caption overlap count, loudness measurement, black-frame count, repeated-asset count, and unsupported-action count. The system must not invent audience-retention numbers or semantic similarity scores.

## 12. Implementation plan for the current repository

### Phase 1: event graph foundation

Add `schemas/editorial_event.schema.json`, `scripts/validate_event_graph.py`, and `scripts/compile_event_graph.py`. Introduce `editorial_event_graph.json` as a first-class artifact. Implement `REVEAL`, `EMPHASIZE`, `PAUSE`, `COMPARE`, and `TRANSITION` with deterministic validation.

### Phase 2: compiler integration

Compile approved events into the existing `timeline_ir.json` and `audio_events.json`. Preserve the current FFmpeg renderer as the execution backend. Add a compilation report that records event-to-operation mappings and renderer capability decisions.

### Phase 3: constraint propagation

Add ripple-safe retiming. When a shot changes, update dependent captions, audio events, markers, and subsequent track positions. Re-run timing, evidence, caption, and audio validators after every revision.

### Phase 4: documentary recipes

Create versioned recipes for serious reveal, evidence emphasis, reflective pause, archival comparison, and chapter transition. Recipes should define allowed operations, intensity ranges, audio responses, graphic rules, and prohibited effects.

### Phase 5: platform adaptation

Add platform profile manifests for 16:9 documentary, YouTube long-form, and vertical short-form. Use the same claim and evidence graph while producing separate composition and delivery plans.

### Phase 6: visual and audio QA

Add frame-sample inspection, caption raster inspection, loudness measurement, black-frame detection, freeze-frame detection, safe-zone checks, and a human review package. Keep any missing or unverified capability explicitly blocked.

### Phase 7: optional interchange

Only after the native event graph and Timeline IR are stable, add an OpenTimelineIO export adapter. OTIO should be an interchange target, not the source of narrative intent.

## 13. Proposed repository layout

```text
references/
  editing-brain.md
schemas/
  editorial_event.schema.json
scripts/
  validate_event_graph.py
  compile_event_graph.py
  validate_constraints.py
  inspect_render.py
style/
  recipes/
    documentary_serious.json
    documentary_reflective.json
    short_vertical_high_energy.json
```

## 14. What this research does not prove

This research does not prove that a particular editing formula produces viral performance. Platform guidance is often written for advertisers or general creators, and audience response varies by topic, audience, packaging, and distribution. It also does not prove that NarrativeOS currently implements the described capabilities. The repository remains evidence-gated: a proposed editing brain becomes implemented only after real artifacts, tests, renderer output, and QA evidence exist.

## References

[1]: https://www.adobe.com/creativecloud/video/post-production/cuts-in-film.html "Explore different types of cuts in film with Adobe Premiere"

[2]: https://opentimelineio.readthedocs.io/en/latest/tutorials/architecture.html "OpenTimelineIO Architecture"

[3]: https://ads.tiktok.com/resources/help/article/creative-best-practices?lang=en "TikTok Creative Best Practices for Performance Ads"

[4]: https://support.google.com/youtube/answer/1722171?hl=en "YouTube Recommended Upload Encoding Settings"

[5]: https://www.adobe.com/learn/premiere-pro/web/professional-audio-mix "Mix Audio Like a Pro"

[6]: https://helpx.adobe.com/audition/desktop/kb/editing-using-essential-sound-panel-audition.html "Deep Dive: The Essential Sound Panel in Adobe Audition"

[7]: https://tech.ebu.ch/groups/ploud-old "EBU Programme Loudness Recommendation R 128"

[8]: https://helpx.adobe.com/premiere/desktop/add-video-effects/types-of-effects/types-of-effects.html "Types of Effects in Adobe Premiere"

[9]: https://www.w3.org/WAI/WCAG21/Understanding/time-based-media.html "Understanding WCAG 2.1 Guideline 1.2: Time-Based Media"

[10]: https://documents.blackmagicdesign.com/UserManuals/DaVinci-Resolve-20-Editors-Guide.pdf?_v=1757574010000 "DaVinci Resolve 20 Editor's Guide"

[11]: https://support.google.com/youtube/answer/6375112?hl=en "YouTube Video Resolution and Aspect Ratios"

[12]: https://www.w3.org/WAI/WCAG21/Understanding/captions-prerecorded.html "Understanding Captions for Prerecorded Media"
