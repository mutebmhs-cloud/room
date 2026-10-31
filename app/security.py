import hashlib, hmac, secrets, os
from datetime import timedelta
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi import HTTPException
from .models import now

hash_password=PasswordHasher(time_cost=3,memory_cost=65536,parallelism=2)
def digest(token): return hashlib.sha256(token.encode()).hexdigest()
def secure_random(): return secrets.token_urlsafe(40)
def pw_valid(password): return 12 <= len(password) <= 128

def verify(password, hashed):
    try: return hash_password.verify(hashed,password)
    except (VerifyMismatchError,VerificationError,ValueError): return False

SESSION_DAYS=7
COOKIE_NAME='writer_session'
IS_PROD=os.getenv('APP_ENV','development')=='production'
APP_SECRET=os.getenv('APP_SECRET') or (secrets.token_urlsafe(48) if os.getenv('PILOT_EPHEMERAL') == '1' else 'development-only-not-for-production')
if IS_PROD and len(APP_SECRET)<32: raise RuntimeError('APP_SECRET must contain at least 32 characters in production')
def csrf_for_session(token): return hmac.new(APP_SECRET.encode(),token.encode(),hashlib.sha256).hexdigest()

def require_csrf(request, sess):
    got=request.headers.get('x-csrf-token','')
    if not got or not secrets.compare_digest(digest(got),sess.csrf_hash):
        raise HTTPException(403,'رمز الحماية غير صالح')
