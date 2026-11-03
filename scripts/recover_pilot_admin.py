"""One-time offline recovery of an existing pilot administrator.

Run ONLY in an authenticated environment with the real DATABASE_URL.
The new credential must be supplied in PILOT_ADMIN_RECOVERY_CODE, never an argument.
This script does not create a new user, publish, or print the credential.

Example (in a trusted shell):
    PILOT_ADMIN_RECOVERY_CONFIRM=ROTATE_EXISTING_ADMIN \
    PILOT_ADMIN_RECOVERY_CODE='<new high-entropy credential>' \
    python scripts/recover_pilot_admin.py

Never place the credential in source control or logs.
"""
import os
import secrets
import sys

from sqlalchemy import select, delete

from app.main import app  # initialize all SQLAlchemy model definitions in a safe order
from app.db import SessionLocal, engine
from app.models import Session as LoginSession
from app.pilot import PilotAccess
from app.security import digest

def main():
    if os.getenv("PILOT_ADMIN_RECOVERY_CONFIRM") != "ROTATE_EXISTING_ADMIN":
        raise SystemExit("REFUSED: explicit recovery confirmation required")
    if engine.dialect.name != "postgresql" and os.getenv("TEST_ALLOW_SQLITE_RECOVERY") != "1":
        raise SystemExit("REFUSED: PostgreSQL required")
    code = os.getenv("PILOT_ADMIN_RECOVERY_CODE", "")
    if len(code) < 40 or len(code) > 160 or len(set(code)) < 12:
        raise SystemExit("REFUSED: invalid recovery credential length or entropy")
    name = os.getenv("PILOT_ADMIN_RECOVERY_USERNAME", "pilot-admin").strip().lower()
    with SessionLocal() as db:
        entry = db.scalar(select(PilotAccess).where(PilotAccess.username == name, PilotAccess.role == "admin"))
        if not entry:
            raise SystemExit("REFUSED: administrator not found; existing accounts not modified")
        if secrets.compare_digest(entry.code_hash, digest(code)):
            print("ADMIN_RECOVERY_ALREADY_MATCHES")
            return
        entry.code_hash = digest(code)
        entry.enabled = True
        db.execute(delete(LoginSession).where(LoginSession.user_id == entry.user_id))
        db.commit()
    print("ADMIN_RECOVERY_COMPLETE: credential rotated and old sessions revoked; secret not printed")

if __name__ == "__main__":
    main()
