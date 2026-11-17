# Replay Lab HD — camera and visual-control hardening (17 November 2026)

Status: independent follow-up branch to draft PR #14; do not merge into main until user validation.

## What changed

- **Recorded camera event lookup:** Native per-player camera events are now resolved by latest valid frame per signal rather than array ordering. This avoids out-of-order older camera events overwriting a newer Ball Cam OFF or rear-look state after seeking. Ambiguous duplicate player identity/name matches are not silently accepted.
- **Uncertain camera state:** If there is no trustworthy recorded Ball Cam status at the current time, the renderer uses a neutral Car Cam fallback rather than inheriting stale Ball Cam ON from a different seek/player. UI continues to say CAMERA UNKNOWN; this is a deterministic viewer fallback, not a claim about how the player actually drove.
- **Camera cut fidelity:** Follow-camera stabilization now snaps at real recorded Ball Cam ON/OFF and rear-look transitions rather than interpolating across unrelated camera poses. Normal movement still uses frame-rate-independent damping.
- **Quality:** The user-selected Sharp profile actually supersamples at 2x when the monitor reports devicePixelRatio=1; previously Sharp was capped to 1x and could appear unchanged. Performance and Balanced retain hardware-aware limits.
- **Trails:** Soft/Original/Off preserves upstream ribbon widths and source visibility. Prior code forcibly restored 15-width ribbons and enabled originally hidden effects after toggling Off.
- **Free-look:** Experimental camera-look reconstruction is opt-in by default. Native switch events remain available and normal Recorded/Force Ball/Force Car camera modes are unchanged.
- **Tests:** Extended camera timeline and shader/effects regression checks for unsorted native events, ambiguous player identities, missing-data fallback, 1x-display Sharp quality and lossless trail settings.

## Constraints

Replay files do **not** store the exact native rendered world-camera transform; camera swivel/rear-look reconstruction is only an approximation when source data exists. Fly Cam is independently viewer controlled, not a historical player input.

No new textures or licensed game assets are added, and the unresolved black/blue field patch from PR #14 is **not** claimed fixed. Original artwork stays default; Clean field is experimental.

No changes to the separate coaching backend, telemetry schema, source MCP, main, or Antigravity working tree. Work is stacked on PR #14 and needs PR #14 to land first in any future approved integration.

## Manual acceptance required

1. On a **separate worktree**, check out this branch, rebuild `coach-app/setup-high-fidelity.cmd`, launch Replay Lab and hard-refresh `http://127.0.0.1:8000/hd`. Confirm the UI uses the new bundle.
2. Load `23A661D44DBC5964B0718DBC5F956A33.replay`. At several recorded ON/OFF switches, pause at the boundary, step forward/back and inspect whether the view and HUD agree. Test backward seeks from ON to OFF and vice versa, and change player. Missing data must display CAMERA UNKNOWN and use the neutral viewer fallback.
3. Inspect a flip at ~7.5s and wall driving at ~13.1s; ensure camera changes are deliberate cuts rather than unwanted smooth camera sweep and no new jitter was introduced.
4. On a 1x display, switch Balanced ↔ Sharp and compare fine distant stadium/grass texture edges, frame pacing, and GPU load. Sharp should visibly use more pixels; do not claim better native assets.
5. Compare trails Soft ↔ Original ↔ Off over the same frames and verify restoration does not reveal previously invisible particles. Compare experimental free-look OFF and ON at a real swivel/rear-view event.
6. Separately continue investigating the unresolved black/blue stadium polygon; existing Clean field toggle has not conclusively removed the artifact.

Automated CI verifies code and a public native replay smoke; it is **not** proof of perceptual native Rocket League parity or that this user's local 2v2 replay was visually tested.
