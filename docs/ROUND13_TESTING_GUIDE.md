# Replay Lab — Round 13 Owner Testing Guide

**Target Branch:** `feature/round13-hd-replay-experience-innovation-20261118`  
**Draft Pull Request:** [#53](https://github.com/mechanicalengineringst-png/rocket-league-video-mcp/pull/53)  
**Target Environment:** Local Windows PC (Python 3.12 + Node.js 22+)  
**Verified Match Fixture:** `fixtures/replays/real_match_2v2.replay`

---

## 1. Quick Start & First-Run Launch on Windows

Replay Lab is configured for reliable, zero-manual-edit launch on Windows:

1. **Open PowerShell or Command Prompt** in the repository root:
   ```cmd
   cd coach-app
   start-windows.cmd
   ```
2. **What this automated launcher does:**
   - Detects or provisions a private Python 3.12 virtual environment (`.venv`).
   - Verifies and installs backend dependencies (`requirements.txt`).
   - Automatically builds the High-Fidelity 3D Viewer bundle if missing (`coach_app/static/hd-player/`).
   - Launches the local FastAPI backend server at `http://127.0.0.1:8000`.
3. **Open Replay Lab in your browser:**
   ```
   http://127.0.0.1:8000
   ```

---

## 2. Complete Recommended Verification Sequence

Follow this step-by-step sequence to verify the complete Replay Lab experience:

### Step 1: Replay Upload & Identity Selection
1. Drag and drop any original `.replay` file (e.g. `fixtures/replays/real_match_2v2.replay`) onto the drop zone, or click **Choose replay file**.
2. Wait ~2–4 seconds for local `subtr-actor` WebAssembly parsing.
3. Select your player from the **Player** dropdown (e.g. `BEN$A sTYXNZ^^` or `Go2DaMoon`).
4. **Expected Outcome:** The 2D Tactical pitch displays the 4 player cars and ball. The High-Fidelity 3D Viewer loads the arena with authentic PBR car models (Fennec, Octane, Dominus, etc.) and active wheel sockets.

---

### Step 2: Automatic Coaching Shortlist & Decision Lens
1. Look at the **Coaching Review Moments** selector.
2. Select an automatically identified coaching episode (e.g. Episode 1).
3. The **Decision Lens** panel automatically opens:
   - Notice that decision-time ($t_0$) metrics are visible (speed, boost, distances to ball and defenders).
   - **Stage A before Stage B:** Notice that actual recorded future follow-through ($\Delta$ metrics and outcome) is **hidden initially** to prevent hindsight bias.
4. Click **Reveal Actual Follow-through (+2s)**:
   - Observe that $+2\text{s}$ recorded metrics appear.
   - The 2D pitch displays $+2\text{s}$ ghost car positions.
5. Click **Loop Scene Playback**:
   - The player continuously replays the 5–15 second window around the decision.
   - Click **Stop scene loop** to return to standard playback.

---

### Step 3: Experimental Situation-Aware Match Report
1. Scroll down to the **Experimental Match Report** panel and open it.
2. Click **Generate Situation-Aware Report**.
3. **Expected Outcome:** The system computes up to six situation-aware tactical findings across the match (spacing, rotation depth, commitment timing, aerial recovery) using deterministic local heuristics.

---

### Step 4: Manual Review of a Missed Moment
1. Seek to any arbitrary moment in the match where you made an interesting play that was not highlighted by the automatic shortlist.
2. In the Decision Lens panel, click **Pin Current Frame for Manual Review**.
3. Click **Analyze Custom Moment**:
   - The system performs a local deterministic assessment of the exact frame, evaluating distances, challenger velocities, and defensive goal coverage without requiring an external AI model.

---

### Step 5: Blind Two-Stage Decision Review
1. Open the **Blind Review** panel.
2. Select your prior exposure (e.g., "Unseen match / Blind").
3. Click **Start Blind Review**:
   - Playback is capped at $t_0$.
   - AI advice and outcome data are strictly masked.
4. Complete **Stage A**:
   - Select your predicted/chosen action (e.g. "Challenge immediately", "Fake challenge / shadow", or "Rotate backpost").
   - Select your estimated goal coverage and confidence level.
   - Click **Lock Pre-Decision Assessment**.
5. Complete **Stage B**:
   - Click **Reveal Outcome**: Watch the post-decision result.
   - Rate decision quality separately from physical execution quality.
   - Click **Save & Export Feedback**: Downloads a structured JSON feedback packet.

---

### Step 6: Optional AI Coaching Panel (Model Transparency & Safety)
1. Open the **AI Model Coach** panel.
2. Check the **Readiness Status**:
   - If no API key is configured, it honestly reports: `Model disabled in local server (No GEMINI_API_KEY)`.
   - **Privacy Guarantee:** API keys are never leaked to client JavaScript.
3. Notice that the **Request AI Coaching Analysis** button is disabled until you explicitly check **"I authorize sending anonymized match telemetry to the configured model provider"**.
4. Click **Local Spatial Inspection**:
   - This runs a zero-provider, zero-cost geometric inspection that populates spatial evidence and actor matrices without making any network calls.

---

### Step 7: Split View & High-Fidelity 3D Viewer Parity
1. Click **Jump to Decision Point** in the coaching panel:
   - Both the 2D pitch and the HD 3D iframe jump synchronously to the exact timestamp.
2. Inside the HD Viewer:
   - **Clean Default:** The stadium is clean and uncluttered by default.
   - **3D Tactical Overlays:** Check the **3D Map** checkbox in the top camera bar to project focus-to-ball distance vectors (color-coded by contest range), teammate spacing lines, and Decision Lens markers directly into the 3D stadium.
   - **Audio Toggle:** Click **🔊 Audio: Off** in the camera toolbar to enable the procedural Web Audio engine (boost thruster whoosh, supersonic sonic booms, ball impact thumps). Adjust volume with the volume slider.
   - **Broadcast Director Autocam:** Click **Director (TV)** to activate dynamic broadcast camera switching (Endzone Attack, Elevated Sideline, High Aerial) with smooth exponential damping.
   - **Camera Rigs:** Switch between **Pro standard (110°)**, **Default RL (90°)**, **Wide angle (110°)**, and **High bird's-eye (105°)**.
   - **Ultra Slow-Motion:** Select **0.1×** playback speed for micro-mechanical touch analysis.
   - **Frame Stepping:** Click `❮│` and `│❯` to step frame-by-frame; observe that car wheels actively roll and turn with front steering pivots even when paused.

---

## 3. Honest Architectural Boundaries & Limitations

1. **No Mandatory Rocket League Install:** The entire application runs standalone in your browser using WASM and WebGL. You do **not** need Rocket League open or installed to review matches.
2. **Optional Native Companion Boundary:** The companion probe checks localhost ports `49123` / `49124` for BakkesMod SOS/Stats API. It provides spectator camera control only when Rocket League is running; it does **not** stream video or alter game files.
3. **External Model Costs:** The optional AI Coach requires an explicit API key and explicit user consent. Replay Lab never executes unannounced or paid external requests.

---

## 4. How to Record & Report Failed Moments

If you discover an unexpected tactical assessment, incorrect vehicle orientation, or desynchronized timestamp:

1. Click **Feedback** on the relevant coaching card.
2. Select **Flawed Assessment** or **Accurate Assessment**.
3. In the note field, record:
   - **Replay Time:** (e.g. `02:14.35` / Frame `3840`).
   - **Player Name & Car:** (e.g. `Quartzsandstorm`, Octane).
   - **Discrepancy Description:** (e.g. "Challenger was recovering backwards; coach recommended rotating instead of challenging").
4. Click **Save Note** and export the feedback bundle via **Blind Review Export** or the feedback panel.
