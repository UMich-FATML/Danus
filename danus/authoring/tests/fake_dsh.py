#!/usr/bin/env python3
"""Deterministic headless protocol fixture; never calls a model."""
import json
import os
import re
import sys


def main():
    prompt = sys.stdin.read()
    match = re.search(r"\[\[FAKE:exit=(\d+)\]\]", prompt)
    if match:
        sys.stderr.write("fake_dsh: forced nonzero exit for the honesty path\n")
        return int(match.group(1))
    tex = ("\\documentclass{amsart}\n\\begin{document}\n\\title{Fake}\n"
           "\\maketitle\nWe prove that $S(n)=n^2$.\n\\end{document}\n")
    if "[[FAKE:gap]]" in prompt:
        tex += "% a hole: [GAP: missing step in the induction]\n"
    if "[[FAKE:empty]]" in prompt:
        tex = ""
    if "[[FAKE:cwd]]" in prompt:
        tex = os.getcwd()
    for event in [{"type":"session", "sessionId":"authoring-fixture"},
                  {"type":"text", "text":"not the artifact", "truncated":True},
                  {"type":"status", "phase":"turn_end", "reason":{"kind":"completed"}},
                  {"type":"final", "text":tex}]:
        print(json.dumps(event))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
