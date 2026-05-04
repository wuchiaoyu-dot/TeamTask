from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cards import (
    ALLOWED_CARD_ACTION_KEYS,
    build_assignee_confirm_card,
    build_change_proposal_card,
    build_initiator_confirm_card,
    build_progress_confirm_card,
    build_progress_reply_payload,
    build_progress_task_select_card,
)
from app.clients import create_feishu_client
from app.config import get_settings
from app.core.permissions import (
    can_confirm_as_assignee,
    can_confirm_as_initiator,
    can_reconcile_pair,
)
from app.db import get_db, init_db
from app.models import ChangeProposal, PersonalTodoProjection, ProgressQuery, SourceEvent, TaskContract, utc_now
from app.schemas.api import (
    AssigneeChangeIn,
    ContractActionIn,
    DebugBitableDryRunCreateIn,
    DebugMinutesExtractTasksIn,
    DebugMinutesParseLinkIn,
    DebugProgressConfirmIn,
    DebugProgressQueryIn,
    DebugResourceBuildQueriesIn,
    DebugResourceSearchIn,
    DevAuthGrantIn,
    EventIn,
    FeishuEventIn,
    FeishuCardCallbackIn,
    ProgressConfirmIn,
    ProgressQueryIn,
)
from app.services.feishu_card_adapter import adapt_feishu_card_action
from app.services.feishu_event_adapter import SourceEventCreate, adapt_feishu_event
from app.services.feishu_security import (
    challenge_response,
    decrypt_card_payload,
    decrypt_event_payload,
    env_bool,
    is_url_verification,
    validate_card_token,
    validate_event_token,
)
from app.services.event_router import extract_task_candidate, route_source_event
from app.services.task_service import (
    create_auth_grant,
    create_change_proposal,
    create_task_contract,
    create_todo_projection,
    find_contract_by_source_event,
    find_matching_change_proposal,
    find_matching_contract_for_progress,
    find_source_event_by_external_id,
    get_existing_card_action,
    get_or_create_user,
    record_card_action,
)
from app.services.todo_backend import create_todo_backend
from app.services.todo_field_mapper import map_contract_to_bitable_fields
from app.services.minutes_backend import create_minutes_backend
from app.services.minutes_link_parser import extract_minutes_token, extract_minutes_url, is_minutes_link
from app.services.minutes_preprocessor import normalize_minutes_content
from app.services.progress_query_service import (
    COMPLETION_BLOCKED,
    COMPLETION_COMPLETED,
    COMPLETION_DELAYED,
    COMPLETION_IN_PROGRESS,
    QUERY_STATUS_CONFIRMED,
    QUERY_STATUS_NO_MATCHING_TASK,
    QUERY_STATUS_PENDING,
    build_progress_summary,
    create_progress_query,
    detect_progress_query,
    extract_progress_query_entities,
    match_task_contract,
)
from app.services.resource_ranker import build_resource_queries
from app.services.resource_search_backend import ResourceSearchResult, create_resource_search_backend
from app.services.task_extractor import extract_task_candidates
from app.state_machine import (
    InvalidStateTransition,
    TaskStatus,
    assignee_accept,
    assignee_propose_change,
    complete_contract,
    confirm_initiator,
    ignore_contract,
    mark_pending_initiator_confirm,
    record_progress_update,
    resolve_change_review,
)

INITIATOR_ACTIONS = {
    "initiator_confirm",
    "initiator_ignore",
    "initiator_request_resource_search",
    "progress_select_task",
    "change_proposal_approve",
    "change_proposal_reject",
}
ASSIGNEE_ACTIONS = {
    "assignee_accept",
    "assignee_ignore",
    "assignee_propose_change",
    "assignee_request_resource_search",
    "progress_confirm",
    "progress_mark_completed",
    "progress_mark_in_progress",
    "progress_mark_delayed",
    "progress_mark_blocked",
    "progress_no_such_task",
}
CALLBACK_ACTION_KEYS = INITIATOR_ACTIONS | ASSIGNEE_ACTIONS


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if os.getenv("TEAMTASK_SKIP_DB_INIT") != "1":
        init_db()
    yield


app = FastAPI(title="TeamTask Agent V1", version="0.1.0", lifespan=lifespan)
feishu_client = create_feishu_client()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/feishu/events")
def feishu_events(payload: dict, db: Session = Depends(get_db)) -> dict:
    if env_bool("FEISHU_EVENT_ENCRYPTED", default=False):
        payload = decrypt_event_payload(payload, os.getenv("FEISHU_ENCRYPT_KEY"))

    if is_url_verification(payload):
        validate_event_token(payload)
        return challenge_response(payload)

    validate_event_token(payload)

    if _is_simulated_feishu_event(payload):
        simulated = FeishuEventIn.model_validate(payload)
        existing_event = find_source_event_by_external_id(db, simulated.event_id)
        if existing_event:
            return _source_event_response(existing_event, db, deduplicated=True)

        event_payload = _event_in_from_feishu(simulated)
        event_type = "group_message" if simulated.event_type == "group_message" else "meeting"
        return _ingest_source_event(event_type, event_payload, db, auto_mark_pending=True)

    adapted = adapt_feishu_event(payload)
    if not adapted.external_event_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Missing external event id")

    existing_event = find_source_event_by_external_id(db, adapted.external_event_id)
    if existing_event:
        return _source_event_response(existing_event, db, deduplicated=True)

    event_payload = _event_in_from_source_event_create(adapted)
    event_type = "meeting" if adapted.source_type == "meeting_minutes" else "group_message"
    return _ingest_source_event(event_type, event_payload, db, auto_mark_pending=True)


