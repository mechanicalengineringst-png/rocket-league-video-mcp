# High-Fidelity 3D Replay Preview (separate experimental renderer)

This is a **real independent 3D browser replay engine**, not a skin on the old
procedural viewer. Its code lives in \`high-fidelity/\`; it builds onto the
existing FastAPI server at \`/hd\`. The original coaching interface, 2D,
boost-pad contract and current 3D renderer remain untouched.

## One-time setup on Windows

1. Install **Node.js 22+** if it isn't already installed.
2. In \`coach-app\`, double-click **\`setup-high-fidelity.cmd\`**. It runs
   \`npm install\` and \`npm run build\` in \`coach-app/high-fidelity\`.
   This locally downloads the published \`@rlrml/player@1.5.1\` and
   \`@rlrml/subtr-actor@1.5.1\` packages and copies the assets they ship.
3. Start \`coach-app/start-windows.cmd\` normally, then open
   **http://127.0.0.1:8000/hd**. If it says the HD viewer isn't built,
   run step 2 and refresh. The server does not require a restart.
4. Upload the same \`23A661D44DBC5964B0718DBC5F956A33.replay\`, or open
   Replay Lab's normal UI, load the replay there, and click **HD 3D Beta**.
   The original \`File\` will transfer between the two same-origin browser tabs
   without uploading it to a third-party server.
   
Development workflow:
\`\`\`sh
cd coach-app/high-fidelity
npm install --no-audit --no-fund
npm test
npm run dev
npm run build
\`\`\`
The development server is on http://127.0.0.1:5178; its page is standalone,
so opening the raw \`.replay\` from its file picker is the simplest QA path.

## What is genuinely different

- Uses the maintained subtr-actor **native replay data model**, not a 30Hz
  FastAPI JSON/nearest-frame visual approximation; it reads original
  \`.replay\` bytes in the browser via WebAssembly.
- Uses \`@rlrml/player\`'s continuous replay clock and interpolation.
  \`Hermite\` (velocity tangent) and \`linear\` interpolation are A/B switchable.
- Instantiates the original library's GLTF stadium/car/ball loaders, including
  optional HDRI environment and artist-authored geometry. Assets are copied
  **only to your local build**; none are added to Git history.
- Follows a player with their recorded camera settings, and offers forced
  Ball Cam, Car Cam, orbit and fly camera.
- Adds first-party player name tags, boost pad events and scored-text effects.
- Provides a replay timeline, speed controls, frame stepping, fullscreen,
  keyboard shortcuts, an honest real-replay events row and hitbox toggles.

**This is a prototype, not a verified Rocket League graphical clone.** 
Personal vehicle cosmetics, maps beyond a generic stadium, precise camera
transitions, effects, and availability depend on underlying replay data and
which assets actually load. It hasn't been evaluated against the user's
seven-minute 2v2 replay or visually compared frame by frame.

## Source and license caution

The npm **code** package reports MIT licensing and the upstream repo
includes \`js/player/LICENSE\`. **Do not assume bundled 3D textures,
models, branding, arenas, decals or sound are automatically MIT.**
Upstream's arena loader includes references to original game art and a
ballcam.tv texture; provenance and redistribution rights have not been
independently established. The files are not committed to this repo.
Before any public distribution, replace them with verified licensable
original assets or get permission from rights holders. Do not silently
include copyright-protected models in a public website or release ZIP.

Source: https://github.com/rlrml/subtr-actor/tree/master/js/player
Package: https://www.npmjs.com/package/@rlrml/player

## QA acceptance on real replay

- Open the same original \`.replay\` in the native game and HD viewer.
- Compare wall climbs, curved wall transitions, flips, aerials and recoveries.
- Test chase/recorded Ball Cam with pauses, seeks, slow motion, full speed,
  demos, boost pickup/reset, and multiple players.
- Confirm the browser console has no missing assets / failed WASM loading.
- On both 60 and 144 Hz displays, watch for camera stutter and frame snapping.
- Keep P0 Antigravity work separate. This branch never overwrites its playback
  or custom camera work; the experiment is opt-in via **HD 3D Beta**.
- Do not merge without visual QA, the asset-license audit, and user approval.

## Future integration

If the real replay test beats the bespoke viewer substantially, we can
promote this engine into the normal 3D tab. Then synchronize its playhead and
player id with the coaching UI and reuse the existing decision overlays via
\`player.replayRoot\`/plugins, instead of continuing to patch the procedural
renderer. No recorded replay bytes should be sent to Gemini without the
user's explicit action.
