#!/usr/bin/env python3
"""Offline verifier plumbing fixture, not a mathematical judge."""
import json
import re
import sys
from pathlib import Path


def main():
    prompt = sys.stdin.read()
    match = re.search(r"this exact path:\s*(.+)\.$", prompt)
    if not match:
        return 3
    output = Path(match.group(1))
    wrong = "[[FAKE:wrong]]" in prompt
    payload = {"verification_report": {"summary":"fixture", "critical_errors":
        [{"location":"proof","issue":"fixture error"}] if wrong else [], "gaps":[]},
        "verdict":"wrong" if wrong else "correct", "repair_hints":"fixture repair" if wrong else ""}
    output.write_text(json.dumps(payload))
    for event in [{"type":"session","sessionId":"verifier-fixture"},
                  {"type":"status","phase":"turn_end","reason":{"kind":"completed"}},
                  {"type":"final","text":"Verification written."}]:
        print(json.dumps(event))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
