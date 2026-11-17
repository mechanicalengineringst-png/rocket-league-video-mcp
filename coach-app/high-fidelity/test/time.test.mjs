import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatTime, clampTime, timelineMarkers } from '../src/time.js';

test('display time is stable across minutes and hundredths', () => {
  assert.equal(formatTime(0),'00:00.00');
  assert.equal(formatTime(59.999),'00:59.99');
  assert.equal(formatTime(61.25),'01:01.25');
  assert.equal(formatTime(600),'10:00.00');
  assert.equal(formatTime(NaN),'00:00.00');
});

test('scrubs cannot seek before zero, beyond replay duration or into NaN', () => {
  assert.equal(clampTime(-8,420),0);
  assert.equal(clampTime(444,420),420);
  assert.equal(clampTime(21,420),21);
  assert.equal(clampTime(NaN,420),0);
});

test('moment markers sort native timestamped events and discard unsupported kinds',()=>{
  const events = timelineMarkers({timelineEvents:[
    {kind:'touch',time:40},
    {kind:'goal',time:90,label:'Blue scores'},
    {kind:'save',time:30},
    {kind:'demo',time:50},
    {kind:'goal',time:Infinity}
  ]});
  assert.deepEqual(events.map(e=>e.kind),['save','demo','goal']);
  assert.deepEqual(events.map(e=>e.time),[30,50,90]);
  assert.equal(events[2].label,'Blue scores');
  assert.deepEqual(timelineMarkers({}),[]);
});
