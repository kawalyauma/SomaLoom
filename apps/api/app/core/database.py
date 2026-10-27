from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings

url = get_settings().database_url
engine = create_engine(
    url,
    pool_pre_ping=True,
    **({"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}),
)
if url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def enable_fk(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")


SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_db():
    with SessionLocal() as db:
        yield db