@app.post("/feishu/card-callback")
def feishu_card_callback(payload: dict, db: Session = Depends(get_db)) -> dict:
    payload = decrypt_card_payload(payload, os.getenv("FEISHU_CARD_ENCRYPT_KEY"))
    validate_card_token(payload)

    if _is_simulated_card_callback(payload):
        callback = FeishuCardCallbackIn.model_validate(payload)
    else:
        try:
            action = adapt_feishu_card_action(payload)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        callback = FeishuCardCallbackIn(
            action_key=action.action_key,
            contract_id=action.contract_id,
            recipient_user_id=action.recipient_user_id,
            title=action.form_value.get("title"),
            description=action.form_value.get("description"),
            deadline=action.form_value.get("deadline"),
            reason=action.form_value.get("reason"),
            progress_summary=action.form_value.get("progress_summary"),
            progress_text=action.form_value.get("progress_text"),
            progress_query_id=action.form_value.get("progress_query_id"),
            new_deadline=action.form_value.get("new_deadline"),
            proposal_id=action.form_value.get("proposal_id"),
            payload={"source_event_id": action.source_event_id, "raw_payload": action.raw_payload},
        )

    if callback.action_key not in ALLOWED_CARD_ACTION_KEYS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown card action_key")
    if callback.action_key not in CALLBACK_ACTION_KEYS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported callback action_key")

    if callback.action_key == "initiator_confirm":
        return _handle_initiator_confirm(callback.recipient_user_id, callback.contract_id, db)
    if callback.action_key == "initiator_ignore":
        return _handle_initiator_ignore(callback.recipient_user_id, callback.contract_id, db)
    if callback.action_key == "assignee_accept":
        return _handle_assignee_accept(callback.recipient_user_id, callback.contract_id, db)
    if callback.action_key == "assignee_ignore":
        return _handle_assignee_ignore(callback.recipient_user_id, callback.contract_id, db)
    if callback.action_key == "initiator_request_resource_search":
        return _handle_resource_search(callback.recipient_user_id, callback.contract_id, db, "initiator")
    if callback.action_key == "assignee_request_resource_search":
        return _handle_resource_search(callback.recipient_user_id, callback.contract_id, db, "assignee")
    if callback.action_key == "assignee_propose_change":
        return _handle_assignee_propose_change(
            actor_user_id=callback.recipient_user_id,
            contract_id=callback.contract_id,
            db=db,
            title=callback.title,
            description=callback.description,
            deadline=callback.deadline,
            reason=callback.reason,
        )
    if callback.action_key == "progress_confirm":
        return _handle_progress_confirm(
            actor_user_id=callback.recipient_user_id,
            contract_id=callback.contract_id,
            db=db,
            progress_summary=callback.progress_summary,
        )
    if callback.action_key == "progress_select_task":
        return _handle_progress_select_task(
            actor_user_id=callback.recipient_user_id,
            contract_id=callback.contract_id,
            db=db,
            progress_query_id=callback.progress_query_id,
        )
    if callback.action_key in {
        "progress_mark_completed",
        "progress_mark_in_progress",
        "progress_mark_delayed",
        "progress_mark_blocked",
        "progress_no_such_task",
    }:
        return _handle_progress_card_action(
            actor_user_id=callback.recipient_user_id,
            contract_id=callback.contract_id,
            db=db,
            action_key=callback.action_key,
            progress_query_id=callback.progress_query_id,
            progress_text=callback.progress_text or callback.progress_summary or callback.reason,
            new_deadline=callback.new_deadline or callback.deadline,
        )
    if callback.action_key == "change_proposal_approve":
        return _handle_change_proposal_review(
            actor_user_id=callback.recipient_user_id,
            contract_id=callback.contract_id,
            db=db,
            proposal_id=callback.proposal_id,
            approved=True,
        )
    if callback.action_key == "change_proposal_reject":
        return _handle_change_proposal_review(
            actor_user_id=callback.recipient_user_id,
            contract_id=callback.contract_id,
            db=db,
            proposal_id=callback.proposal_id,
            approved=False,
        )

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported callback action_key")


@app.post("/events/meeting")
def ingest_meeting(payload: EventIn, db: Session = Depends(get_db)) -> dict:
    return _ingest_source_event("meeting", payload, db, auto_mark_pending=True)


@app.post("/events/group-message")
def ingest_group_message(payload: EventIn, db: Session = Depends(get_db)) -> dict:
    return _ingest_source_event("group_message", payload, db, auto_mark_pending=True)


@app.post("/cards/initiator/confirm")
def initiator_confirm(payload: ContractActionIn, db: Session = Depends(get_db)) -> dict:
    return _handle_initiator_confirm(payload.actor_user_id, payload.contract_id, db)


@app.post("/cards/initiator/ignore")
def initiator_ignore(payload: ContractActionIn, db: Session = Depends(get_db)) -> dict:
    return _handle_initiator_ignore(payload.actor_user_id, payload.contract_id, db)


@app.post("/cards/initiator/request-resource-search")
def initiator_request_resource_search(payload: ContractActionIn, db: Session = Depends(get_db)) -> dict:
    return _handle_resource_search(payload.actor_user_id, payload.contract_id, db, "initiator")


@app.post("/cards/assignee/accept")
def assignee_accept_card(payload: ContractActionIn, db: Session = Depends(get_db)) -> dict:
    return _handle_assignee_accept(payload.actor_user_id, payload.contract_id, db)


@app.post("/cards/assignee/propose-change")
def assignee_propose_change_card(payload: AssigneeChangeIn, db: Session = Depends(get_db)) -> dict:
    return _handle_assignee_propose_change(
        actor_user_id=payload.actor_user_id,
        contract_id=payload.contract_id,
        db=db,
        title=payload.title,
        description=payload.description,
        deadline=payload.deadline,
        reason=payload.reason,
    )


@app.post("/cards/assignee/ignore")
def assignee_ignore(payload: ContractActionIn, db: Session = Depends(get_db)) -> dict:
    return _handle_assignee_ignore(payload.actor_user_id, payload.contract_id, db)


@app.post("/cards/assignee/request-resource-search")
def assignee_request_resource_search(payload: ContractActionIn, db: Session = Depends(get_db)) -> dict:
    return _handle_resource_search(payload.actor_user_id, payload.contract_id, db, "assignee")


@app.post("/progress/query")
def progress_query(payload: ProgressQueryIn, db: Session = Depends(get_db)) -> dict:
    requester = get_or_create_user(db, payload.requester_user_id)
    assignee = get_or_create_user(db, payload.assignee_user_id)
    contract = find_matching_contract_for_progress(
        db,
        requester_user_id=requester.id,
        assignee_user_id=assignee.id,
        query_text=payload.query_text,
    )
    if not contract:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No matching active task contract found")

    initiator = get_or_create_user(db, contract.initiator_user_id)
    if not can_reconcile_pair(requester, initiator, assignee):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Progress reconciliation requires both initiator and assignee authorization",
        )

    progress_query_record = create_progress_query(
        db,
        external_event_id=None,
        requester_user_id=requester.id,
        assignee_user_id=assignee.id,
        matched_contract_id=contract.id,
        query_text=payload.query_text,
        query_status=QUERY_STATUS_PENDING,
        raw_payload_json={"source": "/progress/query"},
    )
    card = build_progress_confirm_card(
        contract,
        assignee.id,
        payload.query_text,
        progress_query=progress_query_record,
        requester_user_id=requester.id,
    )
    delivery = feishu_client.send_card(assignee.id, card)
    record_card_action(
        db,
        "progress_query",
        requester.id,
        contract.id,
        {"assignee_user_id": assignee.id, "query_text": payload.query_text},
    )
    db.commit()
    return {"contract_id": contract.id, "progress_query_id": progress_query_record.id, "progress_card": delivery}


