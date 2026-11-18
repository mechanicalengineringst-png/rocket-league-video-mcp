/** Pure utilities for syncing the main tactical map with the HD replay viewer.
 *
 * These functions make no network requests or hidden game-process calls.
 * Transport/authentication (same-origin window and session checks) is handled
 * by the two UI entry points. An ID match must be established independently:
 * different replay parsers can produce different player ID formats.
 */

export function validateExternalControl(value, sessionId, previousSeq, duration) {
  if (!value || typeof value !== 'object' ||
      value.type !== 'replay-lab:hd-control' ||
      value.sessionId !== sessionId ||
      !Number.isSafeInteger(value.seq) || value.seq <= previousSeq ||
      typeof value.playing !== 'boolean' ||
      typeof value.time !== 'number' || !Number.isFinite(value.time) ||
      value.time < 0 || value.time > duration + 0.001 ||
      typeof value.speed !== 'number' || !Number.isFinite(value.speed) ||
      value.speed < 0.25 || value.speed > 2 ||
      typeof value.focusName !== 'string' || !value.focusName ||
      value.focusName.length > 100 ||
      (value.focusTeam !== 'blue' && value.focusTeam !== 'orange')) {
    return null;
  }
  return {
    seq: value.seq, time: value.time, speed: value.speed,
    playing: value.playing, focusName: value.focusName,
    focusTeam: value.focusTeam,
  };
}

export function resolveFocusedPlayer(players, name, team) {
  if (!Array.isArray(players) || typeof name !== 'string') return null;
  const norm = x => x.trim().toLocaleLowerCase();
  const match = players.filter(p =>
    typeof p?.name === 'string' && norm(p.name) === norm(name) &&
    ((p.team === 0 && team === 'blue') ||
     (p.team === 1 && team === 'orange') ||
     p.team === team)
  );
  return match.length === 1 ? match[0] : null;
}


/** DOM select values are strings. Player adapter IDs may be numeric; matching
 * them strictly without normalization silently leaves Follow Player detached.
 * Duplicate IDs are ambiguous, so never guess which car to follow.
 */
export function findSelectedPlayer(players, selectValue) {
  if(!Array.isArray(players)||selectValue==null)return null;
  const id=String(selectValue);
  const matched=players.filter(p=>p&&p.id!=null&&String(p.id)===id);
  return matched.length===1?matched[0]:null;
}

export function shouldCorrectReplayTime(target, actual, playing) {
  if (!Number.isFinite(actual) || !Number.isFinite(target)) return false;
  // Gentle drift check while both clocks play: avoid constant seek jitter.
  // When paused, seeks should be reflected promptly in both viewers.
  return Math.abs(target - actual) > (playing ? 0.6 : 0.06);
}

export function safeSessionId(raw) {
  return typeof raw === 'string' && /^[a-zA-Z0-9_-]{12,100}$/.test(raw);
}
