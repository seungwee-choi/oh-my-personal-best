#!/usr/bin/env python3
"""Injury tracking & return-to-run management → ``injuries.jsonl``.

The coach *advises* but this module is the single writer of injury state. Each injury is one
episode record carrying a deterministic return-to-run **phase ladder**
(rest → walk → walk_run → easy_only → build → full) that caps weekly load and restricts the
allowed workout types. ``snapshot(home)`` folds the active episode into one compact view so the
weekly-plan guardrail, the analysis agents, and run reviews all see the same injury context
without any of them touching the file.

Capture is deterministic and conservative: ``parse_mention`` only *proposes* an episode when a
body-part token co-occurs with a pain cue; persistence happens behind a confirm gate on the
surface (the coach asks before writing), never auto-written from free chat.

Part of the deterministic toolkit (stdlib only). Imported in-process by ``ompb_core`` and
usable from the CLI: ``python3 injury.py <command> ...`` (see ``--help``).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re as _re
import threading
import uuid
from typing import Dict, List, Optional

from ompb_env import resolve_home, local_today

_LOCK = threading.Lock()

# ── body-part taxonomy (single source for parsing · body map · display) ──────────
BODY_PARTS = {
    "knee": "무릎", "achilles": "아킬레스", "calf": "종아리", "hamstring": "햄스트링",
    "itb": "장경인대", "shin": "정강이", "plantar": "족저근막", "foot": "발",
    "hip": "고관절", "ankle": "발목", "quad": "허벅지 앞", "glute": "둔근", "back": "허리",
}
SIDES = {"left": "왼쪽", "right": "오른쪽", "both": "양쪽"}

# Keyword → canonical part. Matched longest-first so "족저근막"/"발바닥" beat "발",
# and "뒷벅지"/"허벅지" resolve before generic tokens.
_PART_KW = {
    "무릎": "knee", "knee": "knee",
    "아킬레스": "achilles", "achilles": "achilles",
    "종아리": "calf", "calf": "calf",
    "햄스트링": "hamstring", "뒷벅지": "hamstring", "hamstring": "hamstring",
    "장경인대": "itb", "it밴드": "itb", "itb": "itb",
    "정강이": "shin", "shin": "shin",
    "족저근막": "plantar", "발바닥": "plantar", "족저": "plantar", "plantar": "plantar",
    "발목": "ankle", "ankle": "ankle",
    "발": "foot", "foot": "foot",
    "고관절": "hip", "골반": "hip", "hip": "hip",
    "허벅지": "quad", "앞벅지": "quad", "quad": "quad",
    "둔근": "glute", "엉덩이": "glute", "glute": "glute",
    "허리": "back", "요추": "back", "back": "back",
}
_PART_KEYS = sorted(_PART_KW, key=len, reverse=True)  # longest-first match

_PAIN_RE = _re.compile(
    r"아파|아프|통증|쑤시|시큰|부상|다쳤|다침|결려|땡겨|당겨|injur|pain|hurt|sore", _re.I)
_SIDE_KW = {"왼": "left", "좌": "left", "left": "left",
            "오른": "right", "우측": "right", "right": "right",
            "양": "both", "both": "both"}
_SEVERITY_WORDS = [  # (keyword, 1-10) — checked in order, first hit wins
    ("못 견딜", 9), ("심하게", 7), ("심한", 7), ("많이", 7), ("꽤", 5), ("제법", 5),
    ("조금", 3), ("살짝", 3), ("약간", 3),
]


# ── return-to-run phase ladder ──────────────────────────────────────────────────
PHASES = ["rest", "walk", "walk_run", "easy_only", "build", "full"]
_PHASE_META = {
    "rest":      {"label": "완전 휴식",  "load_cap_pct": 0,   "allowed": {"rest", "cross"}},
    "walk":      {"label": "보행",       "load_cap_pct": 0,   "allowed": {"rest", "cross"}},
    "walk_run":  {"label": "걷기/뛰기",  "load_cap_pct": 30,  "allowed": {"recovery", "rest", "cross"}},
    "easy_only": {"label": "이지런만",   "load_cap_pct": 50,  "allowed": {"easy", "recovery", "rest", "cross"}},
    "build":     {"label": "점진 복귀",  "load_cap_pct": 80,  "allowed": {"easy", "long", "recovery", "rest", "cross"}},
    "full":      {"label": "정상 복귀",  "load_cap_pct": 100, "allowed": None},  # None = all types allowed
}
# Pain thresholds (0-10) for deterministic phase advancement on check-ins.
PAIN_OK = 2          # ≤ → pain-free enough to count toward advancing
PAIN_FLARE = 6       # ≥ → flare-up, step back a phase
ADVANCE_STREAK = 2   # consecutive ok check-ins needed to advance one phase


def _home(home: Optional[str]) -> str:
    return home or resolve_home(create=True)


def _today(today: Optional[_dt.date] = None) -> _dt.date:
    """Runner-local 'today' (KST) so onset offsets match the rest of the toolkit."""
    return today if today is not None else local_today()


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def phase_meta(phase: str) -> Dict:
    return _PHASE_META.get(phase, _PHASE_META["easy_only"])


def next_phase(phase: str) -> str:
    i = PHASES.index(phase) if phase in PHASES else PHASES.index("easy_only")
    return PHASES[min(i + 1, len(PHASES) - 1)]


def prev_phase(phase: str) -> str:
    i = PHASES.index(phase) if phase in PHASES else PHASES.index("easy_only")
    return PHASES[max(i - 1, 0)]


def _default_phase(severity: Optional[int]) -> str:
    """Conservative starting phase from reported severity (None → mild start)."""
    if severity is not None and severity >= 7:
        return "rest"
    if severity is not None and severity >= 4:
        return "walk_run"
    return "easy_only"


# ── deterministic capture: only PROPOSE, never auto-write ────────────────────────
def _parse_part(text: str) -> Optional[str]:
    low = text.lower()
    for kw in _PART_KEYS:
        if kw in low:
            return _PART_KW[kw]
    return None


def _parse_side(text: str) -> Optional[str]:
    low = text.lower()
    for kw, side in _SIDE_KW.items():
        if kw in low:
            return side
    return None


_KO_NUM = {"하루": 1, "한": 1, "이틀": 2, "사흘": 3, "나흘": 4, "닷새": 5}


def _parse_onset(text: str, today: _dt.date) -> str:
    """Onset date from relative cues; defaults to today. 'N일째' counts today as day N
    (onset = today-(N-1)); 'N일 전' is literally N days back."""
    if "그저께" in text or "그제" in text:
        return (today - _dt.timedelta(days=2)).isoformat()
    if "어제" in text:
        return (today - _dt.timedelta(days=1)).isoformat()
    m = _re.search(r"(\d+)\s*일\s*(째|전)", text)
    if m:
        n = int(m.group(1))
        back = n - 1 if m.group(2) == "째" else n
        return (today - _dt.timedelta(days=max(0, back))).isoformat()
    for word, n in _KO_NUM.items():
        if word in text and ("째" in text or "전" in text):
            back = n - 1 if "째" in text else n
            return (today - _dt.timedelta(days=max(0, back))).isoformat()
    return today.isoformat()


def _parse_severity(text: str) -> Optional[int]:
    m = _re.search(r"통증\s*(\d{1,2})|(\d{1,2})\s*/\s*10", text)
    if m:
        val = int(m.group(1) or m.group(2))
        return min(10, max(1, val))
    for word, val in _SEVERITY_WORDS:
        if word in text:
            return val
    return None


def parse_mention(text: str, today: Optional[_dt.date] = None) -> Optional[Dict]:
    """Propose an injury episode from free text, or None. Requires BOTH a body-part token
    and a pain cue so ordinary chat never trips it. The coach shows this as a confirm prompt;
    only on confirm does ``create_episode`` persist it."""
    s = (text or "").strip()
    if not s or not _PAIN_RE.search(s):
        return None
    part = _parse_part(s)
    if not part:
        return None
    side = _parse_side(s)
    severity = _parse_severity(s)
    label = (SIDES.get(side, "") + " " + BODY_PARTS[part]).strip()
    return {
        "body_part": part,
        "side": side,
        "label": label,
        "onset_date": _parse_onset(s, _today(today)),
        "severity": severity,
        "raw": s,
    }


# ── persistence (injuries.jsonl — one episode per line, atomic rewrite) ──────────
def _path(home: str) -> str:
    return os.path.join(home, "injuries.jsonl")


def _read(home: str) -> List[Dict]:
    try:
        with open(_path(home), encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _write(home: str, records: List[Dict]) -> None:
    path = _path(home)
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(tmp, path)  # atomic
    except OSError:
        pass  # best-effort; a failed write must never break a request


def create_episode(home: Optional[str], proposal: Dict) -> Dict:
    """Persist a new active episode from a parsed/confirmed proposal."""
    home = _home(home)
    severity = proposal.get("severity")
    phase = proposal.get("phase") or _default_phase(severity)
    part = proposal["body_part"]
    side = proposal.get("side")
    ep = {
        "id": f"inj-{uuid.uuid4().hex[:16]}",
        "body_part": part,
        "side": side,
        "label": proposal.get("label") or (SIDES.get(side, "") + " " + BODY_PARTS.get(part, part)).strip(),
        "onset_date": proposal.get("onset_date") or _today().isoformat(),
        "severity": severity,
        "status": "active",
        "phase": phase,
        "load_cap_pct": phase_meta(phase)["load_cap_pct"],
        "notes": ([{"date": _today().isoformat(), "text": proposal["note"]}]
                  if proposal.get("note") else []),
        "checkins": [],
        "onset_run_id": proposal.get("onset_run_id"),
        "resolved_date": None,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    with _LOCK:
        recs = _read(home)
        recs.append(ep)
        _write(home, recs)
    return ep


def get(home: Optional[str], episode_id: str) -> Optional[Dict]:
    for r in _read(_home(home)):
        if r.get("id") == episode_id:
            return r
    return None


def all_episodes(home: Optional[str]) -> List[Dict]:
    """Every episode, newest onset first."""
    recs = _read(_home(home))
    recs.sort(key=lambda r: (r.get("onset_date") or "", r.get("created_at") or ""), reverse=True)
    return recs


def active(home: Optional[str]) -> Optional[Dict]:
    """The current open episode (status active/recovering), most recent onset. None if clear."""
    open_eps = [r for r in all_episodes(home) if r.get("status") in ("active", "recovering")]
    return open_eps[0] if open_eps else None


def recent(home: Optional[str], days: int = 90) -> List[Dict]:
    cutoff = (_today() - _dt.timedelta(days=days)).isoformat()
    return [r for r in all_episodes(home) if (r.get("onset_date") or "") >= cutoff]


def injured_dates(home: Optional[str], start: str, end: str) -> set:
    """ISO dates within [start, end] covered by any episode (onset_date .. resolved_date,
    or .. today for still-open ones). Lets the calendar mark a planned run missed *during*
    an injury as recovery rather than a penalised skip (fairness)."""
    out: set = set()
    today = _today().isoformat()
    for ep in _read(_home(home)):
        onset = ep.get("onset_date")
        if not onset:
            continue
        ep_end = ep.get("resolved_date") or today
        lo, hi = max(onset, start), min(ep_end, end)
        try:
            cur, last = _dt.date.fromisoformat(lo), _dt.date.fromisoformat(hi)
        except ValueError:
            continue
        while cur <= last:
            out.add(cur.isoformat())
            cur += _dt.timedelta(days=1)
    return out


def _mutate(home: str, episode_id: str, fn) -> Optional[Dict]:
    """Apply ``fn(record)`` in place to one episode and persist. Returns the updated copy."""
    with _LOCK:
        recs = _read(home)
        updated = None
        for r in recs:
            if r.get("id") == episode_id:
                fn(r)
                r["updated_at"] = _now_iso()
                updated = dict(r)
                break
        if updated is not None:
            _write(home, recs)
    return updated


def add_note(home: Optional[str], episode_id: str, text: str,
             date: Optional[str] = None) -> Optional[Dict]:
    d = date or _today().isoformat()
    return _mutate(_home(home), episode_id,
                   lambda r: r.setdefault("notes", []).append({"date": d, "text": text}))


def set_phase(home: Optional[str], episode_id: str, phase: str) -> Optional[Dict]:
    if phase not in PHASES:
        return None

    def apply(r):
        r["phase"] = phase
        r["load_cap_pct"] = phase_meta(phase)["load_cap_pct"]
        r["status"] = "recovering"
    return _mutate(_home(home), episode_id, apply)


def advance_decision(phase: str, checkins: List[Dict]) -> str:
    """Pure deterministic ladder rule. A recent flare (pain ≥ PAIN_FLARE) steps back one
    phase; otherwise ADVANCE_STREAK consecutive pain-free *running* check-ins advance one.
    Returns the resulting phase (possibly unchanged)."""
    if not checkins:
        return phase
    last = checkins[-1]
    if max(last.get("pain_during", 0) or 0, last.get("pain_after", 0) or 0) >= PAIN_FLARE:
        return prev_phase(phase)
    tail = checkins[-ADVANCE_STREAK:]
    if len(tail) >= ADVANCE_STREAK and all(
        c.get("ran") and (c.get("pain_during", 0) or 0) <= PAIN_OK
        and (c.get("pain_after", 0) or 0) <= PAIN_OK for c in tail
    ):
        return next_phase(phase)
    return phase


def checkin(home: Optional[str], episode_id: str, *, pain_during: int = 0,
            pain_after: int = 0, ran: bool = False, note: str = "",
            date: Optional[str] = None) -> Optional[Dict]:
    """Record a recovery check-in, then apply the deterministic phase ladder. The coach can
    advise, but advancement/step-back is decided here so the staged return is consistent."""
    d = date or _today().isoformat()
    entry = {"date": d, "pain_during": pain_during, "pain_after": pain_after, "ran": ran}
    if note:
        entry["note"] = note

    def apply(r):
        r.setdefault("checkins", []).append(entry)
        new_phase = advance_decision(r.get("phase", "easy_only"), r["checkins"])
        r["phase"] = new_phase
        r["load_cap_pct"] = phase_meta(new_phase)["load_cap_pct"]
        if r.get("status") == "active":
            r["status"] = "recovering"
    return _mutate(_home(home), episode_id, apply)


def resolve(home: Optional[str], episode_id: str, date: Optional[str] = None) -> Optional[Dict]:
    d = date or _today().isoformat()

    def apply(r):
        r["status"] = "resolved"
        r["phase"] = "full"
        r["load_cap_pct"] = 100
        r["resolved_date"] = d
    return _mutate(_home(home), episode_id, apply)


# ── snapshot for plan guardrail / coach context ──────────────────────────────────
def load_cap_pct(home: Optional[str]) -> Optional[int]:
    ep = active(home)
    return None if not ep else ep.get("load_cap_pct", phase_meta(ep.get("phase", "easy_only"))["load_cap_pct"])


def allowed_types(home: Optional[str]) -> Optional[set]:
    """Workout types permitted by the active episode's phase. None = no active injury
    (or 'full' phase) → no restriction."""
    ep = active(home)
    if not ep:
        return None
    return phase_meta(ep.get("phase", "easy_only"))["allowed"]


def _cap_of(ep: Dict) -> int:
    return ep.get("load_cap_pct", phase_meta(ep.get("phase", "easy_only"))["load_cap_pct"])


def snapshot(home: Optional[str]) -> Dict:
    """Compact injury state for the plan guardrail / coach context. ``mode='recovery'`` when
    ≥1 episode is open. With several concurrent injuries the constraints COMBINE to the most
    restrictive so the guardrail is safe: ``load_cap_pct`` = the minimum cap, ``allowed_types``
    = the intersection of every open phase's allowed set, and ``primary`` (for display) = the
    most restrictive episode. ``allowed_types`` is a sorted list (None = unrestricted) so it
    stays JSON/template-friendly."""
    open_eps = [r for r in all_episodes(home) if r.get("status") in ("active", "recovering")]
    if not open_eps:
        return {"active": False, "mode": "normal", "episodes": [],
                "load_cap_pct": None, "allowed_types": None, "primary": None}
    # binding load cap = the lowest across all open injuries
    load_cap = min(_cap_of(e) for e in open_eps)
    # allowed = intersection of each phase's allowed set; a 'full' phase (None) adds no limit
    allowed_sets = [phase_meta(e.get("phase", "easy_only"))["allowed"] for e in open_eps]
    allowed_sets = [a for a in allowed_sets if a is not None]
    allowed = set.intersection(*allowed_sets) if allowed_sets else None
    # primary (for the banner) = most restrictive: lowest cap, then earliest onset
    primary = min(open_eps, key=lambda e: (_cap_of(e), e.get("onset_date") or ""))
    return {
        "active": True,
        "mode": "recovery",
        "episodes": open_eps,
        "primary": primary,
        "phase_label": phase_meta(primary.get("phase", "easy_only"))["label"],
        "load_cap_pct": load_cap,
        "allowed_types": sorted(allowed) if allowed is not None else None,
    }


def format_episode(ep: Dict) -> str:
    """One-line Korean summary for cards/chat."""
    meta = phase_meta(ep.get("phase", "easy_only"))
    sev = f" · 통증 {ep['severity']}/10" if ep.get("severity") else ""
    cap = ep.get("load_cap_pct")
    cap_s = f" · 부하 상한 {cap}%" if cap is not None else ""
    return f"🩹 {ep.get('label', '부상')}{sev} — {meta['label']} 단계{cap_s} (발생 {ep.get('onset_date', '')})"


# ── CLI (mutating ops the coach drives behind a confirm gate) ────────────────────
def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Injury episode tracking & return-to-run ladder.")
    ap.add_argument("--home", help="Explicit OMPB_HOME override.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Print the current injury snapshot (JSON).")
    sub.add_parser("list", help="Print all episodes (JSON).")

    p_parse = sub.add_parser("parse", help="Propose an episode from free text (JSON or empty).")
    p_parse.add_argument("text")

    p_new = sub.add_parser("create", help="Create an episode (from a confirmed proposal).")
    p_new.add_argument("--part", required=True, help="Body part keyword (e.g. knee, 무릎).")
    p_new.add_argument("--side", choices=["left", "right", "both"])
    p_new.add_argument("--severity", type=int)
    p_new.add_argument("--onset", help="ISO onset date (default: today).")
    p_new.add_argument("--phase", choices=PHASES)
    p_new.add_argument("--note")

    p_ci = sub.add_parser("checkin", help="Record a recovery check-in (applies the ladder).")
    p_ci.add_argument("--id", required=True)
    p_ci.add_argument("--pain-during", type=int, default=0)
    p_ci.add_argument("--pain-after", type=int, default=0)
    p_ci.add_argument("--ran", action="store_true")
    p_ci.add_argument("--note", default="")

    p_ph = sub.add_parser("set-phase", help="Force a return-to-run phase.")
    p_ph.add_argument("--id", required=True)
    p_ph.add_argument("--phase", required=True, choices=PHASES)

    p_res = sub.add_parser("resolve", help="Mark an episode resolved.")
    p_res.add_argument("--id", required=True)

    a = ap.parse_args(argv)
    home = resolve_home(a.home, create=True)

    if a.cmd == "status":
        out = snapshot(home)
    elif a.cmd == "list":
        out = all_episodes(home)
    elif a.cmd == "parse":
        out = parse_mention(a.text)
    elif a.cmd == "create":
        proposal = {"body_part": _parse_part(a.part) or a.part, "side": a.side,
                    "severity": a.severity, "onset_date": a.onset, "phase": a.phase,
                    "note": a.note}
        out = create_episode(home, proposal)
    elif a.cmd == "checkin":
        out = checkin(home, a.id, pain_during=a.pain_during, pain_after=a.pain_after,
                      ran=a.ran, note=a.note)
    elif a.cmd == "set-phase":
        out = set_phase(home, a.id, a.phase)
    elif a.cmd == "resolve":
        out = resolve(home, a.id)
    else:  # pragma: no cover
        return 2

    print(json.dumps(out, ensure_ascii=False, indent=2, default=sorted_default))
    return 0


def sorted_default(o):
    if isinstance(o, set):
        return sorted(o)
    raise TypeError(f"not serializable: {type(o)}")


if __name__ == "__main__":
    raise SystemExit(main())