@app.post("/cards/progress/confirm")
def progress_confirm(payload: ProgressConfirmIn, db: Session = Depends(get_db)) -> dict:
    return _handle_progress_confirm(payload.actor_user_id, payload.contract_id, db, payload.progress_summary)


@app.get("/task-contracts/{contract_id}")
def get_task_contract(contract_id: int, db: Session = Depends(get_db)) -> dict:
    contract = _get_contract(db, contract_id)
    return _contract_response(contract)


@app.get("/task-contracts/{contract_id}/projections")
def get_task_contract_projections(contract_id: int, db: Session = Depends(get_db)) -> dict:
    contract = _get_contract(db, contract_id)
    return {
        "contract_id": contract.id,
        "projections": [
            {
                "owner_user_id": projection.owner_user_id,
                "role": projection.role,
                "todo_provider": projection.todo_provider,
                "external_record_id": projection.external_record_id,
                "projection_status": projection.status,
                "last_synced_at": projection.last_synced_at.isoformat() if projection.last_synced_at else None,
            }
            for projection in contract.todo_projections
        ],
    }


@app.post("/debug/bitable/dry-run-create")
def debug_bitable_dry_run_create(payload: DebugBitableDryRunCreateIn, db: Session = Depends(get_db)) -> dict:
    contract = _get_contract(db, payload.contract_id)
    role = _role_for_owner(contract, payload.owner_user_id)
    fields = map_contract_to_bitable_fields(payload.owner_user_id, contract, role, get_settings())
    return {
        "contract_id": contract.id,
        "owner_user_id": payload.owner_user_id,
        "role": role,
        "fields": fields,
    }


@app.post("/debug/minutes/parse-link")
def debug_minutes_parse_link(payload: DebugMinutesParseLinkIn) -> dict:
    return {
        "is_minutes_link": is_minutes_link(payload.text),
        "minutes_token": extract_minutes_token(payload.text),
        "minutes_url": extract_minutes_url(payload.text),
    }


@app.post("/debug/minutes/extract-tasks")
def debug_minutes_extract_tasks(payload: DebugMinutesExtractTasksIn) -> dict:
    content = create_minutes_backend(get_settings()).get_minutes_content(payload.minutes_token_or_url)
    normalized = normalize_minutes_content(content, get_settings())
    event_payload = EventIn(
        source_id=payload.minutes_token_or_url,
        external_event_id=f"debug-minutes:{payload.minutes_token_or_url}",
        text=normalized.full_text,
        sender_user_id="u_initiator",
        participant_user_ids=normalized.participants,
        initiator_user_id="u_initiator",
        source_link=normalized.source_link or payload.minutes_token_or_url,
        parsed_context_json=_normalized_context(normalized),
    )
    source_event = SourceEvent(
        id=0,
        event_type="meeting",
        source_id=event_payload.source_id,
        sender_user_id=event_payload.sender_user_id,
        raw_text=event_payload.text,
        participant_user_ids=event_payload.participant_user_ids,
        parsed_context_json=event_payload.parsed_context_json,
    )
    candidates = extract_task_candidates(source_event, event_payload)
    return {
        "minutes_token_or_url": payload.minutes_token_or_url,
        "normalized": event_payload.parsed_context_json,
        "task_candidates": [candidate.model_dump(mode="json") for candidate in candidates],
    }


@app.post("/debug/resources/search")
def debug_resources_search(payload: DebugResourceSearchIn, db: Session = Depends(get_db)) -> dict:
    contract = _get_contract(db, payload.contract_id)
    result = _run_resource_search(payload.user_id, contract, db, write_back=payload.write_back, fail_soft=False)
    if payload.write_back:
        db.commit()
    return _resource_result_response(result)


@app.post("/debug/resources/build-queries")
def debug_resources_build_queries(payload: DebugResourceBuildQueriesIn, db: Session = Depends(get_db)) -> dict:
    contract = _get_contract(db, payload.contract_id)
    return {
        "contract_id": contract.id,
        "search_queries": build_resource_queries(contract, contract.source_event, get_settings()),
        "resource_keywords": contract.resource_keywords,
        "mentioned_resources": contract.mentioned_resources,
        "project_name": contract.project_name,
        "evidence": contract.evidence,
    }


@app.post("/debug/progress/query")
def debug_progress_query(payload: DebugProgressQueryIn, db: Session = Depends(get_db)) -> dict:
    requester = get_or_create_user(db, payload.requester_user_id)
    assignee = get_or_create_user(db, payload.assignee_user_id) if payload.assignee_user_id else None
    result = _prepare_progress_query_response(
        db=db,
        requester_user_id=requester.id,
        assignee_user_id=assignee.id if assignee else None,
        query_text=payload.query_text,
        external_event_id=None,
        raw_payload_json={"source": "/debug/progress/query"},
        source_event=None,
        send_cards=False,
    )
    db.commit()
    return result


@app.post("/debug/progress/confirm")
def debug_progress_confirm(payload: DebugProgressConfirmIn, db: Session = Depends(get_db)) -> dict:
    progress_query = _get_progress_query(db, payload.progress_query_id)
    if not progress_query.matched_contract_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No matched task contract")
    result = _handle_progress_card_action(
        actor_user_id=payload.assignee_user_id,
        contract_id=progress_query.matched_contract_id,
        db=db,
        action_key=payload.action_key,
        progress_query_id=payload.progress_query_id,
        progress_text=payload.progress_text,
        new_deadline=payload.new_deadline,
    )
    return {
        "updated_task_contract": result["updated_task_contract"],
        "response_summary": result["response_summary"],
        "generated_reply_payload": result["generated_reply_payload"],
    }


@app.post("/dev/auth-grants")
def dev_create_auth_grant(payload: DevAuthGrantIn, db: Session = Depends(get_db)) -> dict:
    grant = create_auth_grant(
        db,
        user_id=payload.user_id,
        scope=payload.scope,
        subject_type=payload.subject_type,
        subject_id=payload.subject_id,
    )
    db.commit()
    return {
        "grant_id": grant.id,
        "user_id": grant.user_id,
        "scope": grant.scope,
        "subject_type": grant.subject_type,
        "subject_id": grant.subject_id,
    }


