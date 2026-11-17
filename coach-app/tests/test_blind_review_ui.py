"""Smoke-test the dependency-free reviewer UI and its JavaScript data contract.

GitHub Actions has Node preinstalled on hosted runners, but pytest can run
without it. Real browser layout and accessibility still need manual QA.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1] / "evaluation"


def test_offline_blind_reviewer_html_has_both_sequential_stages():
    html = (ROOT / "review.html").read_text(encoding="utf-8")
    assert '<script src="./review_state.js"></script>' in html
    assert 'id="freezeDecisions"' in html
    assert 'id="loadQuality"' in html
    assert 'id="saveQualityAnswer"' in html
    assert 'id="exportQuality"' in html
    assert 'modelCitations' in html
    assert 'state.decisionFrozen = true' in html
    assert 'state.decisionFrozen = false' in html
    assert 'core.validatePairing(state.decisions, records)' in html
    assert 'textContent = ' in html
    assert 'fetch(' not in html
    assert 'http://' not in html and 'https://' not in html


def test_javascript_review_contract_has_fail_closed_packet_validation():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node not installed; JavaScript contract still available for browser")
    program = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
// The browser page loads review_state.js as a classic standalone script.
// The repository's type=module prevents Node require() from returning its
// script-global API; evaluate it as a script in the current JS realm instead.
vm.runInThisContext(fs.readFileSync(process.argv[1], "utf8"), {filename:process.argv[1]});
const contract = globalThis.ReplayReviewCore;

const decision = {
    review_id: "C00001", situation_type: "first_man_challenge",
    t0: 20.0, review_question: "Was this justified?",
    pre_decision_evidence: [{
        key: "coverage", claim: "Teammate positioned deeper; coverage uncertain.",
        event_time_s: 19.93, finalized_through_s: 19.94,
        source: "replay", source_quality: "high"
    }]
};
const quality = {
    review_id: "Q00001", case_ref: "C00001", assessment: "risk",
    cited_evidence: ["coverage"], title: "Uncertain challenge",
    advice: "Check recovery before committing.", review_question: "Useful?"
};
const rejects = (fn, pattern) => assert.throws(fn, pattern);
assert.equal(contract.validatePackets("decision", [decision]).length, 1);
assert.equal(contract.validatePackets("quality", [quality]).length, 1);
assert.doesNotThrow(() => contract.validatePairing([decision], [quality]));

rejects(() => contract.compileSubmissions("decision", [decision], {}, "reviewer-a", true),
  /Review every case/);
const answers = {"C00001": {verdict:"tradeoff",note:"Need actual recovery data"}};
const compiled = contract.compileSubmissions("decision", [decision], answers, "reviewer-a", true);
assert.deepEqual(compiled, [{
  review_id:"C00001",rater_id:"reviewer-a",
  verdict:"tradeoff",note:"Need actual recovery data"
}]);
assert.equal(contract.countCompleted([decision], answers), 1);
assert.deepEqual(Object.assign({}, contract.importSubmissions("decision",
  [decision],compiled,"reviewer-a")),answers);
rejects(() => contract.importSubmissions("decision",[decision],compiled,"wrong-reviewer"),
  /different reviewer ID/);
rejects(() => contract.cleanReviewerId("A"), /reviewer code/);

const qa = {Q00001: {factual_errors:0,unsupported_claims:1,useful:false}};
assert.deepEqual(contract.compileSubmissions("quality",[quality],qa,"reviewer-a",true),
  [{review_id:"Q00001",rater_id:"reviewer-a",
    factual_errors:0,unsupported_claims:1,useful:false}]);
rejects(() => contract.compileSubmissions("quality",[quality],
  {Q00001:{factual_errors:0,unsupported_claims:1,useful:null}},"reviewer-a",true),
  /Choose whether/);

const mutated = (x, field, value) => Object.assign({}, x, {[field]:value});
rejects(() => contract.validatePackets("decision",
  [mutated(decision,"post_decision_outcome","goal")]), /forbidden field/);
rejects(() => contract.validatePackets("decision",
  [mutated(decision,"pre_decision_evidence",
    [mutated(decision.pre_decision_evidence[0],"finalized_through_s",20.1)])]),
  /future-derived/);
rejects(() => contract.validatePackets("decision",
  [mutated(decision,"pre_decision_evidence",
    [mutated(decision.pre_decision_evidence[0],"source","retrospective")])]),
  /retrospective source/);
rejects(() => contract.validatePackets("decision",
  [mutated(decision,"pre_decision_evidence",
    [mutated(decision.pre_decision_evidence[0],"claim","Steam:76561198000000000")])]),
  /platform ID/);
rejects(() => contract.validatePackets("quality",
  [mutated(quality,"system_id","my-model")]), /forbidden field/);
rejects(() => contract.validatePairing([decision],
  [mutated(quality,"case_ref","C99999")]), /absent decision packet/);
rejects(() => contract.validatePackets("decision",[decision,decision]), /Duplicate packet/);
console.log("offline review contract passed");
"""
    completed = subprocess.run(
        [node, "-e", program, str(ROOT / "review_state.js")],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "offline review contract passed" in completed.stdout
