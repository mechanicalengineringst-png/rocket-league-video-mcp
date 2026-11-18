/* Replay Lab — Decision Lens V0.
 *
 * Deterministic inspection of observed match data at and after a player-chosen
 * decision time. No model requests, tactical grades, counterfactual predicted
 * trajectories, cloud storage, or replay mutation.
 *
 * IMPORTANT TEMPORAL BOUNDARY: the decision anchor uses the LAST recorded
 * sample AT OR BEFORE t0. The actual +2s sample and trajectory are returned
 * separately and must remain hidden until the user explicitly reveals them.
 */
(function (root) {
  'use strict';
  const isNum = Number.isFinite;
  const MAX_STALENESS_S = 0.20;
  const BEFORE_S = 3;
  const AFTER_S = 2;

  function floorFrame(frames, time) {
    if (!Array.isArray(frames) || !frames.length || !isNum(time)) return null;
    let lo = 0, hi = frames.length;
    while (lo < hi) {
      const mid = Math.floor((lo + hi) / 2);
      if (frames[mid] && isNum(frames[mid].t) && frames[mid].t <= time)
        lo = mid + 1;
      else hi = mid;
    }
    return lo > 0 ? frames[lo - 1] : null;
  }
  function validPoint(car) {
    return !!car && isNum(car.x) && isNum(car.y) && isNum(car.z) &&
      car.demolished !== true;
  }
  function distance2D(a, b) {
    if (!validPoint(a) || !validPoint(b)) return null;
    return Math.hypot(a.x - b.x, a.y - b.y);
  }
  function speedOf(car) {
    const velocity = car?.velocity;
    return Array.isArray(velocity) && velocity.length >= 3 &&
      velocity.slice(0, 3).every(isNum) ? Math.hypot(...velocity.slice(0, 3)) : null;
  }
  function freshSnapshot(replay, time, playerId) {
    const frame = floorFrame(replay?.frames, time);
    if (!frame || !isNum(frame.t) || time - frame.t < -1e-8 ||
        time - frame.t > MAX_STALENESS_S) return null;
    const roster = Array.isArray(replay.players) ? replay.players : [];
    const focus = roster.find(p => p?.id === playerId);
    if (!focus || !['blue', 'orange'].includes(focus.team)) return null;
    const cars = frame.cars && typeof frame.cars === 'object' ? frame.cars : {};
    const focalCar = cars[playerId];
    const ball = frame.ball;
    const teammate = roster.find(p => p && p.team === focus.team && p.id !== playerId);
    const opponents = roster.filter(p => p && p.team !== focus.team &&
      ['blue', 'orange'].includes(p.team));
    const other = teammate ? cars[teammate.id] : null;
    const validBall = validPoint(ball);
    const opponentDistances = validBall ? opponents.map(p => distance2D(cars[p.id], ball))
      .filter(isNum) : [];
    const dots = [];
    if (validBall) dots.push({role:'ball',x:ball.x,y:ball.y,z:ball.z});
    for (const p of roster.slice(0, 8)) {
      const car = cars[p.id];
      if (!validPoint(car)) continue;
      dots.push({
        role:p.id === playerId ? 'focus' : p.team === focus.team ? 'teammate' : 'opponent',
        team:p.team, x:car.x, y:car.y, z:car.z
      });
    }
    return {
      sampleTime:frame.t,
      ageMs:Math.round(Math.max(0, time - frame.t) * 1000),
      dots,
      metrics:{
        focusBall2D:distance2D(focalCar, ball),
        teammateSeparation2D:distance2D(focalCar, other),
        opponentBallNearest2D:opponentDistances.length ? Math.min(...opponentDistances) : null,
        focusBoost:validPoint(focalCar) && isNum(focalCar.boost) ? focalCar.boost : null,
        focusSpeed:speedOf(focalCar),
        ballHeight:validBall ? ball.z : null
      },
      complete:validPoint(focalCar) && validBall && validPoint(other) &&
        opponents.length === 2 && opponentDistances.length === opponents.length
    };
  }
  function collectTrace(replay, start, end, playerId) {
    const frames = replay.frames;
    const result={focus:[],ball:[]};
    if (!isNum(start) || !isNum(end) || end <= start) return result;
    // A 30 Hz replay has ~60 frames in two seconds; cap work defensively
    // for unusual sample rates without replacing the actual trajectory
    // with hypothetical straight-line interpolation.
    const samples=[];
    for (const frame of frames) {
      if (!frame || !isNum(frame.t) || frame.t <= start || frame.t > end) continue;
      samples.push(frame);
    }
    const stride=Math.max(1,Math.ceil(samples.length/100));
    for (let i=0;i<samples.length;i++) {
      if (i%stride !== 0 && i !== samples.length-1) continue;
      const f=samples[i];
      const c=f.cars?.[playerId];
      if (validPoint(c)) result.focus.push({t:f.t,x:c.x,y:c.y});
      if (validPoint(f.ball)) result.ball.push({t:f.t,x:f.ball.x,y:f.ball.y});
    }
    return result;
  }
  function buildWindow(replay, playerId, t0, beforeS=BEFORE_S, afterS=AFTER_S) {
    const fs=replay?.frames;
    if (!Array.isArray(fs) || !fs.length || !isNum(t0) ||
        !isNum(beforeS) || !isNum(afterS) || beforeS < 0 ||
        afterS < 0 || beforeS > 8 || afterS > 8) return null;
    const min=fs[0]?.t, max=fs[fs.length-1]?.t;
    if (!isNum(min) || !isNum(max) || t0 < min || t0 > max || max < min) return null;
    const anchor=freshSnapshot(replay,t0,playerId);
    if (!anchor) return null; // Do not invent a snapshot across missing telemetry.
    const start=Math.max(min,t0-beforeS);
    const end=Math.min(max,t0+afterS);
    // The after snapshot is separately labeled and should never be used for
    // pre-decision judging or revealed automatically by the view.
    const after=(end > t0 + 0.05) ? freshSnapshot(replay,end,playerId) : null;
    return {
      schema:'ReplayDecisionLensV0',
      t0,start,end,
      anchor,after,
      recordedAfterTrace:after ? collectTrace(replay,t0,end,playerId) : {focus:[],ball:[]},
      temporalBoundary:'anchor_at_or_before_t0_future_recording_separate',
      source:'recorded_replay_telemetry_not_simulated',
      predictionsMade:false,
      coachingGradeAssigned:false
    };
  }
  function loopNext(now, dt, speed, window) {
    if (!window || !isNum(now) || !isNum(dt) || !isNum(speed) ||
        dt < 0 || speed <= 0 || window.end-window.start < 0.1) return null;
    const span=window.end-window.start;
    // User seeked outside the loop: enter from the start, preserving an
    // accurate source-backed time rather than jumping to a fake event.
    const at=now < window.start || now >= window.end ? window.start : now;
    return window.start + ((at - window.start + dt*speed) % span);
  }
  const API=Object.freeze({
    buildWindow, freshSnapshot, floorFrame, loopNext,
    distance2D, MAX_STALENESS_S, BEFORE_S, AFTER_S
  });
  root.ReplayLabDecisionLens=API;
  if (typeof module !== 'undefined' && module.exports) module.exports=API;
})(typeof globalThis !== 'undefined' ? globalThis : this);
