# NarrativeOS

### A video production system that AI agents can operate.

**NarrativeOS is being built so any capable AI agent can take a topic, brief, script, voiceover, reference video, or raw footage through a repeatable production process to a finished, reviewable video.**

The system holds the production methods, reusable tools, editing knowledge, project state, and quality checks. The AI operates those capabilities: it understands the brief, makes creative proposals, runs the tools, inspects the results, and revises the work. A new agent should be able to resume from the project's files without inheriting the previous agent's conversation.

The ambition is professional editing and motion design: deliberate storytelling, well-chosen pictures, readable typography, purposeful movement, considered sound, and a consistent visual identity. Adding effects is not a substitute for making an editorial decision.

> **Current state: active development.** NarrativeOS has working production tools, a persistent stage controller, a multi-track renderer, reference-analysis tools, specialist workflows, and a live review interface. These pieces are not yet a universal, unattended brief-to-video application. Some production paths still need an agent to connect tools, prepare artifacts, configure providers, and obtain review.

[Start as an AI agent](#start-as-an-ai-agent) · [Capabilities](#what-exists-today) · [Setup](#local-setup) · [Workflow](#how-production-works) · [Documentation](#documentation-map)

Canonical repository: [Hxtra/NarrativeOS](https://github.com/Hxtra/NarrativeOS).

**Development branch:** the capabilities described below reflect work on [departments-analysis](https://github.com/Hxtra/NarrativeOS/tree/departments-analysis), including work still in progress. The default branch may contain an earlier implementation. Where a linked document has not reached `main`, its link opens the development branch.

## What NarrativeOS is for

NarrativeOS is a general-purpose production system. Documentary is the first deeply developed workflow, with additional tools for talking-head editing, voiceover-and-footage edits, short-form captions, reference-driven styles, and custom explainer scenes.

The intended input and output are:

```text
Topic / brief / script / voiceover / footage / reference
                          |
                   NarrativeOS
        Plan -> Produce -> Edit -> Inspect -> Revise
                          |
       Finished video + editable production artifacts
```

A documentary may need sources, claims, archival footage, maps, and narration. A talking-head edit may need take selection, pause removal, reframing, captions, and restrained graphics. A reference-driven short may need measured pacing, typography, colour, and sound. These are different production routes through a shared engine; complete automatic routing between them is still a development goal.

### The division of responsibility

| Part | Responsibility |
|---|---|
| Human producer | Sets intent, supplies or chooses references, gives feedback, and makes required creative, spending, and release decisions. |
| AI operator | Interprets the request, chooses the applicable workflow, uses existing tools, proposes decisions, inspects outputs, and handles revisions. |
| NarrativeOS | Stores project truth, provides production capabilities and contracts, records evidence and versions, validates supported operations, and renders outputs. |
| Providers and backends | Supply specific services such as reasoning, speech, analysis, generation, or rendering through configured integrations. |

“Any AI” means a capable agent with access to the repository, project files, and tools. It does not mean every model can perform every task, or that all integrations work without configuration. Claude Code, Codex, Hermes, and other agents should share the same production artifacts and rules. Older documents still describe NarrativeOS as a Hermes workflow; the product direction is a standalone system with an agent-facing control layer.

## Start as an AI agent

**Read this section before choosing tools or creating a project.**

1. **Understand the request.** Establish the audience, purpose, approximate duration, format, available footage or narration, references, channel identity, and spending constraints. Reuse answers already supplied by the user.
2. **Read the operating contract:** [SKILL.md](SKILL.md). Then read [CLAUDE.md](CLAUDE.md) for accumulated project decisions and implementation history. Despite its filename, that context matters to every agent. Its dated sections contain historical limitations; verify present behaviour against the relevant code and tests.
3. **Inspect before starting over.** For an existing production, read its brief, configuration, state, event log, latest timeline, review findings, and local project notes. Determine which artifacts are current and which are stale.
4. **Discover capabilities.** Use the catalog, then read the relevant command's `--help`, specialist skill, and contract. A catalog entry is a discovery aid; inspect its status and evidence before relying on it.
5. **Choose the production route.** Use the guide below. Reuse registered templates and established methods before building a new tool or scene implementation.
6. **Work in inspectable steps.** Produce real artifacts, run the relevant validators, render previews, inspect frames, listen to audio, and record decisions. Advance the controller only when the applicable stage requirements are satisfied.
7. **Leave a resumable production.** Record what changed, the latest output, unresolved findings, approvals, and the concrete next action in the project. Do not make the next agent reconstruct the work from chat history.

Useful discovery commands, run from the repository root:

```powershell
python scripts/catalog.py list capabilities
python scripts/catalog.py list studies
python scripts/catalog.py show script.compile_timeline
python scripts/controller.py --help
```

### Choose a route

| Request | Start here | Important boundary |
|---|---|---|
| Sourced documentary or explainer | [Explainer-film workflow](https://github.com/Hxtra/NarrativeOS/blob/departments-analysis/skills/narrativeos-explainer-film/SKILL.md), root production contract, and `scripts/visual_strategy.py` | Sources, visual evidence, and rights must support factual scenes. |
| Edit talking-head footage | [Talking-head guide](references/talking-head.md), `scripts/talking_head.py` | Review take choices, speech cuts, crops, and caption placement on actual footage. |
| Adapt an approved reference style | [Watch-reference workflow](https://github.com/Hxtra/NarrativeOS/blob/departments-analysis/skills/narrativeos-watch-reference/SKILL.md), [Signatures](references/signatures.md) | Measure the selected reference; check whether its edit type is supported by the apply path. |
| Produce narration | [Voiceover workflow](https://github.com/Hxtra/NarrativeOS/blob/departments-analysis/skills/narrativeos-voiceover/SKILL.md) | Confirm voice, provider, consent, and any required cost approval before generation. |
| Design or mix sound | [Sound-design workflow](https://github.com/Hxtra/NarrativeOS/blob/departments-analysis/skills/narrativeos-sound-design/SKILL.md) | Listen to the result; measurements alone do not establish editorial quality. |
| Add graphics or transitions | [Template registry and instructions](templates/narrativeos-video-templates/SKILL.md) | Look up a registered component and its parameters before writing a new one. |
| Render an existing timeline | [Timeline compiler](references/timeline-compiler.md), `scripts/compile_timeline.py` | Validate assets, source intervals, timeline structure, and render warnings. |
| Review or revise a production | [Studio](timeline-editor/README.md), `scripts/edit_patch.py`, controller graph | Preserve approved artifacts and rerun gates affected by changes. |

These are entry points, not a claim that every route is fully automated. Use each workflow's current instructions for its inputs and limitations.

### Example instruction for a new agent

> Use NarrativeOS to produce this video. Read README.md and SKILL.md, inspect the applicable context in CLAUDE.md, and discover the existing tools before building anything new. Keep project data outside the source repository. Maintain durable production state, use real evidence and rights records where required, inspect rendered frames and audio, and report concrete blockers. Preserve the work so another agent can resume it.

## How production works

The production logic follows editorial intent through to verifiable output:

```text
Brief and constraints
        |
Story, research, and creative direction
        |
Narration, beats, and visual purpose
        |
Media, rights, continuity, and shot decisions
        |
Timeline, graphics, captions, and sound
        |
Preview -> Technical and editorial review -> Repair
        |
Final render and delivery review
        |
Optional, explicitly authorized publishing
```

The current controller defines a more detailed, predominantly documentary-oriented sequence in [scripts/controller.py](scripts/controller.py). It includes intake, style lock, quoting, research, evidence review, scripting, shot planning, acquisition, approval, timeline construction, rendering, QA, revision, and delivery. The authoritative stage names, dependencies, required artifacts, and implemented checks live in that file.

**The controller is a state and validation gate.** Running it checks the current stage's artifacts and dependencies, records the result, and advances after a pass. It does not automatically invoke all the producers needed to create those artifacts. The operating agent must currently orchestrate much of that work.

The controller stores:

| Artifact | Purpose |
|---|---|
| `state.json` | Current stage, completed stages, blockers, and delivery state. |
| `events.jsonl` | Append-only production activity. |
| `errors.jsonl` | Recorded validation failures. |
| `production_graph.json` | Graph snapshot produced by `--graph`. |
| Stage artifact hashes | Detect changes to previously passed artifacts and dependencies. |

Pausing, revising a stage, and detecting stale work are supported. A revised upstream decision can reopen downstream work rather than leave a previous pass silently valid.

### A scene needs a reason to look the way it does

Visual choices should follow the story and the material available. Use footage when it shows the event, a document when the document matters, a map when the viewer needs geography, and an illustration or diagram when it communicates something that cannot be filmed. Reconstruction must be recognizable as reconstruction.

Channel profiles carry persistent identity. Scene-level choices vary within that identity. AVEN is one channel used to exercise these capabilities; its palette, voice, and documentary preferences are channel data, not universal NarrativeOS defaults.

### Reference learning is grounded in the media

Reference analysis studies picture, editing, motion, text, speech, music, effects, and their timing. A written description is an index into the evidence; the actual frames, clips, audio, and measurements preserve the detail.

Findings distinguish:

- **MEASURED:** a tool produced a value, with a defined method and limits.
- **OBSERVED:** a reviewer saw or heard a feature in the actual media.
- **INFERRED:** an interpretation supported by evidence, still subject to review.
- **NOT_MEASURED:** the system did not establish the property.

Models can propose interpretations and edits. Rendering, comparison, listening, and review establish whether the result works. An effect detector or similarity score is not complete understanding of a video.

## What exists today

The table describes the implementation surface, not a fresh certification of every feature. Use the linked documents, capability records, and relevant tests for detailed status.

| Area | Existing capability | Current qualification |
|---|---|---|
| Production state | Stage controller, event logs, hashes, pause/resume, revision, stale detection | Producer orchestration remains partly agent-driven; validators differ in depth by stage. |
| Research and story | Research workspace, claims, contradiction checks, Director strategy, beat and shot planning | External research and substantive factual review require real sources and configured tools or operator work. |
| Visual strategy | Scene-level media/register choices, evidence and rights gates | These decisions need actual research and media evidence; a manifest cannot supply them by itself. |
| Reference intelligence | Style DNA, effects/text breakdown, motion and audio analysis, shot logs, comparison | Each analyzer has limits; measured properties and inferred labels must remain distinct. |
| Editorial decisions | Rule-based Director, event graph, optional model-assisted proposals, typed edit patches | A validated proposal still needs appropriate rendering and editorial review. |
| Talking-head and voiceover edits | Take selection, trimming, reframing, timed captions, supported Signature application | Coverage varies by edit type; inspect crops, source windows, and speech continuity. |
| Motion design | Registered Remotion templates, shared primitives, StyleProfiles, VFX recipes | The compiler can composite graphics and recipe segments; automatic selection through the controller's `GRAPHICS` producer remains incomplete. |
| Timeline and rendering | IR 3.0 multi-track FFmpeg compiler, transitions, overlays, native audio, captions, grading, speed controls | Optional graphics require their backend. Inspect unsupported or unrendered operations and unresolved sound cues. |
| Voice and sound | Voiceover tools, alignment, sound-design planning, mixing, provider bridges | Dependencies, credentials, provider limits, rights, and listening review apply. |
| Review interface | Studio graph, timeline, previews, evidence views, validated patch proposals, versions and undo | Studio is a layer over production artifacts; its editor does not replace delivery approval. |
| Memory and identity | Versioned channel profiles, pinned project profiles, creative decisions, Signatures, study catalog | Feedback does not silently become a universal rule. Promotion and validation have explicit requirements. |
| Generation | Job states, cost/rights gates, provider metadata, continuity references | Availability is provider-specific. AI video generation remains disabled by default. |
| Delivery and publishing | QA, provenance, delivery review, release packaging, YouTube dry run | Real publishing needs provider setup and an explicit release decision. |

The capability catalog uses labels such as `DOCUMENTED`, `IMPLEMENTED`, `TESTED`, `VALIDATED`, and `BLOCKED`. Their scope matters: a tested component does not prove an entire autonomous production path.

## Local setup

NarrativeOS currently runs from the source tree. There is no single complete installer or universal `narrativeos make-video` command. Install dependencies for the workflow you intend to use.

### Core tools

- Python for the controller and production scripts.
- FFmpeg and FFprobe on `PATH` for media processing, rendering, and verification. Caption rendering needs an FFmpeg build with the relevant subtitle support.
- Workflow-specific Python packages. There is no root dependency file covering every subsystem.
- Node.js and npm when using the Remotion graphics backend.
- Provider credentials or local models only for the features that require them.

Check the basic environment:

```powershell
python --version
ffmpeg -version
ffprobe -version
python scripts/controller.py --help
```

### Data and configuration

Keep source code and reusable knowledge in this repository. Keep production media, channel data, credentials, models, and generated outputs in a separate data directory.

The intended shared setting is `NARRATIVEOS_HOME`, conventionally `~/NarrativeOS-Data`. Migration from older per-tool locations is incomplete; check the tool's documented defaults and explicit path arguments. Setting this variable alone does not guarantee every older script uses it.

For example, in PowerShell:

```powershell
$env:NARRATIVEOS_HOME = Join-Path $HOME "NarrativeOS-Data"
```

The intended data layout is:

```text
NarrativeOS-Data/
  projects/       Briefs, production artifacts, media, previews, and final renders
  channels/       Versioned channel identities and creative decisions
  signatures/     Reference-derived editing styles
  analysis/       Reference frames, measurements, stems, and review sheets
  knowledge/      Evidence-backed production lessons
  memory/         Visual exemplars and concept-memory data as developed
  vfx-library/    Local overlays and their provenance
  models/         Downloaded analysis models
  tools/          Local external tools where applicable
  secrets/        Private credentials; never packaged or committed
```

This is an organizational convention, not an assertion that every directory is automatically created. [.env.example](.env.example) documents some integration settings; it is not a complete provider configuration or a promise that scripts automatically load `.env` files.

### Optional subsystems

| Subsystem | Setup entry point |
|---|---|
| Reference analysis | [Style Intelligence guide](style_intel/README.md) and [requirements](style_intel/requirements.txt). Read the optional OCR/model notes before installing overlapping OpenCV packages. |
| Remotion graphics | In `templates/narrativeos-video-templates/project`, run `npm install`, then `npm run typecheck`. Read the companion skill before rendering or changing templates. |
| Studio | Install [timeline-editor/requirements.txt](timeline-editor/requirements.txt), then follow [the Studio guide](timeline-editor/README.md). |
| Frame-awareness models | `python scripts/vision_models.py --help` and [frame-awareness guide](references/frame-awareness.md). |
| Voice, audio analysis, or generation | Read the applicable specialist skill and provider instructions; these have additional packages, models, or credentials. |

## Operating a local project

The commands below illustrate existing interfaces. They do not constitute an automatic end-to-end production recipe. Run them from the repository root after setting `NARRATIVEOS_HOME` as above.

### 1. Initialize a new production

Select a **new** project directory:

```powershell
$project = Join-Path $env:NARRATIVEOS_HOME "projects/my-first-video"
python scripts/controller.py --project "$project" --init
```

Run `--init` only for a new production: it writes initial controller state. For an existing project, inspect and resume its current state instead.

Initialization creates folders, initial state, and a small set of default artifacts. It does not write your brief or complete the production configuration. Supply `brief.md` and `project.yaml`; [examples/minimal_project/project.yaml](examples/minimal_project/project.yaml) is a minimal configuration example, not a finished production. Configure the channel/style using [channel operations](references/channel-operations.md) where applicable.

### 2. Inspect and advance the workflow

```powershell
python scripts/controller.py --project "$project" --graph
python scripts/controller.py --project "$project"
```

The second command attempts one validation step. If it blocks, inspect `state.json`, the reported requirements, and the relevant stage producer. Create or repair the real inputs and artifacts, then retry. Creating a file or changing a status label is not a substitute for doing the stage's work.

### 3. Validate and render a prepared timeline

For a project that already contains a valid IR 3.0 timeline and approved media:

```powershell
python scripts/compile_timeline.py --project "$project" --timeline timeline_v3.json --validate-only
python scripts/compile_timeline.py --project "$project" --timeline timeline_v3.json --preview
```

The compiler writes a preview and render manifest. Inspect the actual video and audio as well as warnings, verification results, unrendered operations, and unresolved cues. A successful encode does not establish factual accuracy, visual relevance, or editorial quality.

For a final encode from fully approved assets:

```powershell
python scripts/compile_timeline.py --project "$project" --timeline timeline_v3.json --release --output renders/final.mp4
```

`--release` tightens asset approval requirements. It does not replace the separate delivery review, all other QA, or publishing authorization.

### 4. Review and revise

Open Studio on a directory containing projects:

```powershell
python timeline-editor/run_studio.py --projects "$env:NARRATIVEOS_HOME/projects" --no-browser
```

Open the local address printed by the server. Studio exposes the production graph, timeline, preview, and revision proposals. See its guide for Apply, undo, and version behaviour.

To reopen a controller stage after a production decision changes:

```powershell
python scripts/controller.py --project "$project" --revise SHOT_PLAN --reason "Visual coverage changed after review"
```

This reopens affected stage passes; the operator still performs the required repair and reruns validation.

### Structural simulation

For a separate integration exercise:

```powershell
python scripts/simulate_documentary.py --project "$env:NARRATIVEOS_HOME/projects/structural-simulation"
```

The simulation connects planning artifacts with structural fixtures. Its report deliberately says `production_ready: false`. It is not a real-media production demonstration or a deliverable video.

## Production rules

These principles apply across agents and workflows. The detailed contracts remain in [SKILL.md](SKILL.md), schemas, and subsystem instructions.

- **Use relevant media.** Filenames, search titles, technical metadata, or a single thumbnail cannot establish that a clip shows the intended subject or action. Inspect actual media and the selected source interval.
- **Preserve provenance and rights.** Keep sources, checksums, usable intervals, credits, and rights decisions with the assets. A reachable URL is not a license. A downloaded file is not automatically approved media.
- **Keep factual and illustrative material distinct.** Generated or reconstructed pictures never become documentary evidence. Label theories, viewer stories, and reconstructions appropriately.
- **Make cost and release decisions explicit.** Follow quote and approval requirements before billable work. Publishing needs an explicit release decision and provider-specific setup.
- **Treat output inspection as production work.** Look at rendered frames, check transitions and crops, read captions at delivery size, and listen to the mix. Record what was actually checked.
- **Preserve revisions.** Keep approved artifacts, version changes, record reasons, and recheck downstream work when upstream inputs change.
- **Report blockers truthfully.** Distinguish unavailable providers, missing media, unknown rights, unsupported operations, failed validation, and required review. Never claim success from a placeholder or simulation.
- **Make each production improve the system.** Generalize reusable tools, document evidence-backed lessons, and add appropriate verification. Keep private project media and credentials outside the reusable package.

### Delivery means more than an MP4

A reviewed production should preserve the final media, editable timeline, script/transcript, caption files where applicable, asset and rights records, provenance, render/QA reports, relevant hashes and tool versions, and required approvals. Required coverage depends on the production; the documentary delivery contract is defined in the root skill and delivery tools.

Do not describe a production as ready merely because a video file exists or one technical check passed.

## Architecture and repository map

The architecture separates creative reasoning from durable state and deterministic execution:

```text
Human brief and feedback <-> AI operator
                                |
                  Skills, catalog, production contracts
                                |
             Project state, evidence, and editorial decisions
                                |
             Production tools -> Timeline IR -> Compiler
                                                |
                        FFmpeg + optional graphics backends
                                                |
                              Preview -> Review -> Delivery
```

FFmpeg is the primary timeline compiler/render path. Registered Remotion components provide graphics and VFX segments for compositing. HyperFrames is an optional adapter; reconstruction and experimental scene workflows use other tools where documented. No external renderer owns NarrativeOS's project truth.

The current reasoning-provider abstraction accepts command-based or callable integrations for supported editorial proposal tasks. It does not yet provide a universal provider interface for every production department.

| Path | Contents |
|---|---|
| [SKILL.md](SKILL.md) | Root agent operating contract and detailed production graph. |
| [CLAUDE.md](CLAUDE.md) | Historical handoff, owner decisions, implementation notes, and known issues. |
| [scripts/](scripts/) | Controller, planning, media, editing, rendering, QA, and provider tools. |
| [schemas/](schemas/) | Structured artifact contracts. |
| [skills/](https://github.com/Hxtra/NarrativeOS/tree/departments-analysis/skills/) | Specialist reference-study, voiceover, sound-design, and explainer workflows. |
| [style_intel/](style_intel/) | Reference-video measurement, breakdown, motion, sound, and comparison. |
| [templates/narrativeos-video-templates/](templates/narrativeos-video-templates/) | Graphics registry, StyleProfiles, shared primitives, VFX and media-library tooling. |
| [timeline-editor/](timeline-editor/) | Artifact APIs, Studio, and timeline review interfaces. |
| [reconstruct/](https://github.com/Hxtra/NarrativeOS/tree/departments-analysis/reconstruct/) | Reference reconstruction, source/layer matching, and backend experiments. |
| [catalog/](https://github.com/Hxtra/NarrativeOS/tree/departments-analysis/catalog/) | Machine-readable capabilities, reference studies, and third-party inventory. |
| [references/](references/) | Architecture, implementation guides, audits, and roadmaps. |
| [tests/](tests/) | Component, contract, regression, and render tests. |
| [examples/](examples/) | Minimal example configuration. |

## What still needs to become production-grade

The next step is connecting the existing capabilities into a coherent operating system for production:

1. **One agent-facing entry point:** intake, capability discovery, environment checks, project creation, status, next action, and resume.
2. **Executable workflow routes:** supported paths for different video types, with explicit required inputs, producers, gates, and completion criteria.
3. **Reliable orchestration and recovery:** tool execution, classified failures, bounded retries, clear repair actions, and safe resumption. Specialized production and recovery roles are part of the intended design.
4. **Consistent contracts and documentation:** reconcile older timelines, per-tool paths, provider assumptions, and dated status claims so agents do not need to reconstruct the architecture.
5. **Complete quality loops:** verify pictures, story, timing, sound, and reference fidelity on representative real productions; report what automated checks cannot establish.
6. **Portable setup:** reproducible dependencies, provider configuration, model availability, and separation of source from production data.

**The practical acceptance test:** a fresh capable agent, without previous conversation history, can follow the documented entry point, produce a short real video with appropriate rights and evidence, inspect and revise it, deliver the production artifacts, and leave it resumable by a different agent. Any manual bridge exposed by that test becomes a concrete system improvement.

Longer-term goals include broader production profiles, richer editing knowledge and visual concept memory, more capable native compositing, and increasingly autonomous production. These are product direction, not claims of completed features.

## Development and verification

Before extending a capability, inspect the catalog, existing scripts, specialist skill, and relevant tests. Prefer improving a shared tool over leaving another production-specific implementation behind.

Match verification to the change. Contract tests establish structure; rendered-frame and audio checks establish output behaviour; human editorial review evaluates decisions that numerical checks do not settle.

Useful maintenance commands:

```powershell
python scripts/catalog.py check
python -m pytest tests/test_catalog.py
```

When deliberately adding or changing cataloged capabilities, `python scripts/catalog.py scan` refreshes the capability inventory and preserves curated entries. Run relevant subsystem tests and inspect render outputs where applicable. A passing catalog check or typecheck is not proof of video quality.

Third-party tools, models, services, assets, and their recorded license/status information are tracked in [catalog/third_party.json](https://github.com/Hxtra/NarrativeOS/blob/departments-analysis/catalog/third_party.json). Respect their individual licenses and provenance requirements. Credentials, licensed media, reference footage, generated production assets, and private machine paths do not belong in the public package.

## Documentation map

| Need | Read |
|---|---|
| Operate NarrativeOS as an agent | [Root skill](SKILL.md) and relevant context in [CLAUDE.md](CLAUDE.md) |
| Understand artifact and evidence contracts | [Architecture](references/architecture.md) |
| Render, validate, and composite a timeline | [Timeline compiler](references/timeline-compiler.md) |
| Understand editing decisions and implementation boundaries | [Editing brain](references/editing-brain.md) and [implementation audit](references/editing-brain-implementation-audit.md) |
| Plan narration and visual coverage | [Narration and coverage](references/narration-and-visual-coverage.md) |
| Study a reference | [Watch-reference skill](https://github.com/Hxtra/NarrativeOS/blob/departments-analysis/skills/narrativeos-watch-reference/SKILL.md) and [Style Intelligence](style_intel/README.md) |
| Reuse a reference-derived editing style | [Signatures](references/signatures.md) |
| Edit speakers and reframe footage | [Talking-head](references/talking-head.md) and [frame awareness](references/frame-awareness.md) |
| Understand music, speech, and timing analysis | [Perception and rhythm](references/perception-and-rhythm.md) |
| Work with channel identity and creative memory | [Channel operations](references/channel-operations.md) |
| Use generation jobs and their gates | [Generative media](references/generative-media.md) |
| Build registered motion graphics | [Template skill](templates/narrativeos-video-templates/SKILL.md) |
| Review a project in Studio | [Timeline editor and Studio](timeline-editor/README.md) |
| Understand reference reconstruction research | [Deep understanding](https://github.com/Hxtra/NarrativeOS/blob/departments-analysis/references/deep-understanding.md) |
| Inspect the longer implementation plan | [Roadmap v2](references/implementation-roadmap-v2.md); read alongside newer code and subsystem guides |
