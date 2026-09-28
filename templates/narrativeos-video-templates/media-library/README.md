# Media Library

## Status: schema + two manually-verified metadata records. No live source adapter works yet.

Three metadata entries exist:
- `nasa_eileen_collins_001` — real, verified, **and bytes obtained**
  (via scikit-image's redistribution, not a live fetch).
- `nasa_hubble_deep_field_001` — same standard, real bytes, used as the
  second asset in the double-exposure proof.
- `wikimedia_alice_paul_1915` — real, verified metadata (cross-checked
  against multiple independent Commons category tags, not fabricated),
  but **`bytes_obtained: false`** — see below.
- `test_fixture_cockatoo_720p20` — a real video, but explicitly
  `rights_verified: false` and `status: engineering_test_fixture_only`.
  No rights statement exists anywhere in its source repository for this
  specific file, unlike its individually-credited sibling assets.
  **Never treat this as documentary content** — it exists only to test
  `archive_video`'s handling of a real 20fps source with a real (if
  near-silent) audio track. See `references/archive-video-hardening.md`.

`tools/probe_asset.py` runs real `ffprobe` against a video file and
produces the technical facts (`source_fps`, `real_source_frame_count`,
`has_audio`, aspect ratio) that populate an asset's `technical_probe`
field — this has to happen at ingestion time, outside Remotion, since a
React component can't shell out to ffprobe. Run and verified against the
test fixture above; not yet wired into any live source adapter.

## Internet Archive Adapter v0 (`tools/internet_archive_adapter.py`)

The first source adapter with a real, tested, working pipeline —
`SEARCHED -> CANDIDATE -> RIGHTS_VERIFIED -> DOWNLOADABLE -> BYTE_VERIFIED
-> REGISTERED`, refusing to advance past any stage the evidence doesn't
support. `licenseurl:*publicdomain*` is treated as a search constraint
that narrows candidates, never as a blanket per-source trust claim —
every candidate still gets its own item-level rights check against its
own metadata record, independent of the search filter that surfaced it.