def _handle_initiator_confirm(actor_user_id: str, contract_id: int, db: Session) -> dict:
    contract = _get_contract(db, contract_id)
    actor = get_or_create_user(db, actor_user_id)
    if not can_confirm_as_initiator(actor, contract):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the initiator can confirm")

    existing_action = get_existing_card_action(db, "initiator_confirm", actor.id, contract.id)
    state_changed = False
    if contract.status in {TaskStatus.CANDIDATE_EXTRACTED.value, TaskStatus.PENDING_INITIATOR_CONFIRM.value}:
        _transition_or_conflict(confirm_initiator, contract)
        state_changed = True
    elif not existing_action and contract.status not in {
        TaskStatus.PENDING_ASSIGNEE_CONFIRM.value,
        TaskStatus.ACTIVE.value,
        TaskStatus.PROGRESS_UPDATED.value,
        TaskStatus.CHANGE_PENDING_INITIATOR_REVIEW.value,
        TaskStatus.COMPLETED.value,
    }:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Cannot confirm from {contract.status}")

    todo = create_todo_projection(db, contract, actor=actor, owner=actor, role="initiator")
    external_record_id = _ensure_external_projection(todo, contract)
    assignee = get_or_create_user(db, contract.assignee_user_id)
    delivery = None
    if state_changed and not existing_action:
        card = build_assignee_confirm_card(contract, assignee.id)
        delivery = feishu_client.send_card(assignee.id, card)
        record_card_action(
            db,
            "initiator_confirm",
            actor.id,
            contract.id,
            {"created_todo_projection_id": todo.id},
        )

    db.commit()
    db.refresh(contract)
    return {
        "contract_id": contract.id,
        "status": contract.status,
        "initiator_todo_projection_id": todo.id,
        "external_record_id": external_record_id,
        "assignee_card": delivery,
        "idempotent": bool(existing_action and not state_changed),
    }


def _handle_initiator_ignore(actor_user_id: str, contract_id: int, db: Session) -> dict:
    contract = _get_contract(db, contract_id)
    actor = get_or_create_user(db, actor_user_id)
    if not can_confirm_as_initiator(actor, contract):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the initiator can ignore")

    existing_action = get_existing_card_action(db, "initiator_ignore", actor.id, contract.id)
    if contract.status != TaskStatus.IGNORED.value:
        _transition_or_conflict(ignore_contract, contract)
    if not existing_action:
        record_card_action(db, "initiator_ignore", actor.id, contract.id)
    db.commit()
    db.refresh(contract)
    return {"contract_id": contract.id, "status": contract.status, "idempotent": bool(existing_action)}


def _handle_assignee_accept(actor_user_id: str, contract_id: int, db: Session) -> dict:
    contract = _get_contract(db, contract_id)
    actor = get_or_create_user(db, actor_user_id)
    if not can_confirm_as_assignee(actor, contract):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the assignee can accept")

    existing_action = get_existing_card_action(db, "assignee_accept", actor.id, contract.id)
    if contract.status == TaskStatus.PENDING_ASSIGNEE_CONFIRM.value:
        _transition_or_conflict(assignee_accept, contract)
    elif not existing_action and contract.status not in {
        TaskStatus.ACTIVE.value,
        TaskStatus.PROGRESS_UPDATED.value,
        TaskStatus.COMPLETED.value,
    }:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Cannot accept from {contract.status}")

    todo = create_todo_projection(db, contract, actor=actor, owner=actor, role="assignee")
    external_record_id = _ensure_external_projection(todo, contract)
    if not existing_action:
        record_card_action(
            db,
            "assignee_accept",
            actor.id,
            contract.id,
            {"created_todo_projection_id": todo.id},
        )

    db.commit()
    db.refresh(contract)
    return {
        "contract_id": contract.id,
        "status": contract.status,
        "assignee_todo_projection_id": todo.id,
        "external_record_id": external_record_id,
        "idempotent": bool(existing_action),
    }


def _handle_assignee_propose_change(
    actor_user_id: str,
    contract_id: int,
    db: Session,
    title: str | None,
    description: str | None,
    deadline: date | None,
    reason: str | None,
) -> dict:
    contract = _get_contract(db, contract_id)
    actor = get_or_create_user(db, actor_user_id)
    if not can_confirm_as_assignee(actor, contract):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the assignee can propose changes")
    if not any([title, description, deadline]):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No proposed changes provided")

    existing_proposal = find_matching_change_proposal(
        db,
        contract,
        proposer=actor,
        title=title,
        description=description,
        deadline=deadline,
    )
    if contract.status == TaskStatus.CHANGE_PENDING_INITIATOR_REVIEW.value and existing_proposal:
        return {
            "contract_id": contract.id,
            "status": contract.status,
            "change_proposal_id": existing_proposal.id,
            "idempotent": True,
        }
    if contract.status == TaskStatus.CHANGE_PENDING_INITIATOR_REVIEW.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A change proposal is already pending review")

    proposal = create_change_proposal(
        db,
        contract,
        proposer=actor,
        title=title,
        description=description,
        deadline=deadline,
        reason=reason,
    )
    _transition_or_conflict(assignee_propose_change, contract)

    card = build_change_proposal_card(contract, proposal, contract.initiator_user_id)
    delivery = feishu_client.send_card(contract.initiator_user_id, card)
    record_card_action(
        db,
        "assignee_propose_change",
        actor.id,
        contract.id,
        {"proposal_id": proposal.id},
    )
    db.commit()
    db.refresh(contract)
    return {
        "contract_id": contract.id,
        "status": contract.status,
        "change_proposal_id": proposal.id,
        "initiator_card": delivery,
    }


def _handle_assignee_ignore(actor_user_id: str, contract_id: int, db: Session) -> dict:
    contract = _get_contract(db, contract_id)
    actor = get_or_create_user(db, actor_user_id)
    if not can_confirm_as_assignee(actor, contract):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the assignee can ignore")

    existing_action = get_existing_card_action(db, "assignee_ignore", actor.id, contract.id)
    if contract.status != TaskStatus.IGNORED.value:
        _transition_or_conflict(ignore_contract, contract)
    if not existing_action:
        record_card_action(db, "assignee_ignore", actor.id, contract.id)
    db.commit()
    db.refresh(contract)
    return {"contract_id": contract.id, "status": contract.status, "idempotent": bool(existing_action)}


def _handle_resource_search(actor_user_id: str, contract_id: int, db: Session, role: str) -> dict:
    contract = _get_contract(db, contract_id)
    actor = get_or_create_user(db, actor_user_id)
    if role == "initiator":
        if not can_confirm_as_initiator(actor, contract):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the initiator can request resources")
        action_key = "initiator_request_resource_search"
    elif role == "assignee":
        if not can_confirm_as_assignee(actor, contract):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the assignee can request resources")
        action_key = "assignee_request_resource_search"
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown resource search role")

    result = _run_resource_search(actor.id, contract, db, write_back=True, fail_soft=False)
    card = (
        build_initiator_confirm_card(contract, actor.id)
        if role == "initiator"
        else build_assignee_confirm_card(contract, actor.id)
    )
    record_card_action(
        db,
        action_key,
        actor.id,
        contract.id,
        {"search_queries": result.search_queries},
    )
    db.commit()
    return {
        "contract_id": contract.id,
        "resource_search_status": contract.resource_search_status,
        "related_resources": contract.related_resources_json,
        "search_queries": result.search_queries,
        "card": card,
    }


