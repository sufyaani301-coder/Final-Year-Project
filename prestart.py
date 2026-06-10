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
# Prevent eventlet.monkey_patch() from running during migration.
# Without a running eventlet hub, monkey-patched threading semaphores deadlock
# inside SQLAlchemy's connection pool, causing upgrade() to hang forever.
os.environ['NO_EVENTLET_PATCH'] = '1'

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

    # Ensure every table exists (safety net if Alembic was stamped without creating tables)
    print("=== Running db.create_all() ===", flush=True)
    try:
        db.create_all()
        print("=== Tables OK ===", flush=True)
    except Exception as exc:
        print(f"=== create_all warning: {exc} ===", flush=True)

    # Legacy schema patches — safe to run repeatedly, fail gracefully
    for _stmt in [
        "ALTER TABLE users ADD COLUMN webauthn_type VARCHAR(20)",
        "ALTER TABLE users ADD COLUMN role VARCHAR(20) DEFAULT 'user'",
        "ALTER TABLE files ADD COLUMN file_hash VARCHAR(64)",
        # FIM columns added when integrity monitoring was introduced
        "ALTER TABLE files ADD COLUMN monitoring_enabled BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE files ADD COLUMN policy_id INTEGER",
        "ALTER TABLE files ADD COLUMN current_status VARCHAR(20) NOT NULL DEFAULT 'pending'",
        "ALTER TABLE files ADD COLUMN last_checked_at TIMESTAMP",
        "ALTER TABLE files ADD COLUMN next_check_at TIMESTAMP",
        "ALTER TABLE files ADD COLUMN check_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE files ADD COLUMN alert_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN default_policy_id INTEGER",
        # change_requests table is created by db.create_all(); columns patched for safety
        "ALTER TABLE change_requests ADD COLUMN pending_file VARCHAR(260)",
        "ALTER TABLE change_requests ADD COLUMN executed_at TIMESTAMP",
    ]:
        try:
            db.session.execute(text(_stmt))
            db.session.commit()
        except Exception:
            db.session.rollback()

    # Data migration: ensure existing admins have super_admin role
    try:
        db.session.execute(text(
            "UPDATE users SET role='super_admin' WHERE is_admin IS TRUE AND (role IS NULL OR role='user')"
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()

    # Final safety pass: create any model-defined tables that still don't exist
    # (catches new models added after the last Alembic migration, e.g. change_requests)
    print("=== prestart: final db.create_all() pass ===", flush=True)
    try:
        db.create_all()
        print("=== prestart: all tables verified ===", flush=True)
    except Exception as exc:
        print(f"=== prestart: final create_all warning: {exc} ===", flush=True)

    # Verify FIM tables exist explicitly
    insp2 = inspect(db.engine)
    all_tables = insp2.get_table_names()
    fim_tables = ['monitoring_policies', 'integrity_baselines',
                  'integrity_checks', 'integrity_alerts',
                  'alert_comments', 'change_requests']
    missing = [t for t in fim_tables if t not in all_tables]
    if missing:
        print(f"=== prestart WARNING: FIM tables still missing after create_all: {missing} ===", flush=True)
    else:
        print("=== prestart: all FIM tables present ===", flush=True)

    print("=== prestart complete ===", flush=True)
