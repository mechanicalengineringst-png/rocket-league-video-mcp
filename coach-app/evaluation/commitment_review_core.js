/* Pure commitment timing-review validation. Classic browser script + Node harness.
 * All fields are local, not sent to a remote server. Do not put source identity,
 * predictor labels or future outcomes in a review packet.
 */
(function (root) {
  "use strict";
  const CHOICES = ["challenge", "shadow", "fake", "other", "unclear"];
  const CONFIDENCES = ["low", "medium", "high"];
  const PACKET_FIELDS = ["review_id", "clip_file", "clip_duration_s", "focus_hint"];
  const ANSWER_FIELDS = ["review_id", "rater_id", "choice", "mark_type",
                         "earliest_s", "latest_s", "confidence", "note"];

  function check(ok, message) { if (!ok) throw Error(message); }
  function finite(v) { return typeof v === "number" && Number.isFinite(v); }
  function fields(record, allowed, context) {
    check(record && typeof record === "object" && !Array.isArray(record),
      context + " must be an object");
    check(Object.keys(record).length === allowed.length &&
      Object.keys(record).every(k => allowed.includes(k)),
      context + " has missing or forbidden fields");
  }
  function reviewerCode(value) {
    check(typeof value === "string" && /^[A-Za-z0-9_-]{2,60}$/.test(value),
      "Use a reviewer code of 2–60 letters, digits, hyphens or underscores");
    return value;
  }
  function validatePackets(packets) {
    check(Array.isArray(packets) && packets.length >= 1 &&
      packets.length <= 100, "Expected 1–100 review packets");
    const ids = new Set(), names = new Set();
    for (const packet of packets) {
      fields(packet, PACKET_FIELDS, "Review packet");
      const id = packet.review_id;
      check(typeof id === "string" && /^T[0-9]{5}$/.test(id),
        "Invalid anonymous review ID");
      check(!ids.has(id), "Duplicate review ID " + id); ids.add(id);
      check(typeof packet.clip_file === "string" &&
        packet.clip_file === id + (packet.clip_file.endsWith(".mp4") ? ".mp4" : ".webm") &&
        (packet.clip_file.endsWith(".mp4") || packet.clip_file.endsWith(".webm")),
        id + " must use an anonymized .mp4 or .webm clip filename");
      check(!names.has(packet.clip_file), id + " duplicate clip filename");
      names.add(packet.clip_file);
      check(finite(packet.clip_duration_s) &&
        packet.clip_duration_s > 0 && packet.clip_duration_s <= 30,
        id + " invalid clip duration");
      check(typeof packet.focus_hint === "string" &&
        packet.focus_hint.length > 0 && packet.focus_hint.length <= 160,
        id + " missing focus description");
      check(!/\b(?:Steam|Epic|PSN|PsyNet|Xbox):[A-Za-z0-9_-]{7,}\b/i.test(
        packet.focus_hint), id + " leaks a platform identifier");
    }
    return packets;
  }
  function validateAnswer(record, packet) {
    fields(record, ANSWER_FIELDS, "Review answer");
    check(record.review_id === packet.review_id, "Answer ID doesn't match packet");
    reviewerCode(record.rater_id);
    check(CHOICES.includes(record.choice), "Choose what the player did");
    check(CONFIDENCES.includes(record.confidence), "Choose a confidence level");
    check(typeof record.note === "string" && record.note.length <= 2000,
      "Note must be 2000 characters or fewer");
    check(record.mark_type === "interval" || record.mark_type === "unobservable",
      "Choose a commitment interval or 'not observable'");
    if (record.mark_type === "interval") {
      check(finite(record.earliest_s) && finite(record.latest_s) &&
        record.earliest_s >= 0 && record.latest_s >= record.earliest_s &&
        record.latest_s <= packet.clip_duration_s + 0.001,
        "Commitment interval must fit inside this clip");
    } else {
      check(record.earliest_s === null && record.latest_s === null,
        "An unobservable case must not have fabricated timestamps");
    }
    return record;
  }
  function compile(packets, answers, who, complete) {
    validatePackets(packets); reviewerCode(who);
    check(answers && typeof answers === "object" && !Array.isArray(answers),
      "Review answers must be keyed by review ID");
    const known = new Set(packets.map(x => x.review_id));
    for (const id of Object.keys(answers)) check(known.has(id), "Unknown answer ID " + id);
    const out = [];
    for (const packet of packets) {
      if (!answers[packet.review_id]) {
        check(!complete, "Complete every case before final export; missing " + packet.review_id);
        continue;
      }
      const ans = {...answers[packet.review_id], review_id:packet.review_id, rater_id:who};
      validateAnswer(ans, packet);
      out.push(ans);
    }
    return out;
  }
  function restore(packets, submissions, who) {
    validatePackets(packets); reviewerCode(who);
    check(Array.isArray(submissions), "Saved annotations must be a JSON array");
    const known = Object.fromEntries(packets.map(x => [x.review_id, x]));
    const answers = Object.create(null);
    for (const row of submissions) {
      check(row && known[row.review_id], "Imported answer ID not in this packet");
      check(!answers[row.review_id], "Duplicate saved review ID " + row.review_id);
      validateAnswer(row, known[row.review_id]);
      check(row.rater_id === who, "Saved annotations belong to a different reviewer");
      const {review_id, rater_id, ...answer} = row;
      answers[row.review_id] = answer;
    }
    return answers;
  }
  const api = {validatePackets, validateAnswer, compile, restore, reviewerCode,
    CHOICES, CONFIDENCES};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ReplayCommitmentReviewCore = api;
})(typeof globalThis === "undefined" ? this : globalThis);