def _prepare_progress_query_response(
    *,
    db: Session,
    requester_user_id: str,
    assignee_user_id: str | None,
    query_text: str,
    external_event_id: str | None,
    raw_payload_json: dict,
    source_event: SourceEvent | None,
    send_cards: bool,
) -> dict:
    intent = extract_progress_query_entities(query_text, requester_user_id=requester_user_id)
    assignee_id = assignee_user_id or intent.assignee_user_id
    if assignee_id:
        get_or_create_user(db, assignee_id)

    matches = match_task_contract(
        db,
        requester_user_id=requester_user_id,
        assignee_user_id=assignee_id,
        query_text=query_text,
        source_event=source_event,
    )
    query_status = QUERY_STATUS_NO_MATCHING_TASK if not matches else QUERY_STATUS_PENDING
    progress_query = create_progress_query(
        db,
        external_event_id=external_event_id,
        requester_user_id=requester_user_id,
        assignee_user_id=assignee_id,
        matched_contract_id=matches[0].id if len(matches) == 1 else None,
        query_text=query_text,
        query_status=query_status,
        raw_payload_json=raw_payload_json,
    )

    response: dict = {
        "detected_intent": detect_progress_query(query_text),
        "progress_query_id": progress_query.id,
        "progress_query_status": progress_query.query_status,
        "matched_contracts": [_compact_contract(contract) for contract in matches],
        "generated_card_json": None,
    }
    if not matches:
        progress_query.response_summary = build_progress_summary(progress_query, None)
        response["response_summary"] = progress_query.response_summary
        response["progress_query_status"] = progress_query.query_status
        return response

    if len(matches) > 1:
        card = build_progress_task_select_card(progress_query, matches, requester_user_id)
        delivery = feishu_client.send_card(requester_user_id, card) if send_cards else None
        response.update(
            {
                "progress_task_select_card": delivery,
                "generated_card_json": card,
            }
        )
        return response

    contract = matches[0]
    progress_query.matched_contract_id = contract.id
    progress_query.assignee_user_id = contract.assignee_user_id
    card = build_progress_confirm_card(
        contract,
        contract.assignee_user_id,
        query_text,
        progress_query=progress_query,
        requester_user_id=requester_user_id,
        chat_id=(source_event.event_metadata or {}).get("chat_id") if source_event else None,
    )
    delivery = feishu_client.send_card(contract.assignee_user_id, card) if send_cards else None
    response.update(
        {
            "contract_id": contract.id,
            "progress_card": delivery,
            "generated_card_json": card,
            "progress_query_status": progress_query.query_status,
        }
    )
    return response


def _handle_progress_select_task(
    actor_user_id: str,
    contract_id: int,
    db: Session,
    progress_query_id: int | None,
) -> dict:
    if progress_query_id is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="progress_query_id is required")
    progress_query = _get_progress_query(db, progress_query_id)
    if actor_user_id != progress_query.requester_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the requester can select the task")
    contract = _get_contract(db, contract_id)
    progress_query.matched_contract_id = contract.id
    progress_query.assignee_user_id = contract.assignee_user_id
    progress_query.query_status = QUERY_STATUS_PENDING
    card = build_progress_confirm_card(
        contract,
        contract.assignee_user_id,
        progress_query.query_text,
        progress_query=progress_query,
        requester_user_id=progress_query.requester_user_id,
    )
    delivery = feishu_client.send_card(contract.assignee_user_id, card)
    record_card_action(
        db,
        "progress_select_task",
        actor_user_id,
        contract.id,
        {"progress_query_id": progress_query.id},
    )
    db.commit()
    return {
        "contract_id": contract.id,
        "progress_query_id": progress_query.id,
        "progress_query_status": progress_query.query_status,
        "progress_card": delivery,
    }


def _handle_progress_card_action(
    *,
    actor_user_id: str,
    contract_id: int,
    db: Session,
    action_key: str,
    progress_query_id: int | None,
    progress_text: str | None,
    new_deadline: date | None,
) -> dict:
    contract = _get_contract(db, contract_id)
    actor = get_or_create_user(db, actor_user_id)
    if not can_confirm_as_assignee(actor, contract):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the assignee can confirm progress")

    progress_query = _get_progress_query(db, progress_query_id) if progress_query_id is not None else None
    existing_action = get_existing_card_action(db, action_key, actor.id, contract.id)
    if existing_action:
        if progress_query and not progress_query.response_summary:
            progress_query.response_summary = build_progress_summary(progress_query, contract)
        reply_payload = build_progress_reply_payload(progress_query, contract) if progress_query else None
        return {
            "contract_id": contract.id,
            "progress_query_id": progress_query.id if progress_query else None,
            "status": contract.status,
            "completion_status": contract.completion_status,
            "response_summary": progress_query.response_summary if progress_query else contract.progress_text,
            "generated_reply_payload": reply_payload,
            "updated_task_contract": _contract_response(contract),
            "idempotent": True,
        }

    if action_key == "progress_no_such_task":
        if progress_query:
            progress_query.query_status = QUERY_STATUS_NO_MATCHING_TASK
            progress_query.response_summary = build_progress_summary(progress_query, None)
        record_card_action(
            db,
            action_key,
            actor.id,
            contract.id,
            {"progress_query_id": progress_query_id},
        )
        db.commit()
        reply_payload = build_progress_reply_payload(progress_query, None) if progress_query else None
        return {
            "contract_id": contract.id,
            "progress_query_id": progress_query.id if progress_query else None,
            "status": contract.status,
            "completion_status": contract.completion_status,
            "response_summary": progress_query.response_summary if progress_query else "Task not confirmed.",
            "generated_reply_payload": reply_payload,
            "updated_task_contract": _contract_response(contract),
            "idempotent": False,
        }

    completion_status = _completion_status_for_action(action_key)
    default_progress_text = _default_progress_text(completion_status)
    contract.completion_status = completion_status
    contract.progress_text = progress_text or default_progress_text
    contract.progress_summary = contract.progress_text
    contract.progress_updated_at = utc_now()

    if action_key == "progress_mark_completed":
        if contract.status in {TaskStatus.ACTIVE.value, TaskStatus.PROGRESS_UPDATED.value}:
            _transition_or_conflict(complete_contract, contract)
    elif action_key == "progress_mark_delayed" and new_deadline and new_deadline != contract.deadline:
        proposal = find_matching_change_proposal(
            db,
            contract,
            proposer=actor,
            deadline=new_deadline,
        )
        if proposal is None:
            proposal = create_change_proposal(
                db,
                contract,
                proposer=actor,
                deadline=new_deadline,
                reason=contract.progress_text,
            )
        if contract.status in {TaskStatus.ACTIVE.value, TaskStatus.PROGRESS_UPDATED.value}:
            _transition_or_conflict(assignee_propose_change, contract)
    elif contract.status in {TaskStatus.ACTIVE.value, TaskStatus.PROGRESS_UPDATED.value}:
        _transition_or_conflict(record_progress_update, contract)

    if progress_query:
        progress_query.query_status = QUERY_STATUS_CONFIRMED
        progress_query.matched_contract_id = contract.id
        progress_query.assignee_user_id = contract.assignee_user_id
        progress_query.response_summary = build_progress_summary(progress_query, contract)

    _sync_assignee_projection_progress(contract)
    record_card_action(
        db,
        action_key,
        actor.id,
        contract.id,
        {
            "progress_query_id": progress_query_id,
            "progress_text": contract.progress_text,
            "new_deadline": new_deadline.isoformat() if new_deadline else None,
        },
    )
    db.commit()
    db.refresh(contract)
    reply_payload = build_progress_reply_payload(progress_query, contract) if progress_query else None
    return {
        "contract_id": contract.id,
        "progress_query_id": progress_query.id if progress_query else None,
        "status": contract.status,
        "completion_status": contract.completion_status,
        "response_summary": progress_query.response_summary if progress_query else contract.progress_text,
        "generated_reply_payload": reply_payload,
        "updated_task_contract": _contract_response(contract),
        "idempotent": False,
    }


