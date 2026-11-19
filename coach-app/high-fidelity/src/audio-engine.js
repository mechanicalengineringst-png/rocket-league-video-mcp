/**
 * Replay Lab Procedural Tactical Audio Engine
 *
 * Synthesizes zero-asset authentic auditory feedback using the Web Audio API:
 * - Thruster / boost filtered noise whoosh
 * - Supersonic sonic boom
 * - Ball contact impact thump
 * - Goal explosion & horn
 *
 * Muted by default to respect browser autoplay policies; toggleable with 1-click.
 */

export function createReplayAudioEngine() {
  let audioCtx = null;
  let masterGain = null;
  let muted = true;
  let volume = 0.5;

  let boostSource = null;
  let boostFilter = null;
  let boostGain = null;
  let isBoosting = false;

  let lastTouchTime = -1;
  let lastBoomTime = -1;

  function ensureContext() {
    if (audioCtx) return audioCtx;
    const AudioContext = globalThis.AudioContext || globalThis.webkitAudioContext;
    if (!AudioContext) return null;

    try {
      audioCtx = new AudioContext();
      masterGain = audioCtx.createGain();
      masterGain.gain.setValueAtTime(muted ? 0 : volume, audioCtx.currentTime);
      masterGain.connect(audioCtx.destination);
    } catch (e) {
      console.warn('[AudioEngine] Could not initialize Web Audio:', e);
    }
    return audioCtx;
  }

  function setMuted(val) {
    muted = Boolean(val);
    if (!audioCtx) return muted;
    if (audioCtx.state === 'suspended' && !muted) {
      audioCtx.resume().catch(() => {});
    }
    if (masterGain) {
      masterGain.gain.setTargetAtTime(muted ? 0 : volume, audioCtx.currentTime, 0.05);
    }
    return muted;
  }

  function setVolume(val) {
    volume = Math.max(0, Math.min(1, Number(val) || 0));
    if (masterGain && !muted && audioCtx) {
      masterGain.gain.setTargetAtTime(volume, audioCtx.currentTime, 0.05);
    }
    return volume;
  }

  /** Synthesize continuous filtered noise for boost thruster */
  function startBoostLoop() {
    if (isBoosting || !audioCtx || muted) return;
    try {
      const bufferSize = audioCtx.sampleRate * 2;
      const noiseBuffer = audioCtx.createBuffer(1, bufferSize, audioCtx.sampleRate);
      const output = noiseBuffer.getChannelData(0);
      for (let i = 0; i < bufferSize; i++) {
        output[i] = Math.random() * 2 - 1;
      }

      boostSource = audioCtx.createBufferSource();
      boostSource.buffer = noiseBuffer;
      boostSource.loop = true;

      boostFilter = audioCtx.createBiquadFilter();
      boostFilter.type = 'bandpass';
      boostFilter.frequency.setValueAtTime(450, audioCtx.currentTime);
      boostFilter.Q.setValueAtTime(1.8, audioCtx.currentTime);

      boostGain = audioCtx.createGain();
      boostGain.gain.setValueAtTime(0.001, audioCtx.currentTime);
      boostGain.gain.exponentialRampToValueAtTime(0.35, audioCtx.currentTime + 0.1);

      boostSource.connect(boostFilter);
      boostFilter.connect(boostGain);
      boostGain.connect(masterGain);

      boostSource.start();
      isBoosting = true;
    } catch (e) {
      // Ignore audio synthesis errors
    }
  }

  function stopBoostLoop() {
    if (!isBoosting || !boostGain || !audioCtx) return;
    try {
      boostGain.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + 0.08);
      setTimeout(() => {
        try {
          boostSource?.stop();
          boostSource?.disconnect();
        } catch (_) {}
        isBoosting = false;
        boostSource = null;
      }, 100);
    } catch (_) {
      isBoosting = false;
    }
  }

  /** Trigger ball impact percussive thump */
  function playBallHit(velocity = 1200) {
    if (muted || !ensureContext()) return;
    const now = audioCtx.currentTime;
    if (now - lastTouchTime < 0.12) return; // Debounce
    lastTouchTime = now;

    try {
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();

      const speedNorm = Math.min(1.0, Math.max(0.2, velocity / 2500));
      const freq = 120 + speedNorm * 180; // 120Hz - 300Hz impact pitch

      osc.type = 'sine';
      osc.frequency.setValueAtTime(freq, now);
      osc.frequency.exponentialRampToValueAtTime(35, now + 0.09);

      gain.gain.setValueAtTime(0.4 * speedNorm, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.11);

      osc.connect(gain);
      gain.connect(masterGain);

      osc.start(now);
      osc.stop(now + 0.12);
    } catch (_) {}
  }

  /** Trigger sonic boom when car reaches supersonic speed */
  function playSupersonicBoom() {
    if (muted || !ensureContext()) return;
    const now = audioCtx.currentTime;
    if (now - lastBoomTime < 1.5) return; // Cooldown
    lastBoomTime = now;

    try {
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();

      osc.type = 'triangle';
      osc.frequency.setValueAtTime(90, now);
      osc.frequency.exponentialRampToValueAtTime(25, now + 0.25);

      gain.gain.setValueAtTime(0.65, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.35);

      osc.connect(gain);
      gain.connect(masterGain);

      osc.start(now);
      osc.stop(now + 0.38);
    } catch (_) {}
  }

  /** Trigger goal celebration chord */
  function playGoalHorn() {
    if (muted || !ensureContext()) return;
    const now = audioCtx.currentTime;

    try {
      const freqs = [130.81, 164.81, 196.0]; // C3 Major triad
      for (const f of freqs) {
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();

        osc.type = 'sawtooth';
        osc.frequency.setValueAtTime(f, now);

        gain.gain.setValueAtTime(0.18, now);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 1.2);

        osc.connect(gain);
        gain.connect(masterGain);

        osc.start(now);
        osc.stop(now + 1.3);
      }
    } catch (_) {}
  }

  return {
    ensureContext,
    setMuted,
    toggleMute() {
      const next = !muted;
      setMuted(next);
      return !next;
    },
    isMuted: () => muted,
    setVolume,
    getVolume: () => volume,
    updateBoostState(active) {
      if (active && !isBoosting) startBoostLoop();
      else if (!active && isBoosting) stopBoostLoop();
    },
    startBoost() {
      if (!isBoosting) startBoostLoop();
    },
    stopBoost() {
      if (isBoosting) stopBoostLoop();
    },
    playBallHit,
    playBallImpact(velocity = 0.5) {
      playBallHit(velocity);
    },
    playSupersonicBoom,
    playSupersonic() {
      playSupersonicBoom();
    },
    playGoalHorn,
    dispose() {
      stopBoostLoop();
      if (audioCtx && audioCtx.state !== 'closed') {
        audioCtx.close().catch(() => {});
      }
      audioCtx = null;
    }
  };
}
