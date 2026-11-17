# Replay Lab HD synchronization (integration prototype)

This is an independent integration branch, not the finished one-window
HD-plus-2D design. It addresses a real user-acceptance defect: opening HD
only copied the replay File and initial player, leaving two unrelated playback
clocks and focus selections.

## What works at the code level

- Once the user **clicks** "HD 3D Beta", the existing same-origin file
  transfer remains in place; no upload to a remote host is added.
- After HD decoding and its assets are ready, HD acknowledges the active
  session. The main app then sends selected player name **and team**,
  replay time, speed, and play/pause state. The parent is authoritative.
- Switching "Who are we coaching?", changing speed, jumping to a moment,
  scrubbing, pausing, or resuming in the main app propagates to HD.
- Within normal playback, the bridge forwards a coalesced timing update at
  most about five times per second and HD only seeks to correct drift greater
  than 0.6 seconds. This avoids 60Hz repeated seek jitter.
- When paused, HD will seek to within 0.06 seconds of the parent's clock.
- HD accepts only messages from its same-origin opener, for the currently
  loaded session, with strictly increasing sequence numbers.
- The focus mapping matches **player name plus team**, and explicitly
  declines ambiguous matches rather than silently following the wrong car.
- Opening HD directly, without a parent, remains supported.
- A synthetic demo in the main app is never synced to a previously loaded
  real replay file.

## Limitations / explicit acceptance gates

This does **not** replace the old 3D Arena yet. The original HD source branch
may change under Antigravity's ongoing work; cherry-pick/reconcile carefully.
The integration is currently in a separate tab, not embedded in the main
layout. It does not make the *new coaching backend* visible.

It assumes both replay decoders share the same elapsed-time origin. That has
NOT been measured against a live native replay in the user's browser.
A clock offset would require a calibrated match-event alignment or an explicit
displayed synchronization offset. The initial player matching is name+team
rather than immutable account identity because parser ID formats can differ;
duplicate display names remain unresolved. Do not claim 1:1 timing or a
fully verified player identity yet.

There is intentionally no ongoing reverse control from HD to 2D. Playback
changes made in the main Replay Lab tab control the HD window. Controls in HD
itself may be overridden at the next main-tab update. The final single-window
design should have ONE authoritative clock and two panes rather than two
independently running replay engines.

## Verification

Run from \`coach-app/high-fidelity/\`:

\`\`\`bash
npm test
npm run build
\`\`\`

The pure contract tests assert origin/session/sequence validation, unknown and
ambiguous focus selection, drift thresholds, throttle/seek behavior, and file
transfer. The browser build verifies imports. Tests cannot substitute for
live two-window acceptance testing with a real \`.replay\`.

**Manual checks:** load a real replay; open HD; switch coached players
between two blue/orange participants and verify HD follow; pause/scrub to
specific moments; change speed; observe how far the clocks drift during
normal play; load a second replay; verify no stale focus, clock, or source
file. Record any elapsed-clock offset with goal timestamp references.

No automated merging. Keep this branch separate until Antigravity finishes
its parallel HD camera implementation and source conflicts are reviewed.