def _handle_progress_confirm(
    actor_user_id: str,
    contract_id: int,
    db: Session,
    progress_summary: str | None,
) -> dict:
    if not progress_summary:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="progress_summary is required")

    contract = _get_contract(db, contract_id)
    actor = get_or_create_user(db, actor_user_id)
    if not can_confirm_as_assignee(actor, contract):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the assignee can confirm progress")

    existing_action = get_existing_card_action(db, "progress_confirm", actor.id, contract.id)
    if not existing_action or contract.progress_summary != progress_summary:
        _transition_or_conflict(record_progress_update, contract)
        contract.progress_summary = progress_summary
        contract.progress_text = progress_summary
        contract.completion_status = COMPLETION_IN_PROGRESS
        contract.progress_updated_at = utc_now()
        _sync_assignee_projection_progress(contract)
    if not existing_action:
        record_card_action(
            db,
            "progress_confirm",
            actor.id,
            contract.id,
            {"progress_summary": progress_summary},
        )
    db.commit()
    db.refresh(contract)
    summary = f"{actor.display_name or actor.id} confirmed progress for '{contract.title}': {contract.progress_summary}"
    return {"contract_id": contract.id, "status": contract.status, "group_reply_summary": summary}


def _handle_change_proposal_review(
    actor_user_id: str,
    contract_id: int,
    db: Session,
    proposal_id: int | None,
    approved: bool,
) -> dict:
    action_key = "change_proposal_approve" if approved else "change_proposal_reject"
    contract = _get_contract(db, contract_id)
    actor = get_or_create_user(db, actor_user_id)
    if not can_confirm_as_initiator(actor, contract):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the initiator can review changes")

    proposal = _get_change_proposal(db, contract.id, proposal_id)
    existing_action = get_existing_card_action(db, action_key, actor.id, contract.id)
    if proposal.status in {"approved", "rejected"} and existing_action:
        return {
            "contract_id": contract.id,
            "status": contract.status,
            "change_proposal_id": proposal.id,
            "proposal_status": proposal.status,
            "idempotent": True,
        }

    if approved:
        if proposal.proposed_title is not None:
            contract.title = proposal.proposed_title
        if proposal.proposed_description is not None:
            contract.description = proposal.proposed_description
        if proposal.proposed_deadline is not None:
            contract.deadline = proposal.proposed_deadline
        proposal.status = "approved"
    else:
        proposal.status = "rejected"

    if contract.status == TaskStatus.CHANGE_PENDING_INITIATOR_REVIEW.value:
        _transition_or_conflict(resolve_change_review, contract)
    if approved:
        _refresh_local_projections(contract)
        _sync_existing_external_projections(contract)
    if not existing_action:
        record_card_action(
            db,
            action_key,
            actor.id,
            contract.id,
            {"proposal_id": proposal.id, "approved": approved},
        )

    db.commit()
    db.refresh(contract)
    return {
        "contract_id": contract.id,
        "status": contract.status,
        "change_proposal_id": proposal.id,
        "proposal_status": proposal.status,
    }


def _handle_ask_progress_event(source_event: SourceEvent, payload: EventIn, db: Session) -> dict:
    requester = get_or_create_user(db, payload.sender_user_id)
    intent = extract_progress_query_entities(payload.text, requester_user_id=requester.id)
    assignee_user_id = payload.assignee_user_id or intent.assignee_user_id
    if not assignee_user_id:
        assignee_user_id = _infer_assignee_from_participants(payload.participant_user_ids, requester.id)
    return _prepare_progress_query_response(
        db=db,
        requester_user_id=requester.id,
        assignee_user_id=assignee_user_id,
        query_text=payload.text,
        external_event_id=source_event.external_event_id,
        raw_payload_json={
            "source_event_id": source_event.id,
            "source": "/feishu/events",
            "raw_payload": payload.raw_payload,
        },
        source_event=source_event,
        send_cards=True,
    )


