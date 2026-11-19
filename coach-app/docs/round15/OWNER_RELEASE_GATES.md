# Round 15 — owner-defined release gate (NOT a feature wishlist)

Status: **BLOCKED / awaiting actual Windows owner acceptance**.

This document records the product constraints made explicit after the failed Round 14.5 real Windows test. Authoritative feedback and superseding clarification are in the PR #64 conversation:
- Initial owner failure report: https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/64#issuecomment-7017285835
- Design reset: https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/64#issuecomment-7017398531
- Rejected Tactical Peek and renewed approval for **small simultaneous inset 2D**: https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/64#issuecomment-7017550211

**Current visual direction**: HD 3D dominates the screen, with a reasonably small, legible **upper-right** simultaneous top-down positioning map within the HD viewport. The map shows all four players and ball, not a giant field overlay, a forced 50/50 split, or a same-time perspective toggle. The exact size, car visibility, and placement must be approved against real replay footage. Never claim a corner map has been approved solely because it is smaller than before.

## Release-blocking acceptance cases

| Gate | Mandatory actual user-visible behavior | Evidence required | Rejection / no silent fallback |
| --- | --- | --- | --- |
| G01 First real replay | From a fresh browser session, ONE uploaded real 2v2 replay decodes, displays four players and **plays in HD 3D immediately** | One first-load browser video + exact code revision | Cannot depend on a second Tactical 2D upload or another mode to initialize |
| G02 Single clock | One authoritative seek, play, pause, speed and selected player for 3D, 2D and coaching. HD and 2D stay aligned after pausing, scrubbing, resuming, switching mode | Browser trace of repeated transitions, both clocks measured | No 2D pause while HD continues; no positive result from clock comparison at just one paused instant |
| G03 Follow camera | The followed actual car remains visible and meaningfully framed at kickoff, general play, wall, aerial, demo/recovery and ballcam transitions | Real video showing each phase; compare native replay where feasible | A technically initialized camera pointing at an empty stadium is a failure |
| G04 Viewer composition | Large HD viewport with small upper-right 2D inset; all four cars and ball readable, including at common desktop widths | Actual screenshots at 1920x1080 and 1500x960 plus bounding rectangles | No centered massive 2D map or 50/50 split; no map so large it hides play |
| G05 Overlay removal | **No** player dotted halo, stranded dotted circle, blue focus ring, floating boost circle above car, or intrusive persistent path tails | Actual screenshot during active play + source and DOM check | Hidden but still rendered, renamed, recolored, or simply toggled off does not count as removed |
| G06 Boost HUD | Correct selected-player boost in a clear, native-style HUD within the **bottom-right of the HD viewport** | Footage showing recorded boost changing as the player spends/collects it | Tiny external BOOST text or floating car marker is not equivalent |
| G07 Clean controls | One legible playback toolbar; no redundant camera or experimental buttons crowding main play; each retained visible control must work | User interaction audit in actual UI | A button existing, changing a label or toggling CSS is not proof of functioning replay behavior |
| G08 Watch while coached | A moment can be selected and replay remains visible while compact coaching appears alongside (outside the pitch), with exact corresponding time range | Full-window screenshot at reviewed t0 and playback video | Scrolling down until the replay disappears is a failure |
| G09 Evidence integrity | Review displays decision-time evidence, a few specific alternatives, uncertainty and separately revealed actual outcome | Source trace to real replay and rendered review | Generic pseudo-advice, invented outcomes, nearest-time causes, or one-match expert habit assertions fail |
| G10 Honest provenance | Real owner test identifies **Git branch, exact commit, local modified files**, browser, replay fixture and whether model was actually called | Immutable acceptance log | CI green or headless E2E success cannot substitute for owner's Windows experience |

## Hard no-regression constraints

- **Do not use Tactical Peek** or a perspective switch as the only way to see positioning; simultaneous 3D and inset tactical 2D is required.
- **Do not build a permanent giant center map or forced 50/50 split**. Keep a separate full Tactical 2D mode only if it works and adds value without distracting from 3D.
- **Delete** outdated dotted/dashed halos around cars, detached circles, the blue selection ring, hovering boost bubble, and permanent cluttering green/blue trails. If a separate height/boost marker is useful, make a proposal only after these have been removed and the owner approves.
- Do not add controls or UI experiments unrelated to the ten gates.
- Don't merge PR #65 blindly; its existing source diff has meaningful but limited changes to V2 context caching and HD iframe sizing, yet it does NOT remove the 50/50 split or prove replay/camera correctness. Its browser E2E changes force-click hidden/obstructed elements and treat screenshot capture failures as nonfatal. **These reduce the value of an accessibility/visual acceptance test**; future owner-facing tests must not rely on forced clicks.
- The user's local branch switch showed uncommitted changes to the same three files touched by PR #65. Record provenance before using the local result to attribute a bug to a specific commit.
- No claim of successful release, verified expert coaching, or end-to-end 3D fidelity without real owner acceptance.

## Verification protocol

1. **Freeze the candidate**: exact integration SHA, branch, `git status --short` from owner's machine. Do not overwrite local modifications, do not delete them to make checkout easy.
2. **Use a genuine original 2v2 .replay**. Start in a clean browser profile. Load once in default HD+map mode. Test before changing to Tactical 2D.
3. **Observe first-load 3D playback** and captured clocks for >2 seconds. Pause and verify both stop. Seek then verify exact replay time, resume, change speed, pause again; test after player selection changes.
4. **Capture first-person review experience** at two important decisions: one sound play and one arguable mistake. The viewed car, tactical map, boost and coaching must all be readable together.
5. **Audit controls**. Every retained button must perform the stated action, or clearly explain genuinely unavailable behavior rather than silently doing nothing.
6. **Provide evidence**: headless WebGL/browser tests, actual screenshot/video, original vs. selected owner assessment. List failures, not just passes.
7. **Owner approves or rejects.** Missing a P0 behavior blocks release even if all workflows are green.

## Known baseline / confirmed by inspection (PR #64)

- `index.html` sets `viewTabSplit` active and `pitchShell` class `split-mode`; `style.css` sets `split-mode` to `grid-template-columns:1fr 1fr`. That is contrary to the latest owner requirement.
- `app.js` `renderPitch()` creates a 26-unit unfilled circle around the focused car and optional dashed circles (e.g. airborne car and ball), despite repeated removal requests.
- `index.html` has a tiny external `#boostValue` in the playback bar; no proof of the requested readable 3D native-style gauge.
- The existing strict browser E2E checks HD canvas existence and one seek-time alignment, but does not establish full play/pause synchronization, follow-car framing, or absence of unwanted overlays.
- PR #65 adds `.hd-inline` CSS size handling and stable V2 context as narrow fixes. Its E2E changes use `{force:true}` clicks and a nonfatal screenshot warning; that cannot certify the owner experience.

These are code observations, NOT demonstrated root causes for every owner-observed runtime failure. A clean, real browser reproduction is still required.
