import test from 'node:test';
import assert from 'node:assert/strict';
import { createReplayAudioEngine } from '../src/audio-engine.js';

// Minimal Web Audio API Mock for Node testing
class MockGain {
  constructor() {
    this.gain = {
      value: 1,
      setValueAtTime: (v) => { this.gain.value = v; },
      setTargetAtTime: (v) => { this.gain.value = v; },
      exponentialRampToValueAtTime: (v) => { this.gain.value = v; },
    };
  }
  connect() {}
}

class MockAudioContext {
  constructor() {
    this.state = 'running';
    this.currentTime = 10.0;
    this.sampleRate = 44100;
    this.destination = {};
  }
  createGain() { return new MockGain(); }
  createOscillator() {
    return {
      type: 'sine',
      frequency: {
        setValueAtTime() {},
        exponentialRampToValueAtTime() {},
      },
      connect() {},
      start() {},
      stop() {},
    };
  }
  createBiquadFilter() {
    return {
      type: 'bandpass',
      frequency: { setValueAtTime() {} },
      Q: { setValueAtTime() {} },
      connect() {},
    };
  }
  createBuffer(channels, size, rate) {
    return {
      getChannelData: () => new Float32Array(size),
    };
  }
  createBufferSource() {
    return {
      connect() {},
      start() {},
      stop() {},
      disconnect() {},
    };
  }
  resume() { return Promise.resolve(); }
  close() {
    this.state = 'closed';
    return Promise.resolve();
  }
}

globalThis.AudioContext = MockAudioContext;

test('audio engine starts muted by default', () => {
  const engine = createReplayAudioEngine();
  assert.equal(engine.isMuted(), true, 'Must start muted for browser policy compliance');
  assert.equal(engine.getVolume(), 0.5);

  engine.setMuted(false);
  assert.equal(engine.isMuted(), false);

  engine.setVolume(0.8);
  assert.equal(engine.getVolume(), 0.8);
  engine.dispose();
});

test('audio engine volume is clamped between 0 and 1', () => {
  const engine = createReplayAudioEngine();
  assert.equal(engine.setVolume(1.5), 1.0);
  assert.equal(engine.setVolume(-0.5), 0.0);
  assert.equal(engine.setVolume(0.7), 0.7);
  engine.dispose();
});

test('sound triggers do not crash when muted or active', () => {
  const engine = createReplayAudioEngine();
  engine.ensureContext();

  // Trigger while muted (should be silent no-op)
  assert.doesNotThrow(() => engine.playBallHit(1800));
  assert.doesNotThrow(() => engine.playSupersonicBoom());
  assert.doesNotThrow(() => engine.playGoalHorn());
  assert.doesNotThrow(() => engine.updateBoostState(true));
  assert.doesNotThrow(() => engine.updateBoostState(false));

  // Trigger while unmuted
  engine.setMuted(false);
  assert.doesNotThrow(() => engine.playBallHit(2200));
  assert.doesNotThrow(() => engine.playSupersonicBoom());
  assert.doesNotThrow(() => engine.playGoalHorn());
  assert.doesNotThrow(() => engine.updateBoostState(true));
  assert.doesNotThrow(() => engine.updateBoostState(false));

  engine.dispose();
});
