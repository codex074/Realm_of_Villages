"""Scheduling and cancelling of game events."""

from datetime import datetime

from sqlalchemy import delete, func
from sqlalchemy.orm import Session

from realm.core.types import EventType
from realm.db.models import Event


def schedule(s: Session, world_id: int, etype: EventType, due_at: datetime, payload: dict) -> Event:
    """Add a pending event for a world and return the flushed row."""
    event = Event(
        world_id=world_id,
        type=etype.value,
        due_at=due_at,
        payload=payload,
        created_at=func.now(),
    )
    s.add(event)
    s.flush()
    return event


def cancel_pending(s: Session, world_id: int, etype: EventType, match: dict) -> int:
    """Delete pending events of a world/type whose payload contains every key of match."""
    stmt = (
        delete(Event)
        .where(Event.world_id == world_id)
        .where(Event.type == etype.value)
        .where(Event.status == "pending")
        .where(Event.payload.contains(match))
    )
    result = s.execute(stmt)
    s.flush()
    return result.rowcount or 0
