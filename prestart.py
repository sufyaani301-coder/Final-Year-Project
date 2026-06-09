"""
prestart.py — Run before gunicorn on Railway.

Handles two scenarios:
1. Fresh database: flask db upgrade runs all migrations normally.
2. Schema already exists (from db.create_all() on a previous deploy):
   upgrade fails with DuplicateColumn/DuplicateTable -> stamp head so
   Alembic records the current state, then upgrade is a clean no-op.
"""
import subprocess
import sys

print(">>> Running flask db upgrade ...", flush=True)
result = subprocess.run(["flask", "db", "upgrade"], capture_output=False)

if result.returncode == 0:
    print(">>> Migrations OK.", flush=True)
    sys.exit(0)

print(">>> Upgrade failed — schema likely pre-exists from db.create_all().", flush=True)
print(">>> Stamping head and retrying ...", flush=True)

stamp = subprocess.run(["flask", "db", "stamp", "head"])
if stamp.returncode != 0:
    print(">>> stamp failed — aborting.", flush=True)
    sys.exit(1)

retry = subprocess.run(["flask", "db", "upgrade"])
if retry.returncode != 0:
    print(">>> Upgrade still failed after stamp — aborting.", flush=True)
    sys.exit(1)

print(">>> Migrations OK (after stamp).", flush=True)
