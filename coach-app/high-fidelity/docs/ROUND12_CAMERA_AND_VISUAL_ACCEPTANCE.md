# Round 12 HD viewer — verified code changes and outstanding visual issues

**Status (18 November 2026):** The user's earlier HD viewer criticism is
tracked here as a testing contract, NOT silently declared resolved. This
branch is stacked on the HD-first frontend PR #24, **not** on the newer coach
backend PR #41. Antigravity owns the whole-app renderer integration. ChatGPT
owns this isolated recorded-camera performance/quality-control patch.

## Historical observations from user testing

The user's own browser tests reported:

1. **Follow/Car camera too low and tight:** looked at the back tires or ground
   instead of the developing play; following a specific player sometimes
   behaved incorrectly.
2. **Camera jitter, unwanted roll/flip, odd orbit and incorrect Ball Cam:**
   the camera appeared stuck in Ball Cam or had poor transition behavior.
   Native Ball Cam OFF/ON, rear view and manual/free camera distinctions matter.
3. **Blocky or missing effects:** tire trails and boost visuals were large
   polygon/block shapes; wheel-ground alignment and boost gauge often poor.
4. **Asset fidelity:** blue block-like car, misplaced/low-resolution textures,
   weak stadium materials and missing decals; goal/demolition transitions
   difficult to understand.
5. **Whole-app UX:** the basic geometric 3D viewer was rejected; use only
   2D tactical, HD 3D recreation, and the synchronized HD + 2D split view.
   Support actionable coaching, not cluttered overlays or dozens of generic
   flags.
6. **Strategic product constraint:** the standalone HD viewer must continue
   to work without launching Rocket League; the *optional* actual Rocket
   League client/Stats API is another rendering option, not a replacement.

These are user-reported historical defects, NOT proof they remain in the
current branch after all fixes, nor proof they are resolved. Browser visual
acceptance is still required with real native .replay files on Windows.

## Existing code findings in PR #24 (actual source inspection)

- `src/camera-timeline.js` can read Ball Cam ON/OFF, rear-view, and any
  sampled camera yaw/pitch in ReplayModel. It correctly distinguishes unknown
  switches from recorded ON and uses the ReplayModel clock at seeks.
- `src/recorded-camera-switch.js` runs before the camera plugin and resets
  an unknown state to neutral *unclaimed* Car Cam, preventing a previous
  player's Ball Cam ON from leaking through.
- `src/camera-polish.js` adds a minimum chase distance/elevation, horizon
  levelling, limited camera smoothing, and hard cuts on native switches,
  camera changes, large seeks/goal jumps/demolition respawns.
- `src/visual-quality.js` contains reversible soft/trail shader patches,
  conservative anisotropic filtering that leaves authored sampler modes
  intact, and a reversible clean-floor-decal mode.
- The HD-first integration from PR #24 embeds an actual HD iframe rather
  than the basic geometric 3D in split view. **Round 12 coaching PR #41
  does not yet contain that frontend integration**. The latest active
  coaching branch still has a `3D Arena`/geometry tab.

Some claimed visual corrections have only automated checks or older
screenshots, not current real replay proof. We must not call them visually
fixed based on CI alone.

## New isolated Round 12 camera improvement

The previous `recordedCameraAt()` rescanned all camera events on **every
frame** while rendering in follow mode. With hundreds of native Ball Cam
switches, doing this repeatedly at 60–144 Hz adds JS main-thread work
during gameplay playback and seeking.

This patch compiles a **per-replay immutable signal index** once into
WeakMap-backed event timelines, then uses O(log n) binary lookups for
each camera state. It preserves:
- exact native event frame boundaries, including backward seeking;
- the latest known independent Ball Cam, rear-view and driving state;
- source-array tie precedence for multiple changes on the same frame;
- distinction between unknown and recorded OFF;
- captured yaw/pitch values from selected native frame samples;
- no changes to forced camera overrides.

The index is released when the decoded replay/track is garbage-collected.
Replacing the event array or appending events rebuilds it. Editing an
existing event value in place while leaving the array and count unchanged
is unsupported; ReplayModel is an immutable decoded replay.

**This is an algorithmic performance and correctness improvement, not a
promise that a low camera, blocky boost, or missing assets are fixed.**

## Visual acceptance matrix for next user test (actual .replay)

| Scenario | Evidence required to pass | Current status |
|---|---|---|
| Standalone HD full match | Recorded .replay loads, car + arena assets really visible, playback stable | **Needs user's Windows/browser test** |
| Chase camera | Can follow exact player, good horizon and ball visibility; no back-tire obstruction | **Unverified visually** |
| Ball Cam transitions | Recorded ON/OFF seek matches native replay where events exist | **Unit-tested; native comparison outstanding** |
| Missing camera telemetry | Labeled unknown; deterministic neutral fallback, not falsely claimed Ball Cam ON | **Unit-tested** |
| 360-degree/free camera | Camera control doesn't corrupt recorded mode; original state recoverable | **Browser comparison needed** |
| Backboard/wall aerial | Camera, ball/car geometry and vehicle rolls remain legible | **Browser comparison needed** |
| Effects | Boost flame/tire/supersonic trails are smooth, visible, reversible | **Shader unit tests; visual comparison outstanding** |
| Models/textures | Recognizable vehicle meshes, wheels aligned, glTF decals not mispositioned | **Asset QA outstanding** |
| Split view | One selected player and timestamp, 2D/HD synchronized, no geometric 3D tab | **Frontend integration outstanding** |
| Native RL rendering | Optional real-game companion loads/seeks/changes POV, without modifying game without permission | **Separate PR #28, live game unverified** |
| Coaching moment | Real source-backed candidate seeks both views, with evidence, no fake suggestion | **Cross-agent integration outstanding** |

## Concrete next actions for Antigravity and ChatGPT

1. Use this branch's `camera-timeline.js` and new regression tests when
   integrating PR #24 into the Round 12 coaching stack. If a different
   native camera source is implemented, preserve the exact state semantics.
2. Add deterministic browser QA on a real native replay with logged camera
   event times; inspect camera ON/OFF at boundaries and immediately after
   backward/forward seeking.
3. Verify 3D player identities across two parsers; never guess a duplicate
   player match.
4. Use screenshots or short clips to compare the worst real HD scenes
   (backboard, wall transitions, aerial inversions, boost trails, stadium
   textures) against an actual Rocket League replay.
5. Retain the independent HD renderer AND separately exercise the optional
   native game path once user permission and Windows setup are available.
6. Track unresolved issues with exact replay-local timestamps and camera
   mode, but do not commit user replay data, account names, local paths,
   credentials or images of private matches to this public repository.

## Testing claim boundaries

Node unit/QA tests validate code logic, not exact native visual parity or
unavailable real-camera analog inputs. A compiled Vite bundle is not a real
rendering test. High-rank coaching validity is a separate expert-review gate.
No actual native-game commands were issued by this branch.
