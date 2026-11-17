# Replay Lab — 3D rendering editorial audit (17 Nov 2026)

Status: implemented on draft PR #14, NOT merged; based on unified test branch.

## Verified code defects and fixes

1. HD recorded Ball Cam was not fully attached to the replay engine. The old UI called the camera plug-in's follow(name) but not the core ReplayPlayer's setAttachedPlayer(id); the core's native Ball Cam transition logic only runs for an attached player. The new UI uses setAttachedPlayer(id) and setBallCamEnabled(null) for native recorded switches, reserving forced true/false for overrides.
2. The source replay contains per-player camera event changes (Ball Cam active, behind-view) and optional continuous camera yaw/pitch samples. The HD viewer now reports native-event counts, ON/OFF moments, a seekable camera-switch timeline, live actual mode and its source (recorded versus forced). A missing stream is labeled unknown, not defaulted to a claim of Ball Cam ON.
3. Recorded free-look yaw/pitch and rear view are reconstructed in an OPTIONAL experimental plugin. These are approximations: raw Rocket League replay files do NOT store the camera's literal world position and rotation. FLY CAM is viewer-controlled, not the player's recorded camera. Disable experimental free-look when it distorts wall or flip handling; native Ball Cam toggles still work.
4. A stationary HDR skybox replaces upstream's slowly rotating 2-degrees-per-second default. The user can compare static HDR with neutral lighting. Additional frame-rate-independent follow-camera smoothing is seek-safe and separate from the upstream internal chase camera.
5. Coarse car/field textures: graphics settings now control DPR and anisotropic texture filtering without changing encoded colour spaces or model materials. Profiles: Performance, Balanced, Sharp.
6. Blocky tire/supersonic trails: reversible soft particle/ribbon shaders and a narrower ribbon width; switch Soft / Original / Off to compare on identical replay frames. These effects are still procedural rather than exact native Rocket League VFX.
   - Actual screenshot investigation: a large black/blue region persisted after hiding the upstream full-boost base. A filtered WebGL raycast traced it to the stadium's Field_STD_Floor_Hex002 mesh (Couleur_T0 material) immediately under the nearby small boost pad. The unnecessary full-boost-base removal was REVERTED. The identified stadium floor mesh is now controlled by a reversible Clean field / Original artwork selector. The clean mode removes that specific decoration, retaining turf, other field lines, and pad mechanics; acceptance screenshot comparison is required.
7. Original P0 boost pads were wired to the older evaluator, which incorrectly called unmatched-pad states available. The new compiled three-valued native event model now drives BOTH original 2D and 3D visuals; unknown is visibly distinct, with cooldown countdowns and radial 3D rings. Both views respect the pad toggle.
8. The original 2D UI was rebuilding 34 boost pads every animation frame, and recalculating Hermite/quaternion frame samples for different panels. Boost nodes are now reused; sampled replay frame is cached, heavy map SVG repaints capped at 30fps in Split View / 60fps in 2D, inspector at 10fps; 3D rAF remains unaffected. Profiling on actual user's GPU remains required.
9. Fly-camera arrow keys and Space now go to the native fly control rather than being stolen by playback shortcuts. A new R shortcut restores recorded camera after forcing views.

## Automated acceptance

The high-fidelity test suite includes camera event, no-data camera state, shader-reversion and quality-capability tests, plus headless Chromium+WebGL using a real public native Rocket League replay. It verifies camera mode override switches and will report any missing GLTF/WASM requests and shader compile errors. Repo-wide CI, 3D tests and coach API suite also run. The user-specific 2v2 replay is not available inside GitHub Actions; automated tests cannot alone establish game-level parity.

## User-side manual acceptance

- From a separate worktree on feature/hd-camera-effects-editorial-20261117 (do not overwrite Antigravity's local work), rebuild coach-app/setup-high-fidelity.cmd so the updated HD Vite bundle is generated, then open /hd and hard refresh.
- Upload the real 2v2 file 23A661D44DBC5964B0718DBC5F956A33.replay.
- Follow a player, select recorded view, and click actual BALL CAM OFF / ON events to compare view transitions. Switch players and seek backward; the HUD should report whether recorded switch data exists.
- Turn experimental free-look ON and OFF at rear-view / camera swivels, and compare gameplay video; the reconstruction cannot match native spectator camera perfectly.
- Compare the formerly black/blue polygon near the pad in Clean field versus Original artwork mode. The source of this polygon was confirmed by WebGL raycast, but the final visual fix must be accepted from a fresh screenshot.
- Inspect kickoff flip near 7.5s, wall ride near 13.1s, demos, resets, boosts, tires, shadows and wheels. Try Sharp graphics, Stable HDR vs Neutral, and Soft vs Original trails.
- Check 0.25x/1x/2x and whether 60Hz / 144Hz behavior is smooth, with and without Split View.
- Compare the 2D map to original 3D at known pad pickups, 4/10s cooldowns, and uncertain unmatched native pickups.
- Keep the branch draft and preserve the existing HD and custom renderers side-by-side until the user signs off.

Limit: no custom asset textures/models have been added, and no actual Rocket League runtime parity claim is made.
