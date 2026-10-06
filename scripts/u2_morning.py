"""U2 morning context card (docs/U2_README.md §10): gap reference, today's events, news bias and global cues.

Sources:
- The Nifty system's event calendar (read-only) and premium's own `config/u2_events.yaml` (owner-maintained).
- Yesterday's close from the recorder's previous day (read-only).
- ONE headless Claude Code call (`claude -p`, WebSearch only) under the owner's subscription login; API-key
  variables are removed from the child environment, so it can never bill an API key.
Writes data/u2/<day>_morning.json once; the card is then frozen for the day. Never trades, never places orders.
Usage: uv run python scripts/u2_morning.py [--day YYYY-MM-DD] [--no-llm]
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "u2"
RAW = ROOT.parent / "suzlon" / "data" / "raw"
CAL_NIFTY = ROOT.parent / "suzlon" / "config" / "event_calendar.yaml"
CAL_U2 = ROOT / "config" / "u2_events.yaml"
MODEL, TIMEOUT_S = "claude-sonnet-5-5", 240
TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*IST")

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "bias": {"type": "string", "enum": ["positive", "negative", "mixed", "unknown"]},
        "confidence": {"type": "number"},
        "headlines": {"type": "array", "items": {"type": "string"}},
        "global_cues": {"type": "object", "properties": {
            "us_close": {"type": "string"}, "asia": {"type": "string"}, "crude": {"type": "string"},
            "usdinr": {"type": "string"}, "gift_nifty": {"type": "string"}},
            "required": ["us_close", "asia", "crude", "usdinr", "gift_nifty"], "additionalProperties": False},
        "events_today": {"type": "array", "items": {"type": "object", "properties": {
            "time_ist": {"type": "string"}, "name": {"type": "string"}},
            "required": ["time_ist", "name"], "additionalProperties": False}},
        "event_risk": {"type": "string", "enum": ["none", "medium", "high"]},
        "summary": {"type": "string"},
        "sources": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["bias", "confidence", "headlines", "global_cues", "events_today", "event_risk", "summary", "sources"],
    "additionalProperties": False,
}
SYSTEM = ("You are a careful market-news analyst helping with PAPER research on Indian index options (Nifty 50). "
          "Use web search for today's pre-market news. Report only what sources support; if unsure, say 'unknown'. "
          "You never recommend trades. Return the JSON requested.")


def calendar_events(day: date) -> list[dict[str, Any]]:
    """Today's events from both calendars, plus yesterday's 'next session' events (US events after the close)."""
    out = []
    for path, src in ((CAL_NIFTY, "nifty-calendar"), (CAL_U2, "u2-events")):
        if not path.exists():
            continue
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for e in raw.get("events") or []:
            d = e.get("date")
            d = d if isinstance(d, date) else date.fromisoformat(str(d))
            text = str(e.get("event", ""))
            prev_session = d < day and "next session" in text and (day - d).days <= 3
            if d == day or prev_session:
                m = TIME_RE.search(text) if d == day else None
                out.append({"name": text, "time_ist": f"{int(m.group(1)):02d}:{m.group(2)}" if m else "",
                            "verified": bool(e.get("verified", False)), "source": src,
                            "kind": "overnight (affects the open)" if prev_session else "today"})
    return out


def prev_close(day: date) -> tuple[str | None, float | None]:
    days = sorted(p.name[5:] for p in RAW.glob("date=*") if p.name[5:] < str(day))
    for d in reversed(days):
        f = RAW / f"date={d}" / "ltp.jsonl"
        if not f.exists():
            continue
        last = None
        with f.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    j = json.loads(line)
                except ValueError:
                    continue
                n = (j.get("index") or {}).get("NSE_NIFTY")
                if n and j["recv_ts"][11:16] <= "15:30":
                    last = float(n)
        if last:
            return d, last
    return None, None


def ask_llm(day: date, events: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str]:
    exe = shutil.which("claude") or next((str(p) for p in (Path.home() / ".local" / "bin").glob("claude*")), None)
    if not exe:
        return None, "claude CLI not found"
    user = (f"Date: {day:%A %d %B %Y} (IST). Indian market opens 09:15 IST.\n"
            f"Known scheduled events (some unverified): {json.dumps(events)}\n"
            "1) Overall pre-market news bias for Nifty 50 today (positive / negative / mixed / unknown) with "
            "confidence 0-1. 2) Up to 5 key headlines. 3) Global cues: US close, Asia now, crude, USD/INR, GIFT Nifty. "
            "4) Scheduled India-market-moving events TODAY during 09:15-15:30 IST with their IST time (HH:MM) - "
            "e.g. RBI policy, major data, heavyweight results. Confirm or correct the RBI date if relevant. "
            "5) Event risk today: none / medium / high. 6) One-paragraph summary. Include source URLs.")
    cmd = [exe, "-p", "--output-format", "json", "--model", MODEL, "--tools", "WebSearch", "--allowedTools",
           "WebSearch", "--no-session-persistence", "--system-prompt", SYSTEM, "--json-schema", json.dumps(SCHEMA)]
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    work = Path(tempfile.gettempdir()) / "premium_u2_llm"
    work.mkdir(parents=True, exist_ok=True)
    try:
        # fixed argument list, no shell; the prompt goes via stdin
        p = subprocess.run(cmd, input=user, capture_output=True, text=True, encoding="utf-8",  # noqa: S603
                           timeout=TIMEOUT_S, cwd=work, env=env, check=False)
    except (subprocess.TimeoutExpired, OSError) as e:
        return None, f"{type(e).__name__}: {e}"[:200]
    try:
        j = json.loads(p.stdout)
    except json.JSONDecodeError:
        return None, f"bad CLI output (exit {p.returncode})"
    data = j.get("structured_output")
    if j.get("is_error") or not isinstance(data, dict):
        return None, f"CLI error: {str(j.get('result') or j.get('subtype'))[:200]}"
    return data, ""


def build(day: date, use_llm: bool = True) -> dict[str, Any]:
    events = calendar_events(day)
    pday, pclose = prev_close(day)
    llm, err = ask_llm(day, events) if use_llm else (None, "LLM not requested")
    windows = []
    llm_events = [dict(x, source="llm", verified=False, kind="today") for x in (llm or {}).get("events_today", [])]
    for e in events + llm_events:
        t = e.get("time_ist") or ""
        if re.fullmatch(r"\d{1,2}:\d{2}", t) and "09:15" <= f"{int(t.split(':')[0]):02d}:{t.split(':')[1]}" <= "15:30":
            hh, mm = (int(x) for x in t.split(":"))
            et = datetime.combine(day, datetime.min.time()).replace(hour=hh, minute=mm)
            windows.append({"name": e["name"], "time": f"{hh:02d}:{mm:02d}", "source": e["source"],
                            "from": (et - timedelta(minutes=10)).strftime("%H:%M"),
                            "to": (et + timedelta(minutes=15)).strftime("%H:%M")})
    risk = (llm or {}).get("event_risk", "none")
    if windows and risk == "none":
        risk = "medium"
    return {"day": str(day), "built_at": datetime.now().isoformat(timespec="seconds"),
            "prev_day": pday, "prev_close": pclose, "calendar_events": events, "event_windows": windows,
            "event_risk": risk, "bias": (llm or {}).get("bias", "unknown"),
            "confidence": (llm or {}).get("confidence"), "headlines": (llm or {}).get("headlines", []),
            "global_cues": (llm or {}).get("global_cues", {}), "summary": (llm or {}).get("summary", ""),
            "sources": (llm or {}).get("sources", [])[:10], "llm_error": err}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=str(date.today()))
    ap.add_argument("--no-llm", action="store_true")
    a = ap.parse_args()
    day = date.fromisoformat(a.day)
    OUT.mkdir(parents=True, exist_ok=True)
    f = OUT / f"{day}_morning.json"
    if f.exists():
        print(f"card already built (frozen for the day): {f}")
        return
    card = build(day, use_llm=not a.no_llm)
    f.write_text(json.dumps(card, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: card[k] for k in ("prev_close", "event_windows", "event_risk", "bias", "confidence",
                                           "llm_error")}, default=str))


if __name__ == "__main__":
    main()
