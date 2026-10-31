"""Generate one-time invitation code. Run in the app container."""
import sys, secrets
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.db import Base,engine,SessionLocal
from app.models import Invite
from app.security import digest
Base.metadata.create_all(bind=engine)
code=secrets.token_urlsafe(24)
with SessionLocal() as db:
    db.add(Invite(token_hash=digest(code)))
    db.commit()
print('One-time invite:',code)