**What's real and tested, with evidence:**
- `archive.org/advancedsearch.php` (search) and `archive.org/details/*`
  (item pages) are reachable via `web_fetch` and return real, live data —
  confirmed against a real item, `1957-10-07_New_Moon` ("New Moon. Reds
  Launch First Space Satellite," a Universal Newsreels clip about
  Sputnik's launch). Its metadata page states an explicit
  `licenseurl: http://creativecommons.org/licenses/publicdomain/`,
  independently cross-confirmed by Wikimedia Commons's own mirror of the
  same file (matching duration, resolution, and format specs from a
  completely separate source — not a single unverified claim).
- The adapter's rights/availability decision logic (`_verify_rights_from_metadata`)
  is exercised by a real offline self-test built from those genuinely
  observed field values: correctly advances a rights-and-file-bearing
  item to `DOWNLOADABLE`, correctly leaves a no-`licenseurl` item stuck
  at `CANDIDATE`, and `register()` correctly refuses to register
  anything short of `BYTE_VERIFIED` — all three checked by running the
  code, not just reasoning about it.

**What's honestly blocked, and precisely why — this is a different, more
specific finding than the earlier NASA/Wikimedia blockers:** the actual
byte-download step could not be completed in the sandbox this was built
in. Two separate, precise causes, not one vague "archive.org doesn't
work":
1. `bash_tool`'s network egress explicitly refuses the domain —
   confirmed via the proxy's own response: `x-deny-reason: host_not_allowed`,
   *"Host not in allowlist: archive.org."* This is sandbox
   configuration, fixable by adding the host to that allowlist.
2. `web_fetch` (a separate tool, not bound by that allowlist) genuinely
   reaches the real download URL — confirmed: it resolves to a real
   Internet Archive CDN node (`dn711004.ca.archive.org`) and correctly
   reports the real `video/ogg` mime type — but returns a `[binary data]`
   placeholder rather than usable bytes. **This is not a size or
   binary-content issue** — confirmed by separately fetching a 1KB
   plain-text `_meta.xml` file from the same CDN datanode, which
   returned the identical placeholder. The limitation is specifically
   about content served via redirect to an `*.archive.org` CDN datanode
   subdomain, regardless of what that content actually is.

Neither of these is a defect in Internet Archive, in rights verification,
or in the adapter's logic — both are this specific sandbox's tooling
limits. The download/checksum/probe code in the adapter is ordinary,
correct Python that should work in any environment with normal outbound
HTTPS access; it just wasn't exercisable end-to-end here. See
`metadata/ia_1957-10-07_new_moon.json` for the real record, held
honestly at `pipeline_status: DOWNLOADABLE` — not `REGISTERED`, because
it hasn't earned that yet.

**Reachability-from-this-sandbox is a separate axis from rights-verification
difficulty, and the two shouldn't be conflated.** A source can be low-risk
on rights and still be blocked purely by network access in a given
environment:

- **NASA** (`images-api.nasa.gov`) — real, documented, no API key required
  for search. Tested three times with varying query encoding: every
  attempt returned HTTP 400 from this environment's `web_fetch`.
- **Wikimedia** (`commons.wikimedia.org/w/api.php`) — real, documented,
  extensively used in the wild (Openverse, countless tools reference it).
  Every fetch attempt — including URLs copied verbatim from search
  results, not constructed — returned "this domain is cache-only" from
  this environment's `web_fetch`.

Both are genuinely low-risk sources on the rights-verification tier below.
Both are currently unreachable live from this specific sandbox. A real
production server without these sandbox-specific network restrictions
would very likely reach both fine — don't read "blocked here" as "hard to
build," they're different claims. But don't assume either adapter works
without re-testing in whatever environment actually runs it.

**The general principle this surfaced, worth keeping explicit:** these are
five separate, independently-failable things, not one:

```
provider availability  ≠  API availability  ≠  metadata availability
                        ≠  media-byte availability  ≠  rights verification
```

NASA and Wikimedia both cleared "provider exists" and "rights model is
tractable." NASA failed at "API availability" (HTTP 400). Wikimedia
cleared "API availability" in principle (real, documented, widely used)
but failed at "media-byte availability" from this environment
specifically (cache-only fetch restriction) while still clearing
"metadata availability" (real, cited fields, just no pixels). Treat each
of the five as its own checkbox for any future source — don't infer one
from another.

## The ingestion pipeline (what "Media Library" actually means)

A source adapter is not just "code that downloads a file." Every asset has
to pass through the same four steps before it's usable, in this order:

1. **Fetch** — from a source adapter (`source/nasa/`, `source/wikimedia/`, etc).
2. **Verify rights** — see the risk tiers below. This step can say no.
3. **Auto-tag** — `visual_tags` and `usable_as` don't appear by magic; this
   is a captioning/tagging pass (a vision model describing the image) run
   at ingestion time. Not built yet — the one real entry above was tagged
   manually as a stand-in, and that doesn't scale past a handful of assets.
4. **Store** — `processed/<id>.jpg` + `metadata/<id>.json`, only after 2 and 3
   both succeed. Nothing skips the rights check to get stored provisionally.

## Source adapter risk tiers — these are not equivalent difficulty

- **Tier 1 (build first): NASA, Wikimedia.** Both expose structured,
  machine-readable license fields via their own APIs. A blanket
  source-level policy ("if it's from NASA's own API and flagged public
  domain, trust it") is defensible. Wikimedia's real field names, for
  whoever builds this adapter once reachability is sorted: `extmetadata`
  on the `imageinfo` API property gives `Artist`, `LicenseShortName`,
  `LicenseUrl`, `Categories`, `DateTimeOriginal`, `Credit` — map these into
  this schema's `creator`, `license`, `license_note`, `topics`, `subject`
  fields respectively. Confirmed via Wikimedia's own
  Commons:Machine-readable_data and Extension:CommonsMetadata
  documentation, not guessed.
- **Tier 2 (build later, per-item logic required): Internet Archive.**
  This is a preservation archive, not a rights-cleared library. A large
  fraction of what's in it is archived for preservation, not cleared for
  reuse. Do not apply a blanket "source == Internet Archive therefore
  public domain" rule — each item's actual rights statement has to be
  checked individually. Treating this the same as NASA/Wikimedia is the
  most likely way `rights_verified: true` ends up wrong.
- **Tier 3: government, licensed.** "Government" varies by country and
  agency — not all government-produced material is public domain outside
  the U.S. federal case. "Licensed" (the user's own purchased stock/footage)
  is rights-clear by definition but needs its own provenance record (what
  was purchased, what the license terms actually permit) rather than being
  treated as equivalent to public domain.

## Fallback policy — the gap in the original design, now made explicit

`Media Requirements → asset lookup` assumes a matching asset already
exists. Most of the time, for most documentary topics, it won't. Do not let
the system silently substitute a loosely-related asset and call it a match
— that's a worse failure than an obvious gap, because it's invisible in the
output. The lookup needs an explicit three-way result, not a boolean
found/not-found:

- **Exact or near-exact subject match** → use it.
- **Category-level match** (no "Eileen Collins" photo, but a
  "1990s NASA astronaut portrait, public domain" exists) → usable, but the
  asset record and the render's own provenance log should note it was a
  category substitution, not an exact match, so this is auditable later.
- **No usable match** → do not substitute silently. Surface the gap
  (flag for manual sourcing, or let the Director Brain choose a different
  editorial treatment that doesn't need this specific asset) rather than
  grabbing whatever image search returns.

## Asset record schema

See `metadata/nasa_eileen_collins_001.json` for a real filled example.
Required fields: `id`, `type`, `source`, `license`, `source_url`,
`rights_verified`, `rights_verification_method`, `topics`, `visual_tags`,
`usable_as`, `local_path`. `rights_verification_method` matters as much as
`rights_verified` itself — "manual" vs. "automated via source API" are very
different confidence levels and both should be visible, not collapsed into
a single boolean.
