"""Evidence-bound question answering about a reviewed moment (Round 4, Phase 3).

The contract has three parts, and only the middle one may use a language model:

1. ``build_packet``: deterministic retrieval. It turns a finding into numbered
   evidence items (``E1``…) with their kind, and lists what is not established.
   Retrospective items (what happened after t0) get ``R`` ids and are marked.
2. An answerer. ``answer_deterministically`` writes the answer from the packet
   with no model; an LLM may replace it using ``llm_prompt``.
3. ``validate_answer``: every sentence must cite packet ids, every number must
   appear in a cited item, retrospective citations must be worded as later
   events, and intent, blame or probability words are rejected unless the packet
   itself contains them. An answer that fails is replaced by the deterministic one.

Nothing in this module reads telemetry directly; it only sees the packet.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .tactical_analysis import Finding, challenge_verdict, shot_verdict

QUESTION_TYPES = ("why_flagged", "alternative_feasibility", "teammate_actions", "opponent_actions",
                  "what_would_change", "recurring_patterns")

INTENT_WORDS = re.compile(r"\b(wanted|intended|intend|tried to|meant to|decided to|chose to|was trying|panicked|lazy)\b", re.I)
BLAME_WORDS = re.compile(r"\b(mistake|error|bad decision|wrong|should have|blunder|fault)\b", re.I)
PROB_WORDS = re.compile(r"(\d+\s*%|\bprobabilit|\bchance of|\blikelihood|\bodds\b|\bxg\b)", re.I)
RETRO_MARKERS = re.compile(r"\b(later|afterwards|after t0|then|next|followed|retrospective)\b", re.I)
NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?")


@dataclass
class Item:
    id: str
    kind: str            # fact | derived | interpretation | alternative | unknown | retrospective | factor
    text: str
    tags: list[str] = field(default_factory=list)


@dataclass
class Packet:
    question_type: str
    question: str
    case_id: str
    t0: float
    situation: str
    verdict: str
    headline: str
    items: list[Item]
    not_established: list[str]

    def by_id(self) -> dict[str, Item]:
        return {i.id: i for i in self.items}

    def to_dict(self) -> dict[str, Any]:
        return {"question_type": self.question_type, "question": self.question, "case_id": self.case_id,
                "t0": self.t0, "situation": self.situation, "verdict": self.verdict, "headline": self.headline,
                "items": [vars(i) for i in self.items], "not_established": list(self.not_established)}


def _tags_for(text: str, inputs: list[str]) -> list[str]:
    tags = []
    low = text.lower()
    if "mate" in inputs or "teammate" in low:
        tags.append("teammate")
    if any(i not in ("ball", "focus", "mate") for i in inputs) or "defender" in low or "opponent" in low or "attacker" in low:
        tags.append("opponent")
    if "focus" in inputs or "challenger" in low:
        tags.append("focus")
    return tags


def what_would_change(finding: Finding) -> list[str]:
    """Flip each known verdict factor and report which flips change the verdict. Pure, no telemetry."""
    f = dict(finding.factors)
    if not f:
        return []
    rule = (lambda x: challenge_verdict(x)) if finding.situation == "first_man_challenge" else \
        (lambda x: shot_verdict(x, finding.reviewed_action)) if finding.situation == "possession_shot_opportunity" else None
    if rule is None:
        return []
    base = rule(f)
    out = []
    for k, v in f.items():
        label = k.replace("_", " ")
        if v is None:
            for guess in (True, False):
                alt = rule(dict(f, **{k: guess}))
                out.append(f"'{label}' is unknown; if it were {guess}, the verdict would be {alt} instead of {base}."
                           if alt != base else f"'{label}' is unknown; setting it to {guess} leaves the verdict at {base}.")
            continue
        alt = rule(dict(f, **{k: not v}))
        if alt != base:
            out.append(f"If '{label}' were {not v} instead of {v}, the verdict would be {alt} instead of {base}.")
    if not any("would be" in o for o in out):
        out.append(f"No single factor change alters the verdict ({base}).")
    return out


def build_packet(finding: Finding, question_type: str, question: str = "",
                 retrospective: list[str] | None = None, history: list[Finding] | None = None) -> Packet:
    """Deterministic retrieval of the evidence a question may use."""
    if question_type not in QUESTION_TYPES:
        raise ValueError(f"question_type must be one of {QUESTION_TYPES}")
    items: list[Item] = []
    n = 0

    def add(kind: str, text: str, tags: list[str] | None = None, prefix: str = "E") -> None:
        nonlocal n
        n += 1
        items.append(Item(f"{prefix}{n}", kind, text, tags or []))

    for s in finding.statements:
        add(s.kind, s.text + ("" if not s.assumptions else f" (Assumes: {'; '.join(s.assumptions)})"),
            _tags_for(s.text, s.inputs))
    for a in finding.alternatives:
        add("alternative", f"Alternative '{a.action}': {a.feasibility}. {a.basis}"
            + ("" if not a.unknowns else f" Unknown: {'; '.join(a.unknowns)}"), ["alternative"])
    for u in finding.unknowns:
        add("unknown", u, _tags_for(u, []))
    if finding.reviewed_action:
        add("retrospective", f"Retrospective label of what happened next: '{finding.reviewed_action}'. Not known at t0 and not intent.",
            ["retrospective"], prefix="R")
    for r in retrospective or []:
        add("retrospective", r, ["retrospective"], prefix="R")
    if question_type == "what_would_change":
        for line in what_would_change(finding):
            add("factor", line, ["factor"])
    if question_type == "recurring_patterns":
        for line in recurring_patterns(history or [finding]):
            add("factor", line, ["pattern"])

    keep = {
        "why_flagged": lambda i: i.kind in ("fact", "derived", "interpretation", "unknown", "retrospective"),
        "alternative_feasibility": lambda i: i.kind in ("alternative", "unknown") or i.kind == "derived",
        "teammate_actions": lambda i: "teammate" in i.tags or i.kind == "unknown" and "teammate" in i.text.lower(),
        "opponent_actions": lambda i: "opponent" in i.tags or i.kind == "unknown" and "opponent" in i.text.lower(),
        "what_would_change": lambda i: i.kind in ("factor", "unknown"),
        "recurring_patterns": lambda i: i.kind == "factor",
    }[question_type]
    return Packet(question_type, question, finding.case_id, finding.t0, finding.situation, finding.verdict,
                  finding.headline, [i for i in items if keep(i)], list(finding.not_established))


def recurring_patterns(findings: list[Finding], min_count: int = 3) -> list[str]:
    """Counts with denominators. A pattern needs at least ``min_count`` occurrences."""
    by_sit = Counter(f.situation for f in findings)
    out = []
    for (sit, verdict), k in sorted(Counter((f.situation, f.verdict) for f in findings).items()):
        if verdict in ("abstain", "situation_brief"):
            continue
        line = f"{verdict} in {k} of {by_sit[sit]} reviewed {sit.replace('_', ' ')} moments"
        out.append(line + ("." if k >= min_count else f" (fewer than {min_count}: not a pattern)."))
    factor_counts: Counter = Counter()
    for f in findings:
        for key, v in f.factors.items():
            if v is True:
                factor_counts[(f.situation, key)] += 1
    for (sit, key), k in sorted(factor_counts.items()):
        if k >= min_count:
            out.append(f"'{key.replace('_', ' ')}' was present in {k} of {by_sit[sit]} {sit.replace('_', ' ')} moments.")
    if not out:
        out.append(f"No recurring pattern: {len(findings)} moment(s) reviewed, none repeated {min_count}+ times.")
    return out


# ---------- answers ----------

def answer_deterministically(p: Packet) -> dict[str, Any]:
    """Model-free answer: the packet's own sentences, each citing itself."""
    sentences = []
    lead = {
        "why_flagged": f"This moment is shown as '{p.headline}' ({p.verdict}).",
        "alternative_feasibility": "Alternatives at t0, with how feasible the telemetry suggests they were:",
        "teammate_actions": "What the telemetry shows about the teammate at t0:",
        "opponent_actions": "What the telemetry shows about the opponents at t0:",
        "what_would_change": "How the verdict depends on its inputs:",
        "recurring_patterns": "Across the reviewed moments:",
    }[p.question_type]
    for it in p.items:
        text = it.text
        if it.kind == "retrospective" and not RETRO_MARKERS.search(text):
            text = "Afterwards: " + text
        sentences.append({"text": text, "cites": [it.id]})
    if not sentences:
        return {"lead": lead, "sentences": [], "abstain": True,
                "not_established": p.not_established, "answerer": "deterministic",
                "note": "The telemetry packet has nothing that answers this question."}
    return {"lead": lead, "sentences": sentences, "abstain": False, "not_established": p.not_established,
            "answerer": "deterministic"}


