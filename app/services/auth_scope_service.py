from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import UserAuthGrant


def has_required_scopes(db: Session, user_id: str, required_scopes: list[str] | tuple[str, ...]) -> bool:
    return not explain_missing_scopes(db, user_id, required_scopes)


def explain_missing_scopes(db: Session, user_id: str, required_scopes: list[str] | tuple[str, ...]) -> list[str]:
    current = _current_scope_names(db, user_id)
    return [scope for scope in required_scopes if scope not in current]


def current_grants(db: Session, user_id: str) -> list[dict]:
    grants = db.scalars(
        select(UserAuthGrant).where(UserAuthGrant.user_id == user_id).order_by(UserAuthGrant.created_at.asc())
    ).all()
    return [
        {
            "scope": grant.scope,
            "subject_type": grant.subject_type,
            "subject_id": grant.subject_id,
            "is_active": grant.is_active,
        }
        for grant in grants
    ]


def _current_scope_names(db: Session, user_id: str) -> set[str]:
    grants = db.scalars(
        select(UserAuthGrant).where(
            UserAuthGrant.user_id == user_id,
            UserAuthGrant.is_active.is_(True),
        )
    ).all()
    return {grant.scope for grant in grants}
