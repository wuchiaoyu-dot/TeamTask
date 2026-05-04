import os
from collections.abc import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./teamtask_agent.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_columns()


def _ensure_sqlite_columns() -> None:
    if not DATABASE_URL.startswith("sqlite"):
        return

    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    if "source_events" not in table_names:
        source_event_columns = set()
    else:
        source_event_columns = {column["name"] for column in inspector.get_columns("source_events")}
    with engine.begin() as connection:
        if "external_event_id" not in source_event_columns:
            connection.exec_driver_sql("ALTER TABLE source_events ADD COLUMN external_event_id VARCHAR(255)")
        if "parsed_context_json" not in source_event_columns:
            connection.exec_driver_sql("ALTER TABLE source_events ADD COLUMN parsed_context_json JSON")
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_source_events_external_event_id "
            "ON source_events(external_event_id) WHERE external_event_id IS NOT NULL"
        )

        if "personal_todo_projections" in table_names:
            todo_columns = {column["name"] for column in inspector.get_columns("personal_todo_projections")}
            if "todo_provider" not in todo_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE personal_todo_projections ADD COLUMN todo_provider VARCHAR(64) DEFAULT 'mock' NOT NULL"
                )
            if "external_record_id" not in todo_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE personal_todo_projections ADD COLUMN external_record_id VARCHAR(255)"
                )
            if "last_synced_at" not in todo_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE personal_todo_projections ADD COLUMN last_synced_at DATETIME"
                )
        if "task_contracts" in table_names:
            task_columns = {column["name"] for column in inspector.get_columns("task_contracts")}
            if "parent_task_title" not in task_columns:
                connection.exec_driver_sql("ALTER TABLE task_contracts ADD COLUMN parent_task_title VARCHAR(500)")
            if "related_resources_json" not in task_columns:
                connection.exec_driver_sql("ALTER TABLE task_contracts ADD COLUMN related_resources_json JSON")
            if "resource_search_status" not in task_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE task_contracts ADD COLUMN resource_search_status VARCHAR(64) DEFAULT 'not_started' NOT NULL"
                )
            if "resource_search_error" not in task_columns:
                connection.exec_driver_sql("ALTER TABLE task_contracts ADD COLUMN resource_search_error TEXT")
            if "progress_text" not in task_columns:
                connection.exec_driver_sql("ALTER TABLE task_contracts ADD COLUMN progress_text TEXT")
            if "progress_updated_at" not in task_columns:
                connection.exec_driver_sql("ALTER TABLE task_contracts ADD COLUMN progress_updated_at DATETIME")
            if "completion_status" not in task_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE task_contracts ADD COLUMN completion_status VARCHAR(64) DEFAULT 'unknown' NOT NULL"
                )

        if "progress_queries" in table_names:
            progress_query_columns = {column["name"] for column in inspector.get_columns("progress_queries")}
            if "raw_payload_json" not in progress_query_columns:
                connection.exec_driver_sql("ALTER TABLE progress_queries ADD COLUMN raw_payload_json JSON")
