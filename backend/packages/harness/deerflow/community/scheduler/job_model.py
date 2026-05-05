"""Data model for scheduled tasks (jobs)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class SchedulePayload:
    """Unified payload model for scheduler jobs.
    
    Stored in APScheduler's JobStore and passed to job execution function.
    Channel-agnostic: all IM context (channel_name, chat_id, etc.) is preserved here.
    """

    schedule_id: str
    """Unique identifier for this schedule (e.g. uuid4 hex)."""

    mode: Literal["once", "interval", "cron"]
    """Task type. Current implementation uses 'once'; others are reserved for expansion."""

    action_type: Literal["remind", "execute"]
    """Action type. Current implementation supports 'remind'; 'execute' is reserved."""

    channel_name: str
    """IM channel routing key (e.g. 'feishu', 'slack')."""

    chat_id: str
    """Channel-specific conversation ID."""

    user_id: str
    """Original user who created the task."""

    content: str
    """Reminder text to send at trigger time."""

    run_at: str
    """ISO 8601 UTC time string for one-time execution."""

    timezone: str
    """IANA timezone name (for display, not scheduling—storage is always UTC)."""

    topic_id: str | None = None
    """Optional topic/channel ID for threaded conversations."""

    thread_ts: str | None = None
    """Optional platform thread timestamp (for grouped replies)."""

    thread_id: str | None = None
    """DeerFlow thread ID to prevent drift after /new operations."""

    created_at: float = field(default_factory=time.time)
    """Unix timestamp when the task was created."""

    @classmethod
    def from_dict(cls, data: dict) -> SchedulePayload:
        """Deserialize from dict (for job resumption after scheduler restart)."""
        return cls(**data)

    def to_dict(self) -> dict:
        """Serialize to dict for storage."""
        return {
            "schedule_id": self.schedule_id,
            "mode": self.mode,
            "action_type": self.action_type,
            "channel_name": self.channel_name,
            "chat_id": self.chat_id,
            "user_id": self.user_id,
            "content": self.content,
            "run_at": self.run_at,
            "timezone": self.timezone,
            "topic_id": self.topic_id,
            "thread_ts": self.thread_ts,
            "thread_id": self.thread_id,
            "created_at": self.created_at,
        }
