"""Browser review contract and standalone local interface smoke checks."""
from pathlib import Path
import shutil
import subprocess

import pytest


BASE = Path(__file__).resolve().parents[1] / "evaluation"


def test_local_video_review_interface_remains_standalone_and_masked():
    html = (BASE / "commitment_review.html").read_text(encoding="utf-8")
    assert '<script src="./commitment_review_core.js"></script>' in html
    for field in ("packetFile", "videoFiles", "reviewer", "clip", "markEarliest",
                  "markLatest", "unobservable", "choice", "confidence",
                  "exportDraft", "exportFinal", "savedFile"):
        assert 'id="' + field + '"' in html
    assert 'input class="file" id="videoFiles"' in html
    assert 'URL.createObjectURL' in html
    assert 'core.validateAnswer(record,packet)' in html
    assert '.textContent=' in html
    assert 'fetch(' not in html
    assert 'http://' not in html and 'https://' not in html
    assert 'detector_choice' not in html
    assert 'source_t0_s' not in html


def test_commitment_review_js_contract_round_trip_and_rejects_leaks():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node not available for offline browser-script contract")
    program = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
// The browser includes a classic .js script. This repository uses ESM,
// so wrap that source in a module object without changing browser semantics.
const source = fs.readFileSync(process.argv[1], "utf8");
const wrapper = vm.runInThisContext("(function(module) {\n" + source +
  "\nreturn module.exports;\n})", {filename:process.argv[1]});
const api = wrapper({exports:{}});
const packet = {
  review_id:"T00001", clip_file:"T00001.mp4",
  clip_duration_s:4.5, focus_hint:"Follow the outlined blue car"
};
assert.deepEqual(api.validatePackets([packet]), [packet]);
const answer = {
  choice:"fake", mark_type:"interval",
  earliest_s:1.45, latest_s:2.8, confidence:"low", note:"Aerial control unclear"
};
const out = api.compile([packet],{T00001:answer},"rater-01",true);
assert.equal(out.length,1);
assert.deepEqual(out[0],{review_id:"T00001",rater_id:"rater-01",...answer});
assert.deepEqual(Object.assign({},api.restore([packet],out,"rater-01")),
  {T00001:answer});
const fails = (fn,re) => assert.throws(fn,re);
fails(()=>api.validatePackets([{...packet,detector_choice:"challenge"}]),
  /forbidden fields/);
fails(()=>api.validatePackets([{...packet,clip_file:"../real-name.mp4"}]),
  /anonymized/);
fails(()=>api.validatePackets([packet,packet]),/Duplicate/);
fails(()=>api.validatePackets([{...packet,focus_hint:"Steam:76561198000000000"}]),
  /platform identifier/);
fails(()=>api.compile([packet],{},"rater-01",true),
  /Complete every case/);
fails(()=>api.compile([packet],{T00001:{...answer,latest_s:5}},
  "rater-01",true),/fit inside/);
fails(()=>api.compile([packet],{T00001:{...answer,latest_s:Infinity}},
  "rater-01",true),/fit inside/);
fails(()=>api.compile([packet],{T00001:{...answer,earliest_s:2.9}},
  "rater-01",true),/fit inside/);
const unknown={...answer,mark_type:"unobservable",earliest_s:null,latest_s:null};
assert.equal(api.compile([packet],{T00001:unknown},"rater-01",true)[0].mark_type,
  "unobservable");
fails(()=>api.compile([packet],{T00001:{...unknown,earliest_s:2}},
  "rater-01",true),/must not have fabricated/);
fails(()=>api.restore([packet],out,"other-rater"),/different reviewer/);
fails(()=>api.restore([packet],[...out,...out],"rater-01"),/Duplicate/);
console.log("commitment browser contract passed");
"""
    completed = subprocess.run(
        [node, "-e", program, str(BASE / "commitment_review_core.js")],
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "commitment browser contract passed" in completed.stdout
