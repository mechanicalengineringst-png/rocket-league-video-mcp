/** Pure helpers so the viewer UI can be tested without WebGL or WASM. */
export function formatTime(input) {
  const t = Number.isFinite(input) ? Math.max(0, input) : 0;
  const minutes = Math.floor(t / 60);
  const seconds = Math.floor(t % 60);
  const hundredths = Math.min(99, Math.floor((t - Math.floor(t)) * 100 + 1e-7));
  return String(minutes).padStart(2, '0') + ':' +
    String(seconds).padStart(2, '0') + '.' +
    String(hundredths).padStart(2, '0');
}

export function clampTime(input, duration) {
  if (!Number.isFinite(input)) return 0;
  return Math.min(Math.max(0, input), Math.max(0, Number(duration) || 0));
}

export function timelineMarkers(replay, limit = 25) {
  if (!Array.isArray(replay?.timelineEvents)) return [];
  const kinds = new Set(['goal', 'save', 'demo', 'shot', 'bookmark']);
  return replay.timelineEvents
    .filter(event => event && kinds.has(String(event.kind ?? '').toLowerCase()))
    .map(event => ({
      kind: String(event.kind).toLowerCase(),
      time: Number(event.time),
      label: String(event.label || event.kind),
    }))
    .filter(event => Number.isFinite(event.time) && event.time >= 0)
    .sort((a,b) => a.time - b.time)
    .slice(0,limit);
}