def _ingest_source_event(
    event_type: str,
    payload: EventIn,
    db: Session,
    auto_mark_pending: bool,
) -> dict:
    existing_event = find_source_event_by_external_id(db, payload.external_event_id)
    if existing_event:
        return _source_event_response(existing_event, db, deduplicated=True)

    if event_type == "meeting" and not (payload.parsed_context_json or {}).get("action_sections"):
        payload = _hydrate_minutes_payload(payload)

    sender = get_or_create_user(db, payload.sender_user_id)
    for user_id in set(
        payload.participant_user_ids + [payload.initiator_user_id or sender.id, payload.assignee_user_id or sender.id]
    ):
        if user_id:
            get_or_create_user(db, user_id)

    source_event = SourceEvent(
        event_type=event_type,
        source_id=payload.source_id,
        external_event_id=payload.external_event_id,
        sender_user_id=sender.id,
        raw_text=payload.text,
        participant_user_ids=payload.participant_user_ids,
        event_metadata={
            "project_name": payload.project_name,
            "chat_id": payload.chat_id,
            "message_id": payload.message_id,
            "source_link": payload.source_link,
            "raw_payload": payload.raw_payload,
        },
        parsed_context_json=payload.parsed_context_json,
    )
    db.add(source_event)
    db.flush()
    intent = route_source_event(source_event)

    response: dict = {
        "source_event_id": source_event.id,
        "external_event_id": source_event.external_event_id,
        "intent": intent,
        "deduplicated": False,
    }
    if intent == "ask_progress":
        response.update(_handle_ask_progress_event(source_event, payload, db))
    elif intent == "assign_task":
        candidates = extract_task_candidates(source_event, payload)
        contracts: list[TaskContract] = []
        deliveries = []
        for candidate in candidates:
            contract = create_task_contract(db, source_event, candidate)
            contracts.append(contract)
            if auto_mark_pending and candidate.confidence >= _confidence_threshold():
                _transition_or_conflict(mark_pending_initiator_confirm, contract)
            if get_settings().resource_search_enable_for_initiator:
                _run_resource_search(contract.initiator_user_id, contract, db, write_back=True, fail_soft=True)
            card = build_initiator_confirm_card(contract, contract.initiator_user_id)
            deliveries.append(feishu_client.send_card(contract.initiator_user_id, card))
        first_contract = contracts[0] if contracts else None
        first_candidate = candidates[0] if candidates else None
        if first_contract and first_candidate:
            response.update(
                {
                    "task_candidate": first_candidate.model_dump(mode="json"),
                    "task_candidates": [candidate.model_dump(mode="json") for candidate in candidates],
                    "contract_id": first_contract.id,
                    "contract_ids": [contract.id for contract in contracts],
                    "contract_status": first_contract.status,
                    "initiator_card": deliveries[0] if deliveries else None,
                    "initiator_cards": deliveries,
                }
            )
    db.commit()
    return response


def _is_simulated_feishu_event(payload: dict) -> bool:
    return payload.get("event_type") in {"group_message", "meeting_minutes"} and "event_id" in payload


def _is_simulated_card_callback(payload: dict) -> bool:
    return {"action_key", "contract_id", "recipient_user_id"}.issubset(payload.keys())


def _event_in_from_feishu(payload: FeishuEventIn) -> EventIn:
    text = payload.text
    if payload.event_type == "meeting_minutes" and not text and payload.minutes_token:
        text = payload.minutes_token
    if not text:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="text is required")

    metadata = payload.raw_event or {}
    return EventIn(
        source_id=payload.event_id,
        external_event_id=payload.event_id,
        text=text,
        sender_user_id=payload.sender_user_id,
        participant_user_ids=payload.participant_user_ids,
        initiator_user_id=payload.initiator_user_id,
        assignee_user_id=payload.assignee_user_id,
        project_name=payload.project_name or metadata.get("project_name"),
        source_link=payload.minutes_token if payload.event_type == "meeting_minutes" else None,
    )


def _event_in_from_source_event_create(source_event: SourceEventCreate) -> EventIn:
    return EventIn(
        source_id=source_event.message_id or source_event.external_event_id,
        external_event_id=source_event.external_event_id,
        text=source_event.text,
        sender_user_id=source_event.trigger_user_id,
        participant_user_ids=source_event.participant_user_ids,
        initiator_user_id=source_event.trigger_user_id,
        assignee_user_id=None,
        project_name=None,
        chat_id=source_event.chat_id,
        message_id=source_event.message_id,
        source_link=source_event.source_link,
        raw_payload=source_event.raw_payload,
        parsed_context_json={"source_type": source_event.source_type},
    )


def _source_event_response(source_event: SourceEvent, db: Session, deduplicated: bool) -> dict:
    contract = find_contract_by_source_event(db, source_event.id)
    progress_query = db.scalar(select(ProgressQuery).where(ProgressQuery.external_event_id == source_event.external_event_id))
    response = {
        "source_event_id": source_event.id,
        "external_event_id": source_event.external_event_id,
        "intent": source_event.intent,
        "deduplicated": deduplicated,
    }
    if contract:
        all_contracts = db.scalars(select(TaskContract).where(TaskContract.source_event_id == source_event.id)).all()
        response.update(
            {
                "contract_id": contract.id,
                "contract_ids": [item.id for item in all_contracts],
                "contract_status": contract.status,
            }
        )
    if progress_query:
        response.update(
            {
                "progress_query_id": progress_query.id,
                "progress_query_status": progress_query.query_status,
                "contract_id": progress_query.matched_contract_id,
                "response_summary": progress_query.response_summary,
            }
        )
    return response


def _contract_response(contract: TaskContract) -> dict:
    return {
        "contract_id": contract.id,
        "source_event_id": contract.source_event_id,
        "status": contract.status,
        "title": contract.title,
        "description": contract.description,
        "project_name": contract.project_name,
        "initiator_user_id": contract.initiator_user_id,
        "assignee_user_id": contract.assignee_user_id,
        "deadline": contract.deadline.isoformat() if contract.deadline else None,
        "progress_summary": contract.progress_summary,
        "progress_text": contract.progress_text,
        "progress_updated_at": contract.progress_updated_at.isoformat() if contract.progress_updated_at else None,
        "completion_status": contract.completion_status,
        "related_resources": contract.related_resources_json,
        "resource_search_status": contract.resource_search_status,
        "resource_search_error": contract.resource_search_error,
        "todo_projection_count": len(contract.todo_projections),
        "change_proposal_count": len(contract.change_proposals),
    }


def _ensure_external_projection(projection: PersonalTodoProjection, contract: TaskContract) -> str:
    if projection.external_record_id:
        return projection.external_record_id

    backend = create_todo_backend(feishu_client, get_settings())
    existing_external_id = backend.find_existing_projection(projection.owner_user_id, contract.id)
    external_record_id = existing_external_id or backend.create_personal_todo_projection(
        projection.owner_user_id,
        contract,
        projection.role,
    )
    projection.todo_provider = backend.provider
    projection.external_record_id = external_record_id
    projection.last_synced_at = utc_now()
    return external_record_id


