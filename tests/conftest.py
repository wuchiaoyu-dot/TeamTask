import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["TEAMTASK_SKIP_DB_INIT"] = "1"
os.environ["ENV_PROFILE"] = "local_mock"
os.environ["TASK_EXTRACTOR_BACKEND"] = "rule"
os.environ["TASK_EXTRACTOR_LLM_FALLBACK"] = "true"
os.environ["LLM_TASK_API_KEY"] = ""
os.environ["LLM_TASK_MODEL"] = ""
os.environ["FEISHU_MOCK"] = "true"
os.environ["LARK_DRY_RUN"] = "true"
os.environ["LARK_CLI_DRY_RUN"] = "true"
os.environ["FEISHU_SEND_DRY_RUN"] = "true"
os.environ["BITABLE_DRY_RUN"] = "true"
os.environ["TODO_PROJECTION_DRY_RUN"] = "true"
os.environ["FEISHU_ENABLE_REAL_READ"] = "false"
os.environ["RESOURCE_SEARCH_REAL_READ"] = "false"
os.environ["RESOURCE_SEARCH_DRY_RUN"] = "true"
os.environ["TODO_BACKEND"] = "mock"
os.environ["ALLOWED_USER_IDS"] = ""
os.environ["ALLOWED_CHAT_IDS"] = ""
os.environ["FEISHU_VERIFICATION_TOKEN"] = ""
os.environ["FEISHU_CARD_VERIFICATION_TOKEN"] = ""

from app.db import Base, get_db  # noqa: E402
from app.main import app, feishu_client  # noqa: E402


@pytest.fixture()
def session_factory() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
        expire_on_commit=False,
    )
    yield TestingSessionLocal
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(session_factory: sessionmaker[Session]) -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    feishu_client.sent_cards.clear()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
