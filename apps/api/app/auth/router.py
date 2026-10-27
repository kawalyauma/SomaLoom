import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.security import (
    DUMMY_HASH,
    current_user,
    hash_token,
    hasher,
    require_roles,
    verify_password,
)
from app.core.config import get_settings
from app.core.database import get_db
from app.core.models import AuditLog, AuthSession, School, User, utcnow
from app.core.schemas import Login, SessionOut, UserCreate, UserOut

router = APIRouter(tags=["authentication"])


def audit(db, user, action, target, request):
    db.add(
        AuditLog(
            tenant_id=user.tenant_id,
            actor_id=user.id,
            action=action,
            target_id=str(target),
            request_id=request.state.request_id,
        )
    )


@router.post("/auth/login", response_model=SessionOut)
def login(data: Login, request: Request, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == str(data.email).lower()))
    valid = verify_password(user.password_hash if user else DUMMY_HASH, data.password)
    if not user or not valid or not user.active:
        db.add(AuditLog(action="auth.login_failed", request_id=request.state.request_id))
        db.commit()
        raise HTTPException(401, "Invalid credentials")
    if hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hasher.hash(data.password)
    old = request.cookies.get("somaloom_session")
    if old:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == hash_token(old)))
    token = secrets.token_urlsafe(48)
    expires = utcnow() + timedelta(hours=get_settings().session_hours)
    db.add(AuthSession(user_id=user.id, token_hash=hash_token(token), expires_at=expires))
    audit(db, user, "auth.login", user.id, request)
    db.commit()
    response.set_cookie(
        "somaloom_session",
        token,
        httponly=True,
        secure=get_settings().app_env == "production",
        samesite="lax",
        max_age=get_settings().session_hours * 3600,
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return SessionOut(user=UserOut.model_validate(user), expires_at=expires)


@router.post("/auth/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    token = request.state.session_token
    db.execute(delete(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    audit(db, user, "auth.logout", user.id, request)
    db.commit()
    response.delete_cookie(
        "somaloom_session",
        path="/",
        secure=get_settings().app_env == "production",
        httponly=True,
        samesite="lax",
    )


@router.get("/users/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@router.post("/users", response_model=UserOut, status_code=201)
def provision(
    data: UserCreate,
    request: Request,
    user: User = Depends(require_roles("platform_admin", "school_admin")),
    db: Session = Depends(get_db),
):
    if user.role == "school_admin" and (
        data.tenant_id != user.tenant_id or data.role not in {"teacher", "reviewer"}
    ):
        raise HTTPException(403, "Cannot assign this tenant or role")
    if (data.role == "platform_admin") != (data.tenant_id is None):
        raise HTTPException(
            422, "School users require tenant_id; platform admins cannot have a tenant"
        )
    if data.tenant_id and not db.get(School, data.tenant_id):
        raise HTTPException(404, "School not found")
    created = User(
        email=str(data.email).lower(),
        name=data.name,
        role=data.role,
        tenant_id=data.tenant_id,
        password_hash=hasher.hash(data.password),
    )
    db.add(created)
    try:
        db.flush()
        audit(db, user, "user.provision", created.id, request)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Account already exists") from None
    return created
