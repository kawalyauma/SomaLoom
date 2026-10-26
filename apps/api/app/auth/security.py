import hashlib
import secrets
from datetime import datetime, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.models import AuthSession, User

hasher = PasswordHasher()
# Equalize unknown-account password verification cost.
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(32))


def hash_token(value):
    return hashlib.sha256(value.encode()).hexdigest()


def verify_password(encoded, password):
    try:
        return hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


bearer_scheme = HTTPBearer(auto_error=False)
cookie_scheme = APIKeyCookie(name="somaloom_session", auto_error=False)


def current_user(
    request: Request,
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    cookie: str | None = Security(cookie_scheme),
) -> User:
    token = credentials.credentials if credentials else cookie
    if not token or len(token) > 200:
        raise HTTPException(401, "Authentication required")
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    if not session:
        raise HTTPException(401, "Session invalid or expired")
    expires = (
        session.expires_at.replace(tzinfo=timezone.utc)
        if session.expires_at.tzinfo is None
        else session.expires_at
    )
    if expires <= datetime.now(timezone.utc):
        raise HTTPException(401, "Session invalid or expired")
    user = db.get(User, session.user_id)
    if not user or not user.active:
        raise HTTPException(401, "Account unavailable")
    request.state.session_token = token
    return user


def require_roles(*roles):
    def dependency(user: User = Depends(current_user)):
        if user.role not in roles:
            raise HTTPException(403, "Permission denied")
        return user

    return dependency
