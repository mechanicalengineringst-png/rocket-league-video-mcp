# Boost-pad native-event contract — parallel handoff for Antigravity

This branch contains the **Python replay parser plus pad-only 2D/3D UI integration**. It does not change Antigravity's P0 camera/interpolation math, playback timer, or car geometry. The web UI now uses a standalone `boost-pad-state.js` evaluator and renders actual availability (when evidence exists).

## What the upload API now returns

`POST /api/replays` -> `replay.boostPadTimeline`:

```json
{
  "schema": "replay-lab/boost-pads-v1",
  "source": "native-boost-pickups",
  "pads": [
    {"id": 0, "x": -3072, "y": -4096, "big": true, "respawnSeconds": 10}
  ],
  "pickups": [
    {"t": 8.11, "padId": 29, "playerId": "Epic:...", "method": "player_position_nearest"}
  ],
  "resets": [4.0, 87.2],
  "unmatchedPickups": [],
  "observedPickupCount": 330,
  "unmatchedPickupCount": 0
}
```

**The numbers/times above are just an illustrative shape; no actual replay has been validated by ChatGPT.** The reported 330 events came from Antigravity's test. There are 34 pads in the real response; ID ordering matches the current `BOOST_PADS` array in `static/viewer3d.js`.

- `source: "unavailable"` means no native pickup events. **Do not display all pads as reliably active**. Availability is unknown.
- `unmatchedPickupCount > 0` means native events could not be resolved to specific pads. `unmatchedPickups` retains timestamps and optional `padType` to correctly flag availability as **unknown** for that size until its cooldown expires or a new kickoff resets it. Native events also remain in `replay.events` without `padId`.
- `method:"player_position_nearest"` is an **inferred pad identity** (not native pad actor ID), bounded by pickup size, proximity and ambiguity guardrails. Report this clearly; if too many are unmatched or inaccurately matched on the real replay, inspect subtr-actor's actor-level boost data instead.
- `resets` are deduplicated native kickoff-spawn and kickoff times within the visible replay window. After a reset all pads are available unless a later pickup says otherwise.
- For `pads[p].big`, cooldown is 10 seconds; otherwise 4 seconds.
- `pad_state_at(timeline, pad_id, time)` in `coach_app/boost_pad_events.py` is the Python **reference evaluator**. The browser should implement identical time-scrub semantics (small data volume, can binary search per pad).
- Never infer pad pickup solely because a car happens to drive near one, or from its boost value increase. Native pickup is the source of truth.
- Existing per-event `replay.events` of type `boost_pickups` now have `padId`, `padType`, `padMatch` and `padDistance` when reliably matched.

## Integration contract for Antigravity

1. Keep P0 interpolation and camera branch independent from this backend PR.
2. When the backend PR is ready, integrate it by merging/cherry-picking **only after checking collisions** with your branch and confirming no local work is lost.
3. The **2D and 3D renderer integration is already implemented on this branch**. When integrating, preserve `boost-pad-state.js`, `updateBoostPads2D`, `setBoostPadTimeline` and `updateBoostPadStates` hooks. The 2D map shows cooldown numbers and radial sweeps; 3D shows dimmed pads and radial sweep rings. Both use the same pure JS evaluator. Confirm the UI remains connected after P0 playback refactoring.
4. Test on `23A661D44DBC5964B0718DBC5F956A33.replay` and print `observedPickupCount`, `unmatchedPickupCount`, and the percentage of confidently mapped native pickups. If substantially different from reported 330 events, investigate event data format rather than changing thresholds by guesswork.
5. Record screenshot comparisons at 0.1s before, at, and 0.1s after a known pickup, at +4/+10 seconds, and after each kickoff reset.
6. Do **not** merge the feature into main until visual QA and user acceptance.

## Tests

Run `python -m pytest coach-app/tests/test_boost_pad_events.py coach-app/tests/test_subtr_replays.py -q` and `node --test coach-app/tests/test_boost_pad_state.cjs`. GitHub Actions now runs both Python and JS boost tests. This branch deliberately avoids changes to the Cloudflare Worker.

## Known limitations

- Current coordinates are standard Soccar, same as the existing viewer. Nonstandard modes/arenas need a separate pad catalog or actor-level pad location data.
- Player location at pickup can be offset from pad center; matching is bounded and may be incomplete. Real-match audit required.
- No direct backend pad-state lookup in HTTP: frontend `boost-pad-state.js` reconstructs states from `pads`, `pickups`, `resets`, `unmatchedPickups`; the Python evaluator is a reference. No real-replay visual verification has yet occurred.
- No authoritative native pad-ID binding has yet been verified.