def _run_resource_search(
    user_id: str,
    contract: TaskContract,
    db: Session,
    write_back: bool,
    fail_soft: bool,
) -> ResourceSearchResult:
    try:
        if write_back:
            contract.resource_search_status = "pending"
            contract.resource_search_error = None
            db.flush()
        backend = create_resource_search_backend(feishu_client, get_settings())
        result = backend.search_resources(user_id, contract, contract.source_event)
        if write_back:
            contract.related_resources_json = {
                "high_confidence": result.high_confidence,
                "low_confidence": result.low_confidence,
                "backend": result.backend,
                "dry_run": result.dry_run,
                "search_queries": result.search_queries,
            }
            contract.resource_search_status = "completed"
            contract.resource_search_error = None
            db.flush()
        return result
    except Exception as exc:
        if write_back:
            contract.resource_search_status = "failed"
            contract.resource_search_error = str(exc)
            db.flush()
        if fail_soft:
            return ResourceSearchResult(
                high_confidence=[],
                low_confidence=[],
                raw_results=[],
                search_queries=[],
                backend=get_settings().resource_search_backend,
                dry_run=True,
            )
        raise


def _resource_result_response(result: ResourceSearchResult) -> dict:
    return {
        "high_confidence": result.high_confidence,
        "low_confidence": result.low_confidence,
        "raw_results": result.raw_results,
        "search_queries": result.search_queries,
        "backend": result.backend,
        "dry_run": result.dry_run,
    }


def _refresh_local_projections(contract: TaskContract) -> None:
    for projection in contract.todo_projections:
        projection.title = contract.title
        projection.description = contract.description
        projection.deadline = contract.deadline
        projection.status = contract.status
        projection.updated_at = utc_now()


def _sync_existing_external_projections(contract: TaskContract) -> None:
    backend = create_todo_backend(feishu_client, get_settings())
    for projection in contract.todo_projections:
        if not projection.external_record_id:
            continue
        fields = map_contract_to_bitable_fields(projection.owner_user_id, contract, projection.role, get_settings())
        backend.update_personal_todo_projection(
            projection.owner_user_id,
            projection.external_record_id,
            fields,
        )
        projection.todo_provider = backend.provider
        projection.last_synced_at = utc_now()


def _sync_assignee_projection_progress(contract: TaskContract) -> None:
    projection = next(
        (
            item
            for item in contract.todo_projections
            if item.owner_user_id == contract.assignee_user_id and item.role == "assignee"
        ),
        None,
    )
    if projection is None:
        return
    projection.status = contract.completion_status
    projection.updated_at = utc_now()
    if not projection.external_record_id:
        return
    backend = create_todo_backend(feishu_client, get_settings())
    settings = get_settings()
    backend.update_personal_todo_projection(
        projection.owner_user_id,
        projection.external_record_id,
        {
            settings.feishu_todo_status_field: contract.completion_status,
            "progress_text": contract.progress_text,
            "progress_updated_at": contract.progress_updated_at.isoformat() if contract.progress_updated_at else None,
        },
    )
    projection.todo_provider = backend.provider
    projection.last_synced_at = utc_now()


def _completion_status_for_action(action_key: str) -> str:
    mapping = {
        "progress_mark_completed": COMPLETION_COMPLETED,
        "progress_mark_in_progress": COMPLETION_IN_PROGRESS,
        "progress_mark_delayed": COMPLETION_DELAYED,
        "progress_mark_blocked": COMPLETION_BLOCKED,
    }
    if action_key not in mapping:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported progress action")
    return mapping[action_key]


def _default_progress_text(completion_status: str) -> str:
    return {
        COMPLETION_COMPLETED: "Completed.",
        COMPLETION_IN_PROGRESS: "In progress.",
        COMPLETION_DELAYED: "Delayed; deadline review may be required.",
        COMPLETION_BLOCKED: "Blocked and needs help.",
    }.get(completion_status, "Progress updated.")


def _compact_contract(contract: TaskContract) -> dict:
    return {
        "contract_id": contract.id,
        "title": contract.title,
        "project_name": contract.project_name,
        "assignee_user_id": contract.assignee_user_id,
        "status": contract.status,
        "completion_status": contract.completion_status,
        "deadline": contract.deadline.isoformat() if contract.deadline else None,
    }


def _infer_assignee_from_participants(participant_user_ids: list[str], requester_user_id: str) -> str | None:
    candidates = [user_id for user_id in participant_user_ids if user_id and user_id != requester_user_id]
    return candidates[0] if len(candidates) == 1 else None


def _role_for_owner(contract: TaskContract, owner_user_id: str) -> str:
    if owner_user_id == contract.initiator_user_id:
        return "initiator"
    if owner_user_id == contract.assignee_user_id:
        return "assignee"
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Owner is not part of this task contract")


def _hydrate_minutes_payload(payload: EventIn) -> EventIn:
    token_or_url = extract_minutes_token(payload.text) or extract_minutes_url(payload.text) or payload.source_link
    if not token_or_url:
        return payload
    content = create_minutes_backend(get_settings()).get_minutes_content(token_or_url)
    normalized = normalize_minutes_content(content, get_settings())
    return payload.model_copy(
        update={
            "text": normalized.full_text,
            "participant_user_ids": list(dict.fromkeys(payload.participant_user_ids + normalized.participants)),
            "source_link": normalized.source_link or payload.source_link or extract_minutes_url(payload.text),
            "parsed_context_json": _normalized_context(normalized),
        }
    )


def _normalized_context(normalized) -> dict:
    return {
        "source_type": "meeting_minutes",
        "title": normalized.title,
        "participants": normalized.participants,
        "action_sections": normalized.action_sections,
        "evidence_blocks": normalized.evidence_blocks,
        "source_link": normalized.source_link,
        "truncated": normalized.truncated,
    }


def _get_contract(db: Session, contract_id: int) -> TaskContract:
    contract = db.get(TaskContract, contract_id)
    if not contract:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task contract not found")
    return contract


def _get_progress_query(db: Session, progress_query_id: int) -> ProgressQuery:
    progress_query = db.get(ProgressQuery, progress_query_id)
    if not progress_query:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Progress query not found")
    return progress_query


def _get_change_proposal(db: Session, contract_id: int, proposal_id: int | None) -> ChangeProposal:
    if proposal_id is not None:
        proposal = db.get(ChangeProposal, proposal_id)
        if proposal and proposal.contract_id == contract_id:
            return proposal
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Change proposal not found")

    proposal = db.scalar(
        select(ChangeProposal)
        .where(ChangeProposal.contract_id == contract_id)
        .where(ChangeProposal.status == "pending_initiator_review")
        .order_by(ChangeProposal.id.desc())
    )
    if not proposal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Change proposal not found")
    return proposal


def _transition_or_conflict(transition_func, contract: TaskContract) -> None:
    try:
        transition_func(contract)
    except InvalidStateTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


def _confidence_threshold() -> float:
    try:
        return float(os.getenv("TEAMTASK_CONFIDENCE_THRESHOLD", "0.6"))
    except ValueError:
        return 0.6
