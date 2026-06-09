"""
prestart.py — Runs before gunicorn on Railway.

Sets SKIP_DB_INIT so that importing app.py does NOT trigger db.create_all()
or ALTER TABLE statements (which would hang on cold Railway Postgres and
race with Alembic). Uses the Flask-Migrate Python API directly.

Handles two production scenarios:
  A) Fresh database          — alembic_version missing/empty AND users table absent
                               => run upgrade() normally (creates all tables via migrations)
  B) Schema pre-exists       — alembic_version missing/empty BUT users table exists
     (old db.create_all())   => stamp head so Alembic knows current state, then upgrade() no-op
  C) Already migrated        — alembic_version has entries
                               => upgrade() applies only new migrations
"""
import os
import sys

# Must be set before importing app so the startup DDL block is skipped.
os.environ['SKIP_DB_INIT'] = '1'

print("=== prestart: importing app ===", flush=True)
try:
    from app import app, db
except Exception as exc:
    print(f"=== prestart: import failed: {exc} ===", flush=True)
    sys.exit(1)

print("=== prestart: checking migration state ===", flush=True)

with app.app_context():
    from sqlalchemy import inspect, text
    from flask_migrate import upgrade, stamp

    insp = inspect(db.engine)
    table_names = insp.get_table_names()

    # Determine current Alembic state
    has_alembic = 'alembic_version' in table_names
    current_rev = None
    if has_alembic:
        try:
            row = db.session.execute(
                text("SELECT version_num FROM alembic_version LIMIT 1")
            ).fetchone()
            current_rev = row[0] if row else None
        except Exception:
            current_rev = None

    users_exist = 'users' in table_names

    print(f"=== alembic_version present: {has_alembic}, current_rev: {current_rev}, users table: {users_exist} ===", flush=True)

    # Scenario B: schema exists but Alembic has no record of it
    if current_rev is None and users_exist:
        print("=== Schema pre-exists without migration history — stamping head ===", flush=True)
        try:
            stamp(revision='head')
            print("=== Stamped head OK ===", flush=True)
        except Exception as exc:
            print(f"=== stamp failed: {exc} ===", flush=True)
            sys.exit(1)

    # Scenario A & C (and after B's stamp): run upgrade
    print("=== Running flask db upgrade ===", flush=True)
    try:
        upgrade()
        print("=== DB migrations OK ===", flush=True)
    except Exception as exc:
        print(f"=== upgrade failed: {exc} ===", flush=True)
        sys.exit(1)
