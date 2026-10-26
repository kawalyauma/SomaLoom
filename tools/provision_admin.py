"""Run inside the API container, after migrations. Password never appears in argv."""

import getpass

from app.auth.security import hasher
from app.core.database import SessionLocal
from app.core.models import AuditLog, User
from pydantic import EmailStr, TypeAdapter
from sqlalchemy import select


def main():
    email = str(TypeAdapter(EmailStr).validate_python(input("Admin email: ").strip())).lower()
    name = input("Admin name: ").strip()
    password = getpass.getpass("Password (12+ characters): ")
    if len(password) < 12 or password != getpass.getpass("Confirm password: ") or not name:
        raise SystemExit("Invalid name/password or confirmation")
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == email)):
            raise SystemExit("Account already exists")
        user = User(
            email=email, name=name, role="platform_admin", password_hash=hasher.hash(password)
        )
        db.add(user)
        db.flush()
        db.add(AuditLog(actor_id=user.id, action="admin.bootstrap", target_id=str(user.id)))
        db.commit()
    print("Administrator provisioned")


if __name__ == "__main__":
    main()
