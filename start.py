"""
start.py — Single entrypoint for Railway.

Runs prestart.py (migrations) then replaces this process with app.py using
os.execv so there is no gap and Railway's health check sees a continuous PID.
"""
import os
import sys
import subprocess

print("=== start.py: running prestart ===", flush=True)
result = subprocess.run([sys.executable, "prestart.py"])
if result.returncode != 0:
    print(f"=== start.py: prestart failed (exit {result.returncode}) ===", flush=True)
    sys.exit(result.returncode)

print("=== start.py: exec app.py ===", flush=True)
os.execv(sys.executable, [sys.executable, "-u", "app.py"])