def llm_prompt(p: Packet) -> str:
    """Prompt for an optional model answerer. The model sees only the packet."""
    lines = [f"[{i.id}] ({i.kind}) {i.text}" for i in p.items]
    return (
        "You are a Rocket League coach explaining a replay moment. Use ONLY the evidence below.\n"
        "Rules: (1) Every sentence ends with the ids it relies on, like [E2][E5]. (2) Use no number that is not in a "
        "cited item. (3) Items with R ids happened after the decision: say so ('later', 'afterwards') and never use "
        "them as reasons the player could have known. (4) Do not describe intent, blame, or any probability or "
        "percentage. (5) If the evidence does not answer the question, say what is unknown and stop. "
        "(6) These are not established and must not be asserted: " + "; ".join(p.not_established) + "\n"
        "Return JSON: {\"sentences\": [{\"text\": str, \"cites\": [id, ...]}], \"abstain\": bool}\n\n"
        f"Situation: {p.situation} at t0={p.t0:.2f}s. Verdict: {p.verdict} — {p.headline}\n"
        f"Question ({p.question_type}): {p.question}\n\nEvidence:\n" + "\n".join(lines)
    )


def _numbers(text: str) -> set[float]:
    return {abs(float(x)) for x in NUMBER.findall(text)}


def validate_answer(answer: dict[str, Any], p: Packet) -> list[str]:
    """Return a list of contract violations; empty means the answer may be shown."""
    problems: list[str] = []
    known = p.by_id()
    sentences = answer.get("sentences")
    if not isinstance(sentences, list):
        return ["Answer has no sentence list."]
    if not sentences and not answer.get("abstain"):
        problems.append("Empty answer without abstaining.")
    for k, s in enumerate(sentences, 1):
        text, cites = str(s.get("text", "")), list(s.get("cites") or [])
        if not cites:
            problems.append(f"Sentence {k} cites nothing.")
            continue
        bad = [c for c in cites if c not in known]
        if bad:
            problems.append(f"Sentence {k} cites ids not in the packet: {bad}.")
            continue
        cited_text = " ".join(known[c].text for c in cites)
        allowed = _numbers(cited_text) | {0.0, 1.0, 2.0}   # "two attackers", "1v2"
        extra = [x for x in _numbers(text) if not any(abs(x - a) <= max(0.051, 0.01 * a) for a in allowed)]
        if extra:
            problems.append(f"Sentence {k} uses numbers not in its cited evidence: {sorted(extra)}.")
        if any(known[c].kind == "retrospective" for c in cites) and not RETRO_MARKERS.search(text):
            problems.append(f"Sentence {k} cites a later event without saying it happened later.")
        for rx, what in ((INTENT_WORDS, "intent"), (BLAME_WORDS, "blame"), (PROB_WORDS, "probability")):
            m = rx.search(text)
            if m and not rx.search(cited_text):
                problems.append(f"Sentence {k} asserts {what} ('{m.group(0)}') that the evidence does not contain.")
        for ne in p.not_established:
            core = ne.rstrip(".").lower()
            if core and core in text.lower() and "not established" not in text.lower() and "unknown" not in text.lower():
                problems.append(f"Sentence {k} asserts something listed as not established: '{ne}'.")
    return problems


def answer(finding: Finding, question_type: str, question: str = "", model_answer: dict[str, Any] | None = None,
           history: list[Finding] | None = None) -> dict[str, Any]:
    """Build the packet, validate a model answer if given, and fall back to the deterministic answer."""
    p = build_packet(finding, question_type, question, history=history)
    result: dict[str, Any] = {"packet": p.to_dict()}
    if model_answer is not None:
        problems = validate_answer(model_answer, p)
        if not problems:
            result["answer"] = dict(model_answer, answerer="model", validated=True)
            return result
        result["rejected_model_answer"] = {"answer": model_answer, "problems": problems}
    result["answer"] = answer_deterministically(p)
    return result
