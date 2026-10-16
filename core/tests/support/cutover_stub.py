#!/usr/bin/env python3
"""Test double for solar_state_cutover.py in a full update.

Like the real helper it runs the apply hook it is given (that is where the code is replaced),
and it writes the arguments it received to $CUTOVER_STUB_LOG when that is set. It never touches
a runtime. $CUTOVER_STUB_EXIT makes it fail after the hook ran.
"""
import os
import subprocess
import sys

args = sys.argv[1:]
log = os.environ.get("CUTOVER_STUB_LOG")
if log:
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(" ".join(args) + "\n")
if "--apply-hook" in args:
    hook = args[args.index("--apply-hook") + 1]
    if subprocess.run([hook], check=False).returncode != 0:
        raise SystemExit(1)
raise SystemExit(int(os.environ.get("CUTOVER_STUB_EXIT", "0")))
