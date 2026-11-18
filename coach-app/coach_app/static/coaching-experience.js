/**
 * Replay Lab — Interactive AI Coaching Experience Controller
 *
 * Implements Round 9 interactive tactical coaching:
 * - Multi-node tactical episode selector & stepper (N1 -> N2 -> N3)
 * - Navigation to earlier contributing decisions
 * - Synchronized replay seeking (2D map and 3D arena)
 * - Structured coaching lesson cards with epistemic stances & feasibility
 * - Interactive Evidence Inspector modal for granular telemetry & uncertainty
 * - Follow-up conversational Q&A with strict evidence citations
 * - Stage 1 / Stage 2 Temporal Firewall (quarantining hindsight outcomes)
 */

(function (global) {
  'use strict';

  // Helper selector
  const $ = id => document.getElementById(id);
  const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));

  class CoachingExperienceController {
    constructor() {
      this.episodes = [];
      this.isDemo = false;
      this.liveStatus = 'Load a real replay to inspect source-backed coaching, or explicitly select the simulated demo.';
      this.activeEpisode = null;
      this.activeNode = (this.activeEpisode && this.activeEpisode.nodes[this.activeEpisode.nodes.length - 1]) || null;
      this.stage1Locked = true;
      this.inspectedEvidence = null;
      this.chatHistory = [];
      this.isAnswering = false;

      this.initDefaultChat();
    }

    initDefaultChat() {
      this.chatHistory = [
        {
          sender: 'coach',
          text: 'Welcome to Replay Lab Coaching. Select a decision moment on the episode timeline above to inspect the pre-decision telemetry, or ask me any question below about your positioning, alternatives, or teammate coverage.',
          citations: []
        }
      ];
    }

    /**
     * Mount into DOM container
     */
    mount(containerId) {
      this.container = $(containerId);
      if (!this.container) {
        console.warn('Coaching container #' + containerId + ' not found in DOM.');
        return;
      }
      this.render();
      this.bindEvents();
    }

    resetForReplay(demo = false) {
      this.isDemo = Boolean(demo);
      this.episodes = this.isDemo
        ? [...(global.ReplayLabCoachingFixtures?.FIXTURES || [])] : [];
      this.activeEpisode = this.episodes[0] || null;
      this.activeNode = this.activeEpisode?.nodes?.find(n => n.is_primary) || null;
      this.stage1Locked = true;
      this.inspectedEvidence = null;
      this.liveStatus = this.isDemo
        ? 'SIMULATED DEMONSTRATION ONLY — all match situations and coaching text are examples.'
        : 'Waiting for source-backed analysis of the selected player.';
      this.initDefaultChat();
      this.render();
    }

    setLiveStatus(message) {
      if (this.isDemo) return;
      this.liveStatus = String(message || 'Live coaching unavailable.');
      if (!this.activeEpisode) this.render();
    }

    addVerifiedLesson(lesson, request, decisionCase = {}) {
      if (!lesson || lesson.schema !== 'CoachLessonV0'
          || lesson.stage !== 'predecision' || !request) return;
      const decision = lesson.decision || {};
      const time = Number(decision.t0_s);
      if (!Number.isFinite(time)) return;
      const primaryId = decision.node_id || 'N3';
      const tactics = lesson.tactical_options || {};
      const allClaims = [...(lesson.claims || []), ...(tactics.claims || [])];
      const references = [...new Set(allClaims.flatMap(c => c.evidence_refs || []))]
        .filter(ref => typeof ref === 'string' && ref.length <= 160).slice(0, 30);
      const evidence = references.map(id => ({
        id, kind: 'reference', label: id, value: 'Open verified source',
        provenance: 'backend_reference', description: 'Value is retrieved from /api/coach/evidence'
      }));
      const choices = (tactics.options || []).map(o => ({
        id: 'option-' + String(o.action || 'unknown'),
        action: String(o.action || 'unknown').replace(/_/g, ' '),
        feasibility: o.physical_feasibility || 'unknown',
        feasibility_label: o.physical_feasibility || 'unknown',
        risk_level: 'unknown',
        pros: 'Uncalibrated rule stance: ' + (o.strategic_stance || 'not assessed'),
        cons: 'Limit sources: ' + [...(o.limiting_claims || []), ...(o.severe_limit_claims || [])].join(', ')
          + '. Counterfactual ball trajectories and expected value are not simulated.',
        description: 'Rule-derived option, not a validated best move. ' +
          'Supporting sources: ' + (o.supporting_claims || []).join(', ')
      }));
      const prior = decision.other_decisions || [];
      const moments = [...prior, {node_id: primaryId, t0_s: time}];
      const nodes = moments.map((moment, i) => {
        const isPrimary = moment.node_id === primaryId;
        const nodeTime = Number(moment.t0_s);
        return {
          node_id: moment.node_id, t0: nodeTime, is_primary: isPrimary,
          information_cutoff_s: nodeTime,
          label: isPrimary ? 'Primary source-backed decision' : 'Earlier context timestamp (not individually graded)',
          summary: isPrimary ? 'Decision-time evidence and uncalibrated tactical possibilities.'
            : 'Context timestamp selected near a source case; not a proven contributing choice.',
          coaching: isPrimary ? {
            headline: 'Source-backed tactical possibilities — not expert validated',
            stance: 'neutral', confidence: 'hypothesis',
            assessment: 'Backend verdict: ' + (lesson.assessment?.grade || 'undetermined')
              + '. The tactical option menu is an uncalibrated hypothesis, not a proven recommendation.',
            feasible_alternatives: choices,
            observed_evidence: evidence,
            earlier_contributors: (lesson.earlier_factors || []).map(h => ({
              id: h.hypothesis_id, earlier_node: h.earlier_node,
              question: 'Could an earlier setup have affected this decision?',
              not_established: 'Unverified causal hypothesis. Consult its supporting evidence.'
            })),
            takeaway: 'No expert-calibrated takeaway yet. Inspect options, constraints and uncertainty.',
            unknowns: [...(lesson.not_observable || []), ...(lesson.uncertainties || []).map(u => u.what || 'Unknown input')]
          } : {
            headline: 'Context only; no independently verified tactical grade.',
            stance: 'neutral', confidence: 'hypothesis',
            assessment: 'A selected earlier timestamp is not by itself evidence of a contributing mistake.',
            feasible_alternatives: [], observed_evidence: [], earlier_contributors: [],
            unknowns: [], takeaway: 'Review this timestamp in the replay before attributing causation.'
          }
        };
      });
      const replayPlayer = request.replay?.players?.find(p => p.id === request.player_id);
      const ep = {
        schema: 'CoachLessonV0', source: 'backend_stage1',
        episode_id: 'backend-' + request.player_id + '-' + String(time),
        title: String(decisionCase.title || 'Replay tactical decision'),
        subtitle: 'SOURCE-BACKED / PREDECISION / UNCALIBRATED',
        player_id: request.player_id, player_name: replayPlayer?.name || 'Selected player',
        backendRequest: request,
        window: {start_s: request.episode_start_s, end_s: time,
          length_s: time - request.episode_start_s, stage1_horizon_s: time},
        nodes, retrospective: null
      };
      this.addLiveEpisode(ep);
    }

    /**
     * Switch active episode
     */
    selectEpisode(episodeId) {
      const ep = this.episodes.find(e => e.episode_id === episodeId);
      if (!ep) return;
      this.activeEpisode = ep;
      // Default to primary decision node (final node)
      const primary = ep.nodes.find(n => n.is_primary) || ep.nodes[ep.nodes.length - 1];
      this.activeNode = primary;
      this.stage1Locked = true;
      this.inspectedEvidence = null;
      this.initDefaultChat();
      this.render();
      this.syncReplayToNode(this.activeNode);
    }

    /**
     * Select specific decision node in episode
     */
    selectNode(nodeId) {
      if (!this.activeEpisode) return;
      const node = this.activeEpisode.nodes.find(n => n.node_id === nodeId);
      if (!node) return;
      this.activeNode = node;
      this.render();
      this.syncReplayToNode(node);
    }

    /**
     * Navigate backward to earlier contributing choice (e.g. N3 -> N2 -> N1)
     */
    navigateEarlier() {
      if (!this.activeEpisode || !this.activeNode) return;
      const idx = this.activeEpisode.nodes.findIndex(n => n.node_id === this.activeNode.node_id);
      if (idx > 0) {
        this.selectNode(this.activeEpisode.nodes[idx - 1].node_id);
      }
    }

    /**
     * Navigate forward to subsequent decision moment
     */
    navigateLater() {
      if (!this.activeEpisode || !this.activeNode) return;
      const idx = this.activeEpisode.nodes.findIndex(n => n.node_id === this.activeNode.node_id);
      if (idx >= 0 && idx < this.activeEpisode.nodes.length - 1) {
        this.selectNode(this.activeEpisode.nodes[idx + 1].node_id);
      }
    }

    /**
     * Jump replay playback and synchronize 2D pitch & 3D arena
     */
    syncReplayToNode(node) {
      if (!node) return;
      if (typeof global.chooseTime === 'function') {
        global.chooseTime(node.t0);
      }
      if (typeof global.stopPlay === 'function') {
        global.stopPlay();
      }
      this.updatePitchOverlays(node);
    }

    /**
     * Step replay time relative to active node
     */
    stepTime(deltaSeconds) {
      if (!this.activeNode) return;
      if (deltaSeconds > 0 && this.stage1Locked) return;
      const targetTime = Math.max(0, this.activeNode.t0 + deltaSeconds);
      if (typeof global.chooseTime === 'function') {
        global.chooseTime(targetTime);
      }
    }

    /**
     * Render tactical overlays on SVG pitch
     */
    updatePitchOverlays(node) {
      const dynamicLayer = $('dynamicLayers');
      if (!dynamicLayer) return;

      // Clean existing coaching overlays
      const existingCoachingLayer = $('coachingOverlayGroup');
      if (existingCoachingLayer) {
        existingCoachingLayer.remove();
      }

      if (!node || !node.car_state) return;

      const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      group.id = 'coachingOverlayGroup';

      // Pitch coordinate mapper (Rocket League coords to SVG viewBox 760x970)
      // X: [-4096, 4096] -> [58, 702]
      // Y: [-5120, 5120] -> [50, 920] (Blue is negative Y in RL, bottom in SVG)
      const toSvgX = x => 380 - (x / 4096) * 322;
      const toSvgY = y => 485 - (y / 5120) * 435;

      const carPos = node.car_state.position;
      const carSvgX = toSvgX(carPos[0]);
      const carSvgY = toSvgY(carPos[1]);

      // 1. Spacing line to teammate
      if (node.teammate_state && node.teammate_state.position) {
        const matePos = node.teammate_state.position;
        const mateSvgX = toSvgX(matePos[0]);
        const mateSvgY = toSvgY(matePos[1]);

        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.setAttribute('x1', carSvgX);
        line.setAttribute('y1', carSvgY);
        line.setAttribute('x2', mateSvgX);
        line.setAttribute('y2', mateSvgY);
        line.setAttribute('stroke', '#00e5ff');
        line.setAttribute('stroke-width', '2');
        line.setAttribute('stroke-dasharray', '5 5');
        line.setAttribute('stroke-opacity', '0.7');
        group.append(line);

        // Distance text badge
        const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        text.setAttribute('x', (carSvgX + mateSvgX) / 2);
        text.setAttribute('y', (carSvgY + mateSvgY) / 2 - 8);
        text.setAttribute('fill', '#00e5ff');
        text.setAttribute('font-size', '10');
        text.setAttribute('font-weight', 'bold');
        text.setAttribute('text-anchor', 'middle');
        text.textContent = Math.round(node.teammate_state.distance_to_focus || 2000) + ' uu';
        group.append(text);
      }

      // 2. Ball threat radius
      if (node.ball_state && node.ball_state.position) {
        const ballPos = node.ball_state.position;
        const ballSvgX = toSvgX(ballPos[0]);
        const ballSvgY = toSvgY(ballPos[1]);

        const threatCircle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        threatCircle.setAttribute('cx', ballSvgX);
        threatCircle.setAttribute('cy', ballSvgY);
        threatCircle.setAttribute('r', '32');
        threatCircle.setAttribute('fill', 'none');
        threatCircle.setAttribute('stroke', '#ff7733');
        threatCircle.setAttribute('stroke-width', '1.5');
        threatCircle.setAttribute('stroke-dasharray', '4 4');
        threatCircle.setAttribute('stroke-opacity', '0.8');
        group.append(threatCircle);
      }

      // 3. Car Facing Cone
      if (node.car_state.forward) {
        const fwd = node.car_state.forward;
        const tipX = carSvgX + fwd[0] * 35;
        const tipY = carSvgY + fwd[1] * 35;

        const arrow = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        arrow.setAttribute('x1', carSvgX);
        arrow.setAttribute('y1', carSvgY);
        arrow.setAttribute('x2', tipX);
        arrow.setAttribute('y2', tipY);
        arrow.setAttribute('stroke', '#ffffff');
        arrow.setAttribute('stroke-width', '2.5');
        arrow.setAttribute('marker-end', 'url(#arrowhead)');
        group.append(arrow);
      }

      dynamicLayer.append(group);
    }

    /**
     * Unlock or toggle Stage 2 Retrospective Outcome
     */
    toggleStage1Firewall() {
      // There is no trusted server-side Stage 2 contract for uploaded replays.
      if (!this.isDemo) return;
      this.stage1Locked = !this.stage1Locked;
      this.render();
    }

    /**
     * Open Evidence Inspector Modal
     */
    inspectEvidence(item) {
      this.inspectedEvidence = item;
      this.renderInspectorModal();
    }

    closeInspectorModal() {
      this.inspectedEvidence = null;
      const modal = $('evidenceInspectorModal');
      if (modal) modal.remove();
    }

    /**
     * Ask coaching follow-up question
     */
    async askQuestion(questionText, questionType) {
      if (!questionText?.trim() || this.isAnswering) return;
      const qText = questionText.trim().slice(0, 500);
      const ep = this.activeEpisode;
      this.chatHistory.push({sender:'user',text:qText,citations:[]});
      this.isAnswering = true;
      this.renderChatList();
      try {
        if (!ep?.backendRequest) {
          // A demo must never pretend to be an evidence-verified live conversation.
          this.chatHistory.push({sender:'coach',
            text: 'This is a simulated demonstration. No live evidence-navigation or model conversation is available for this example.',
            citations:[]});
        } else {
          const res = await fetch('/api/coach/followup', {
            method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({...ep.backendRequest, mode:'deterministic', question:qText})
          });
          if (!res.ok) throw new Error('Evidence-navigation request failed (' + res.status + ').');
          const data = await res.json();
          if (data.schema !== 'CoachFollowupV0' || data.mode !== 'local_evidence_navigation')
            throw new Error('Unrecognized coaching response.');
          this.chatHistory.push({
            sender:'coach',
            text:'Evidence navigation (not AI conversation): ' + String(data.answer || 'No supported answer.'),
            citations:(data.related_refs || []).filter(ref => typeof ref === 'string')
          });
        }
      } catch (err) {
        this.chatHistory.push({sender:'coach',
          text:'Evidence-navigation unavailable. No replay measurements or citations have been inferred.',
          citations:[]});
      } finally {
        this.isAnswering = false;
        this.renderChatList();
      }
    }

    async inspectEvidenceReference(id) {
      const ep = this.activeEpisode;
      if (!ep?.backendRequest) {
        this.inspectEvidence((this.activeNode?.coaching?.observed_evidence || []).find(e => e.id === id)
          || {id, label:'Demo citation',kind:'hypothesis',value:'No real replay source'});
        return;
      }
      try {
        const res = await fetch('/api/coach/evidence',{
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({...ep.backendRequest,mode:'deterministic',evidence_refs:[id]})
        });
        if (!res.ok) throw new Error('Backend did not verify this evidence ID (' + res.status + ').');
        const data = await res.json();
        if (data.schema !== 'CoachEvidenceLookupV0' || data.retrospective_exposed !== false)
          throw new Error('Unsupported evidence response.');
        const item = (data.records || []).find(r=>r.id===id);
        if (!item) throw new Error('Citation missing from reconstructed episode.');
        const kind = item.kind || (item.category==='unverified_contributor_hypothesis'?'hypothesis':'derived');
        this.inspectEvidence({id,kind,label:item.category||'Source record',
          value:item.value === undefined ? (item.what || 'No numerical value') : JSON.stringify(item.value),
          unit:item.unit || '',
          provenance:JSON.stringify(item.provenance || item.verification || 'backend_source'),
          description:'Server-verified reference lookup. Semantic tactical meaning is not expert verified.'});
      } catch (err) {
        this.inspectEvidence({id,kind:'unknown',label:'Unverified source',
          value:'Unavailable',provenance:'none',
          description:'The backend could not resolve this citation: ' + err.message});
      }
    }

    inferQuestionType(text) {
      const lower = text.toLowerCase();
      if (lower.includes('shadow') || lower.includes('alternative') || lower.includes('instead') || lower.includes('could i')) {
        return 'alternative_feasibility';
      }
      if (lower.includes('teammate') || lower.includes('cover')) {
        return 'teammate_actions';
      }
      if (lower.includes('boost') || lower.includes('what would change') || lower.includes('if i had')) {
        return 'what_would_change';
      }
      if (lower.includes('practice') || lower.includes('train') || lower.includes('next time')) {
        return 'practice_priority';
      }
      return 'why_flagged';
    }

    /**
     * Deterministic, Stage-1 compliant answer generator with explicit evidence citations
     */
    generateDeterministicAnswer() {
      return {sender:'coach',
        text:'A simulated example cannot supply verified measurements or live coaching answers.',
        citations:[]};
    }

    /**
     * Primary Render method
     */
    render() {
      if (!this.container) return;
      if (!this.activeEpisode) {
        this.container.innerHTML = '<div class="coaching-empty">' + escapeHTML(this.liveStatus) + '</div>';
        return;
      }

      const ep = this.activeEpisode;
      const node = this.activeNode || ep.nodes[ep.nodes.length - 1];
      const coaching = node.coaching || {};

      this.container.innerHTML = `
        <div class="coaching-deck">
          <!-- 1. Top Bar: Episode Switcher & Temporal Firewall Banner -->
          <div class="coaching-top-bar">
            <div class="episode-selector-row">
              <div class="episode-title-block">
                <span class="coaching-badge">${this.isDemo ? 'SIMULATED DEMONSTRATION — NOT YOUR REPLAY' : 'SOURCE-BACKED COACHING / UNCALIBRATED'}</span>
                <h3 class="episode-heading">${escapeHTML(ep.title)}</h3>
                <span class="episode-sub">${escapeHTML(ep.subtitle)} · Player: <strong>${escapeHTML(ep.player_name)}</strong></span>
              </div>
              <div class="episode-dropdown-wrap">
                <label for="episodeSelect" class="sr-only">Select Episode</label>
                <select id="episodeSelect" class="episode-select">
                  ${this.episodes.map(e => `
                    <option value="${e.episode_id}" ${e.episode_id === ep.episode_id ? 'selected' : ''}>
                      ${escapeHTML(e.title)} (${e.window.length_s.toFixed(1)}s)
                    </option>
                  `).join('')}
                </select>
              </div>
            </div>

            <!-- Temporal Firewall Banner -->
            <div class="firewall-banner ${this.stage1Locked ? 'firewall-locked' : 'firewall-unlocked'}">
              <div class="firewall-status">
                <span class="firewall-icon">${this.stage1Locked ? '🔒' : '🔓'}</span>
                <div>
                  <strong>${this.stage1Locked ? 'STAGE 1: PRE-DECISION COGNITION' : 'STAGE 2: RETROSPECTIVE OUTCOME UNLOCKED'}</strong>
                  <p class="firewall-desc">
                    ${this.stage1Locked
                      ? (this.isDemo
                          ? 'Demo analysis is predecision; simulated outcomes stay hidden.'
                          : 'Server evidence is limited to decision-time data. No verified retrospective contract is available.')
                      : 'Hindsight outcome visible. WARNING: Post-t0 events never prove decision quality.'}
                  </p>
                </div>
              </div>
              <button id="toggleFirewallBtn" class="button-mini ${this.stage1Locked ? 'btn-unlock' : 'btn-lock'}" type="button" ${this.isDemo ? '' : 'disabled'}>
                ${this.isDemo ? (this.stage1Locked ? '🔓 Reveal Simulated Outcome' : '🔒 Hide Simulated Outcome') : 'Retrospective unavailable'}
              </button>
            </div>
          </div>

          <!-- 2. Multi-Node Decision Stepper Bar -->
          <div class="stepper-panel">
            <div class="stepper-header">
              <span class="stepper-title">DECISION SEQUENCE (${ep.nodes.length} Moments)</span>
              <div class="stepper-nav-buttons">
                <button id="stepPrevBtn" class="button-mini" type="button" title="Navigate to earlier decision">
                  ⏮ Earlier Choice
                </button>
                <button id="stepNextBtn" class="button-mini" type="button" title="Navigate to later decision">
                  Later Choice ⏭
                </button>
              </div>
            </div>

            <div class="timeline-stepper">
              ${ep.nodes.map((n, i) => {
                const isActive = n.node_id === node.node_id;
                const isPrimary = n.is_primary;
                const prevNode = i > 0 ? ep.nodes[i - 1] : null;
                const deltaT = prevNode ? (n.t0 - prevNode.t0).toFixed(1) : null;

                return `
                  ${prevNode ? `
                    <div class="stepper-connector">
                      <span class="connector-line"></span>
                      <span class="connector-delta">+${deltaT}s</span>
                    </div>
                  ` : ''}
                  <button class="step-node ${isActive ? 'active' : ''} ${isPrimary ? 'primary-node' : 'context-node'}"
                          data-node-id="${n.node_id}" type="button">
                    <span class="node-id-tag">${n.node_id}${isPrimary ? ' (Primary)' : ''}</span>
                    <span class="node-time">${n.t0.toFixed(1)}s</span>
                    <span class="node-label">${escapeHTML(n.label)}</span>
                  </button>
                `;
              }).join('')}
            </div>

            <!-- Replay Sync Stepping Bar -->
            <div class="replay-step-bar">
              <span class="step-label">REPLAY VIEW JUMP:</span>
              <button id="jumpBeforeBtn" class="button-mini" type="button">⏪ -2s Setup</button>
              <button id="jumpDecisionBtn" class="button-mini active-target" type="button">🎯 Decision (t0 = ${node.t0.toFixed(1)}s)</button>
              <button id="jumpActionBtn" class="button-mini" type="button">⏩ +1s Action</button>
              <button id="jumpOutcomeBtn" class="button-mini" type="button">🏁 +3s Outcome</button>
            </div>
          </div>

          <!-- 3. Retrospective Outcome Card (Shown only if Stage 2 is unlocked) -->
          ${!this.stage1Locked && ep.retrospective ? `
            <div class="retrospective-panel">
              <div class="retro-header">
                <span class="retro-badge">STAGE 2 RETROSPECTIVE (HINDSIGHT)</span>
                <span class="retro-warning">${ep.retrospective.warning}</span>
              </div>
              <p class="retro-summary">${ep.retrospective.summary}</p>
              <div class="retro-events-list">
                ${(ep.retrospective.events || []).map(ev => `
                  <div class="retro-event-item">
                    <span class="retro-time">${ev.t.toFixed(1)}s</span>
                    <span class="retro-desc">${escapeHTML(ev.label)}</span>
                  </div>
                `).join('')}
              </div>
              <div class="retro-consequence">
                <strong>Observed Match Result:</strong> ${ep.retrospective.consequence}
              </div>
            </div>
          ` : ''}

          <!-- 4. Structured Coaching Lesson Panel -->
          <div class="coaching-lesson-grid">
            <!-- Left Column: Assessment & Feasible Alternatives -->
            <div class="lesson-left-col">
              <!-- Assessment Card -->
              <div class="coaching-card assessment-card">
                <div class="card-eyebrow">
                  <span>TACTICAL ASSESSMENT</span>
                  <div class="stance-wrap">
                    <span class="stance-pill stance-${coaching.stance || 'neutral'}">
                      ${(coaching.stance || 'neutral').toUpperCase()}
                    </span>
                    <span class="confidence-pill conf-${coaching.confidence || 'hypothesis'}">
                      ${coaching.confidence === 'fact' ? 'VERIFIED TELEMETRY' : 'EVALUATED HYPOTHESIS'}
                    </span>
                  </div>
                </div>
                <h4 class="assessment-headline">${escapeHTML(coaching.headline || node.label)}</h4>
                <p class="assessment-desc">${escapeHTML(coaching.assessment || node.summary)}</p>

                <!-- Actionable Takeaway -->
                <div class="takeaway-box">
                  <div class="takeaway-title">💡 ACTIONABLE TAKEAWAY</div>
                  <p class="takeaway-text">${escapeHTML(coaching.takeaway || 'Evaluate your recovery route and spacing relative to your teammate.')}</p>
                </div>
              </div>

              <!-- Feasible Alternatives Section -->
              <div class="coaching-card alternatives-card">
                <div class="card-eyebrow">
                  <span>FEASIBLE ALTERNATIVES AT t0</span>
                  <span class="card-subtitle">Physically reachable actions at cutoff</span>
                </div>

                <div class="alternatives-list">
                  ${(coaching.feasible_alternatives || []).length > 0 ? (coaching.feasible_alternatives || []).map(alt => `
                    <div class="alt-item risk-${alt.risk_level || 'medium'}">
                      <div class="alt-item-header">
                        <strong class="alt-action">${escapeHTML(alt.action)}</strong>
                        <span class="feasibility-badge badge-${alt.feasibility}">${escapeHTML(alt.feasibility_label)}</span>
                      </div>
                      <p class="alt-desc">${escapeHTML(alt.description)}</p>
                      <div class="alt-tradeoffs">
                        <div class="tradeoff-pro">✓ <strong>Pro:</strong> ${escapeHTML(alt.pros)}</div>
                        <div class="tradeoff-con">✗ <strong>Risk:</strong> ${escapeHTML(alt.cons)}</div>
                      </div>
                    </div>
                  `).join('') : `
                    <p class="muted">No explicit counterfactual alternatives calculated for this intermediate node.</p>
                  `}
                </div>
              </div>

              <!-- Earlier Contributing Decisions (Causal Hypotheses) -->
              ${(coaching.earlier_contributors || []).length > 0 ? `
                <div class="coaching-card earlier-contributors-card">
                  <div class="card-eyebrow">
                    <span>EARLIER CONTRIBUTING CHOICES</span>
                    <span class="card-subtitle">Causal links leading to this moment</span>
                  </div>
                  <div class="hypotheses-list">
                    ${(coaching.earlier_contributors || []).map(h => `
                      <div class="hypothesis-item">
                        <div class="hyp-header">
                          <span class="hyp-id">${h.id}</span>
                          ${h.earlier_node ? `
                            <button class="jump-earlier-btn button-mini" data-jump-node="${h.earlier_node}" type="button">
                              Inspect ${h.earlier_node} Setup ↗
                            </button>
                          ` : ''}
                        </div>
                        <p class="hyp-question">${escapeHTML(h.question)}</p>
                        <small class="hyp-caveat">${escapeHTML(h.not_established)}</small>
                      </div>
                    `).join('')}
                  </div>
                </div>
              ` : ''}
            </div>

            <!-- Right Column: Evidence Inspector & Follow-Up Q&A -->
            <div class="lesson-right-col">
              <!-- Observed Evidence Chips Panel -->
              <div class="coaching-card evidence-summary-card">
                <div class="card-eyebrow">
                  <span>SUPPORTING EVIDENCE (CLICK TO INSPECT)</span>
                  <span class="card-subtitle">${(coaching.observed_evidence || []).length} telemetry items at t0</span>
                </div>

                <div class="evidence-chips-grid">
                  ${(coaching.observed_evidence || []).map(ev => `
                    <button class="evidence-chip kind-${ev.kind || 'observation'}"
                            data-evidence-id="${ev.id}" type="button"
                            title="Click to inspect telemetry details">
                      <span class="chip-id">${ev.id}</span>
                      <strong class="chip-label">${ev.label}</strong>
                      <span class="chip-val">${escapeHTML(ev.value)}</span>
                    </button>
                  `).join('')}
                </div>

                <!-- Unobservable Unknowns Drawer -->
                <details class="unknowns-details">
                  <summary>Disclosed Unobservable Factors (${(coaching.unknowns || []).length})</summary>
                  <ul class="unknowns-list">
                    ${(coaching.unknowns || []).map(u => `<li>${escapeHTML(u)}</li>`).join('')}
                  </ul>
                </details>
              </div>

              <!-- Follow-Up Conversational Q&A Panel -->
              <div class="coaching-card qa-card">
                <div class="card-eyebrow">
                  <span>ASK THE COACH</span>
                  <span class="card-subtitle">Stage-1 evidence-grounded responses</span>
                </div>

                <!-- Quick Prompt Pills -->
                <div class="quick-prompts">
                  <button class="prompt-pill" data-prompt="Why was challenging here worse than shadowing?" type="button">
                    Why challenge instead of shadow?
                  </button>
                  <button class="prompt-pill" data-prompt="Could my teammate have covered this ball?" type="button">
                    Could my teammate cover?
                  </button>
                  <button class="prompt-pill" data-prompt="What would change if I had 50+ boost?" type="button">
                    What if I had more boost?
                  </button>
                  <button class="prompt-pill" data-prompt="What should I practice to improve this decision?" type="button">
                    What should I practice?
                  </button>
                </div>

                <!-- Chat History Window -->
                <div id="coachingChatList" class="coaching-chat-list">
                  <!-- Populated by renderChatList -->
                </div>

                <!-- Chat Input Row -->
                <form id="coachingChatForm" class="chat-input-form">
                  <input id="coachingChatInput" class="chat-input" type="text"
                         placeholder="Ask a question about this decision..."
                         autocomplete="off" />
                  <button id="coachingSendBtn" class="button button-primary chat-send-btn" type="submit">
                    Send
                  </button>
                </form>
              </div>
            </div>
          </div>
        </div>
      `;

      this.renderChatList();
      this.bindDynamicEvents();
    }

    /**
     * Render Chat Message Stream
     */
    renderChatList() {
      const chatList = $('coachingChatList');
      if (!chatList) return;

      chatList.innerHTML = this.chatHistory.map(msg => {
        const isCoach = msg.sender === 'coach';
        return `
          <div class="chat-message ${isCoach ? 'msg-coach' : 'msg-user'}">
            <div class="msg-header">
              <span class="msg-sender">${isCoach ? '🎯 AI COACH' : '👤 YOU'}</span>
            </div>
            <div class="msg-body">${this.formatMarkdown(msg.text)}</div>
            ${msg.citations && msg.citations.length > 0 ? `
              <div class="msg-citations">
                <span class="cit-label">Cited Evidence:</span>
                ${msg.citations.map(c => `
                  <button class="citation-tag" data-citation-id="${c}" type="button">[${c}]</button>
                `).join('')}
              </div>
            ` : ''}
          </div>
        `;
      }).join('');

      if (this.isAnswering) {
        const typing = document.createElement('div');
        typing.className = 'chat-message msg-coach msg-typing';
        typing.innerHTML = '<span class="typing-indicator">Analyzing pre-decision evidence...</span>';
        chatList.append(typing);
      }

      chatList.scrollTop = chatList.scrollHeight;
    }

    formatMarkdown(text) {
      if (!text) return '';
      return escapeHTML(text)
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\n\n/g, '<br/><br/>')
        .replace(/\[(E\.[a-zA-Z0-9_.]+|D\.[a-zA-Z0-9_.]+|N\d\/[a-zA-Z0-9_.]+)\]/g, '<span class="inline-cit">[$1]</span>');
    }

    /**
     * Render the Evidence Inspector Modal
     */
    renderInspectorModal() {
      const item = this.inspectedEvidence;
      if (!item) return;

      let modal = $('evidenceInspectorModal');
      if (!modal) {
        modal = document.createElement('div');
        modal.id = 'evidenceInspectorModal';
        modal.className = 'evidence-modal-backdrop';
        document.body.append(modal);
      }

      const kindClass = item.kind || 'unknown';
      const kindLabel = {
        observation: 'OBSERVED TELEMETRY (Raw Replay)',
        derived: 'DERIVED / ESTIMATED MODEL',
        hypothesis: 'HYPOTHETICAL EXPLORATION',
        unknown: 'UNOBSERVABLE FACTOR',
        retrospective: 'STAGE 2 RETROSPECTIVE (Hindsight)'
      }[kindClass] || 'OBSERVED TELEMETRY';

      modal.innerHTML = `
        <div class="evidence-modal-dialog" role="dialog" aria-modal="true" aria-labelledby="modalEvidenceTitle">
          <div class="modal-header">
            <div>
              <span class="modal-epistemic-tag tag-${kindClass}">${kindLabel}</span>
              <h3 id="modalEvidenceTitle" class="modal-title">${escapeHTML(item.label || item.id)}</h3>
            </div>
            <button id="closeInspectorBtn" class="modal-close-btn" type="button" aria-label="Close inspector">✕</button>
          </div>

          <div class="modal-body">
            <div class="inspector-value-box">
              <span class="val-label">Recorded Value at t0:</span>
              <strong class="val-number">${escapeHTML(item.value)}</strong>
              ${item.unit ? `<span class="val-unit">(${escapeHTML(item.unit)})</span>` : ''}
            </div>

            <div class="inspector-details-table">
              <div class="detail-row">
                <span class="detail-key">Evidence ID:</span>
                <span class="detail-val"><code>${escapeHTML(item.id)}</code></span>
              </div>
              <div class="detail-row">
                <span class="detail-key">Cutoff Timestamp:</span>
                <span class="detail-val">${(this.activeNode ? this.activeNode.t0 : 0).toFixed(2)}s</span>
              </div>
              <div class="detail-row">
                <span class="detail-key">Provenance Source:</span>
                <span class="detail-val">${escapeHTML(item.provenance || 'Unknown')}</span>
              </div>
              <div class="detail-row">
                <span class="detail-key">Description:</span>
                <span class="detail-val">${escapeHTML(item.description || item.label)}</span>
              </div>
            </div>

            <div class="epistemic-explanation">
              <strong>Epistemic Guarantee:</strong>
              ${kindClass === 'observation'
                ? 'Replay-derived observation. Source freshness and tactical interpretation remain independently unverified.'
                : 'Evidence classification is provisional; derived or unknown values must not be treated as direct observation.'}
            </div>
          </div>

          <div class="modal-footer">
            <button id="modalDoneBtn" class="button button-primary" type="button">Close Inspector</button>
          </div>
        </div>
      `;

      $('closeInspectorBtn').onclick = () => this.closeInspectorModal();
      $('modalDoneBtn').onclick = () => this.closeInspectorModal();
      modal.onclick = e => {
        if (e.target === modal) this.closeInspectorModal();
      };
    }

    /**
     * Bind DOM events
     */
    bindEvents() {
      // Keyboard esc for modal
      document.addEventListener('keydown', e => {
        if (e.key === 'Escape' && this.inspectedEvidence) {
          this.closeInspectorModal();
        }
      });
    }

    bindDynamicEvents() {
      // Episode select
      const epSelect = $('episodeSelect');
      if (epSelect) {
        epSelect.onchange = e => this.selectEpisode(e.target.value);
      }

      // Firewall toggle
      const fwBtn = $('toggleFirewallBtn');
      if (fwBtn) {
        fwBtn.onclick = () => this.toggleStage1Firewall();
      }

      // Step navigation
      const stepPrev = $('stepPrevBtn');
      if (stepPrev) stepPrev.onclick = () => this.navigateEarlier();

      const stepNext = $('stepNextBtn');
      if (stepNext) stepNext.onclick = () => this.navigateLater();

      // Node buttons
      const nodeBtns = this.container.querySelectorAll('.step-node');
      nodeBtns.forEach(btn => {
        btn.onclick = () => {
          const nid = btn.getAttribute('data-node-id');
          this.selectNode(nid);
        };
      });

      // Jump replay buttons
      const jBefore = $('jumpBeforeBtn');
      if (jBefore) jBefore.onclick = () => this.stepTime(-2.0);

      const jDecision = $('jumpDecisionBtn');
      if (jDecision) jDecision.onclick = () => this.stepTime(0);

      const jAction = $('jumpActionBtn');
      if (jAction) jAction.onclick = () => this.stepTime(1.0);

      const jOutcome = $('jumpOutcomeBtn');
      if (jOutcome) jOutcome.onclick = () => this.stepTime(3.0);

      // Jump earlier from hypothesis card
      const jumpEarlierBtns = this.container.querySelectorAll('.jump-earlier-btn');
      jumpEarlierBtns.forEach(btn => {
        btn.onclick = () => {
          const targetNode = btn.getAttribute('data-jump-node');
          this.selectNode(targetNode);
        };
      });

      // Evidence chips click -> Inspector modal
      const chipBtns = this.container.querySelectorAll('.evidence-chip');
      chipBtns.forEach(btn => {
        btn.onclick = () => this.inspectEvidenceReference(btn.getAttribute('data-evidence-id'));
      });

      // Quick prompt pills
      const promptPills = this.container.querySelectorAll('.prompt-pill');
      promptPills.forEach(pill => {
        pill.onclick = () => {
          const prompt = pill.getAttribute('data-prompt');
          this.askQuestion(prompt);
        };
      });

      // Chat form submit
      const chatForm = $('coachingChatForm');
      if (chatForm) {
        chatForm.onsubmit = e => {
          e.preventDefault();
          const input = $('coachingChatInput');
          if (input && input.value) {
            const val = input.value;
            input.value = '';
            this.askQuestion(val);
          }
        };
      }

      // Clickable citations in chat
      const citTags = this.container.querySelectorAll('.citation-tag');
      citTags.forEach(tag => {
        tag.onclick = () => this.inspectEvidenceReference(tag.getAttribute('data-citation-id'));
      });
    }

    /**
     * Add live extracted episode from decision cases
     */
    addLiveEpisode(episode) {
      if (!episode) return;
      const existing = this.episodes.findIndex(e => e.episode_id === episode.episode_id);
      if (existing >= 0) {
        this.episodes[existing] = episode;
      } else {
        this.episodes.unshift(episode);
      }
      this.selectEpisode(episode.episode_id);
    }
  }

  // Export to global scope
  global.CoachingExperienceController = CoachingExperienceController;

})(typeof window !== 'undefined' ? window : this);
