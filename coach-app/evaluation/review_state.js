/* Replay Lab blind review contract, dependency-free in browsers and Node.
 * This is input validation, not certification of semantic event provenance.
 * All reviewer-facing strings must be rendered using textContent.
 */
(function (root) {
  "use strict";
  const DECISIONS = new Set(["sound", "risk", "tradeoff", "indeterminate"]);
  const ASSESSMENTS = new Set(["sound", "risk", "tradeoff", "abstain"]);
  const DECISION_KEYS = new Set(["review_id", "situation_type", "t0", "pre_decision_evidence", "review_question"]);
  const QUALITY_KEYS = new Set(["review_id", "case_ref", "assessment", "cited_evidence", "title", "advice", "review_question"]);
  const EVIDENCE_KEYS = new Set(["key", "claim", "event_time_s", "finalized_through_s", "source", "source_quality"]);
  const BLOCKED_SOURCES = new Set(["post_decision", "post_decision_outcome", "retrospective", "future_derived", "outcome"]);
  const PLATFORM_ID = /\b(?:Steam|Epic|PSN|PsyNet|Xbox):[A-Za-z0-9_-]{7,}\b/i;

  function ensure(condition, message) {
    if (!condition) throw new Error(message);
  }
  function finite(n) { return typeof n === "number" && Number.isFinite(n); }
  function onlyKeys(obj, allowed, what) {
    ensure(obj !== null && typeof obj === "object" && !Array.isArray(obj), what + " must be an object");
    for (const key of Object.keys(obj)) ensure(allowed.has(key), what + " has forbidden field: " + key);
  }
  function validText(text, what, max) {
    ensure(typeof text === "string" && text.length > 0 && text.length <= max, what + " is missing or too long");
  }
  function validatePackets(stage, records) {
    ensure(stage === "decision" || stage === "quality", "Unknown review stage");
    ensure(Array.isArray(records) && records.length > 0 && records.length <= 1000,
      "Expected a JSON array with 1–1000 review packets");
    const ids = new Set();
    for (const item of records) {
      onlyKeys(item, stage === "decision" ? DECISION_KEYS : QUALITY_KEYS, "Review packet");
      const id = item.review_id;
      ensure(typeof id === "string" && new RegExp(stage === "decision" ? "^C[0-9]{5,}$" : "^Q[0-9]{5,}$").test(id),
        "Packet has an invalid anonymous review_id");
      ensure(!ids.has(id), "Duplicate packet ID " + id);
      ids.add(id);
      validText(item.review_question, id + " review question", 2000);
      if (stage === "decision") {
        validText(item.situation_type, id + " situation type", 120);
        ensure(finite(item.t0) && item.t0 >= 0, id + " has invalid decision time");
        ensure(Array.isArray(item.pre_decision_evidence) && item.pre_decision_evidence.length > 0 &&
          item.pre_decision_evidence.length <= 100, id + " needs 1–100 evidence records");
        const evidenceIds = new Set();
        for (const ev of item.pre_decision_evidence) {
          onlyKeys(ev, EVIDENCE_KEYS, id + " evidence");
          validText(ev.key, id + " evidence key", 140);
          validText(ev.claim, id + " evidence claim", 4000);
          validText(ev.source, id + " source", 200);
          ensure(!BLOCKED_SOURCES.has(ev.source.toLowerCase()), id + " retrospective source not admissible");
          ensure(["high", "medium", "low", "unknown"].includes(ev.source_quality),
            id + " invalid source quality");
          ensure(finite(ev.event_time_s) && ev.event_time_s >= 0 && ev.event_time_s <= item.t0,
            id + " contains an observation after the decision");
          ensure(finite(ev.finalized_through_s) && ev.finalized_through_s >= ev.event_time_s &&
            ev.finalized_through_s <= item.t0, id + " contains future-derived evidence");
          ensure(!evidenceIds.has(ev.key), id + " has duplicate evidence keys");
          evidenceIds.add(ev.key);
        }
        ensure(!PLATFORM_ID.test(JSON.stringify(item)), id + " contains a recognizable platform ID");
      } else {
        ensure(typeof item.case_ref === "string" && /^C[0-9]{5,}$/.test(item.case_ref),
          id + " has invalid reference to decision packet");
        ensure(ASSESSMENTS.has(item.assessment), id + " invalid anonymous assessment");
        ensure(Array.isArray(item.cited_evidence) && item.cited_evidence.every(x => typeof x === "string") &&
          item.cited_evidence.length <= 100, id + " invalid citations");
        ensure(typeof item.title === "string" && item.title.length <= 500, id + " invalid title");
        ensure(typeof item.advice === "string" && item.advice.length <= 10000, id + " invalid advice");
        ensure(!PLATFORM_ID.test(JSON.stringify(item)), id + " contains a recognizable platform ID");
      }
    }
    return records;
  }
  function validatePairing(decisions, quality) {
    validatePackets("decision", decisions);
    validatePackets("quality", quality);
    const known = new Set(decisions.map(r => r.review_id));
    for (const item of quality) {
      ensure(known.has(item.case_ref), item.review_id + " refers to an absent decision packet");
    }
  }
  function cleanReviewerId(raterId) {
    ensure(typeof raterId === "string" && /^[A-Za-z0-9_-]{2,60}$/.test(raterId),
      "Enter a reviewer code of 2–60 letters, digits, underscores or hyphens");
    return raterId;
  }
  function validateAnswer(stage, answer) {
    if (stage === "decision") {
      ensure(answer && DECISIONS.has(answer.verdict), "Choose a decision verdict");
    } else {
      ensure(answer && Number.isInteger(answer.factual_errors) && answer.factual_errors >= 0 &&
        answer.factual_errors <= 100, "Enter 0–100 factual errors");
      ensure(Number.isInteger(answer.unsupported_claims) && answer.unsupported_claims >= 0 &&
        answer.unsupported_claims <= 100, "Enter 0–100 unsupported claims");
      ensure(typeof answer.useful === "boolean", "Choose whether the feedback is useful");
    }
    ensure(answer.note === undefined ||
      (typeof answer.note === "string" && answer.note.length <= 2000),
      "Optional reviewer note must be at most 2000 characters");
  }
  function compileSubmissions(stage, records, answers, raterId, complete) {
    validatePackets(stage, records);
    cleanReviewerId(raterId);
    ensure(answers && typeof answers === "object", "Answer collection must be an object");
    const known = new Set(records.map(r => r.review_id));
    for (const id of Object.keys(answers)) ensure(known.has(id), "Unknown answer ID " + id);
    const output = [];
    for (const packet of records) {
      const answer = answers[packet.review_id];
      if (!answer) {
        ensure(!complete, "Review every case before final export; missing " + packet.review_id);
        continue;
      }
      validateAnswer(stage, answer);
      const data = stage === "decision"
        ? { verdict: answer.verdict }
        : { factual_errors: answer.factual_errors, unsupported_claims: answer.unsupported_claims,
            useful: answer.useful };
      const result = { review_id: packet.review_id, rater_id: raterId, ...data };
      if (typeof answer.note === "string" && answer.note.trim()) result.note = answer.note.trim();
      output.push(result);
    }
    return output;
  }
  function importSubmissions(stage, records, submissions, raterId) {
    validatePackets(stage, records);
    cleanReviewerId(raterId);
    ensure(Array.isArray(submissions), "Imported answers must be a JSON array");
    const known = new Set(records.map(x => x.review_id));
    const answers = Object.create(null);
    for (const item of submissions) {
      ensure(item && typeof item === "object" && !Array.isArray(item), "Invalid answer record");
      ensure(known.has(item.review_id), "Imported answer is not in this packet: " + item.review_id);
      ensure(item.rater_id === raterId, "Imported answers use a different reviewer ID");
      ensure(!answers[item.review_id], "Duplicate imported answer for " + item.review_id);
      const answer = stage === "decision"
        ? { verdict: item.verdict }
        : { factual_errors: item.factual_errors, unsupported_claims: item.unsupported_claims,
            useful: item.useful };
      if (typeof item.note === "string") answer.note = item.note;
      validateAnswer(stage, answer);
      answers[item.review_id] = answer;
    }
    return answers;
  }
  function countCompleted(records, answers) {
    return records.reduce((count, item) => count + (answers[item.review_id] ? 1 : 0), 0);
  }
  const api = { validatePackets, validatePairing, cleanReviewerId,
    compileSubmissions, importSubmissions, countCompleted };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ReplayReviewCore = api;
})(typeof globalThis === "undefined" ? this : globalThis);
