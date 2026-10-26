"""Disposable synthetic school/users; tests the restricted DB role against live API."""

import json
import secrets
import urllib.error
import urllib.request
from uuid import uuid4

from app.auth.security import hasher
from app.core.database import SessionLocal
from app.core.models import AuthSession, Organization, School, User

suffix = uuid4().hex
password = secrets.token_urlsafe(32)
with SessionLocal() as db:
    org = Organization(name="Smoke " + suffix)
    db.add(org)
    db.flush()
    schools = [School(name="Smoke", organization_id=org.id) for _ in range(2)]
    db.add_all(schools)
    db.flush()
    user = User(
        email=f"smoke-{suffix}@example.org",
        name="Smoke",
        tenant_id=schools[0].id,
        role="teacher",
        password_hash=hasher.hash(password),
    )
    db.add(user)
    db.commit()
    ids = (user.id, [school.id for school in schools], org.id)
    email = user.email


def request(path, data=None, cookie=None):
    headers = {"Origin": "http://localhost:3000"}
    if cookie:
        headers["Cookie"] = cookie
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        "http://localhost:8000/api/v1" + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers=headers,
    )
    return urllib.request.urlopen(req)


try:
    result = request("/auth/login", {"email": email, "password": password})
    cookie = result.headers["Set-Cookie"].split(";", 1)[0]
    assert json.loads(result.read())["user"]["role"] == "teacher"
    assert json.loads(request("/schools", cookie=cookie).read())["total"] == 1
    try:
        request(f"/schools/{ids[1][1]}", cookie=cookie)
        raise AssertionError("Cross-tenant access succeeded")
    except urllib.error.HTTPError as exc:
        assert exc.code == 404
    assert request("/auth/logout", {}, cookie).status == 204
    print("Live authentication and tenant denial passed")
finally:
    with SessionLocal() as db:
        db.query(AuthSession).filter_by(user_id=ids[0]).delete()
        db.query(User).filter_by(id=ids[0]).update({"active": False})
        db.commit()
