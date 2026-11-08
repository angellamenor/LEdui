"""Configuración común de los tests: SQLite temporal y servicios externos simulados."""
import os
import tempfile

_db_dir = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_db_dir}/test.db"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["ANTHROPIC_API_KEY"] = "test"
os.environ["GOOGLE_AI_API_KEY"] = "test"
os.environ["VALID_ACCESS_KEY"] = "clave-buena"
os.environ.pop("ADMIN_ACCESS_KEY", None)
os.environ.pop("PROMPTS_DIR", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.auth import create_access_token  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.prompt_loader import prompts  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    prompts.reload()
    yield


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


def _make_user(db, email, admin=False):
    user = User(email=email, google_id=f"g-{email}", name=email.split("@")[0], is_admin=admin)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def user(db):
    return _make_user(db, "profe@example.com")


@pytest.fixture
def other_user(db):
    return _make_user(db, "otra@example.com")


@pytest.fixture
def admin_user(db):
    return _make_user(db, "admin@example.com", admin=True)


def auth_headers(user, lang=None):
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    if lang:
        headers["Accept-Language"] = lang
    return headers


@pytest.fixture
def client():
    return TestClient(app)
