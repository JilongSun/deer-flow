"""Scheduler job executor implementations."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from app.channels.message_bus import MessageBus, OutboundMessage

from .job_model import SchedulePayload

logger = logging.getLogger(__name__)


class SchedulerExecutor:
    """Executes scheduled jobs by action type.

    This class isolates job execution behavior from scheduler lifecycle logic,
    making it easier to add new actions (for example: execute) in the future.
    """

    def __init__(self, message_bus: MessageBus) -> None:
        self._bus = message_bus
        self._handlers: dict[str, Callable[[SchedulePayload], Awaitable[None]]] = {
            "remind": self._execute_remind,
        }

    def register_handler(
        self,
        action_type: str,
        handler: Callable[[SchedulePayload], Awaitable[None]],
    ) -> None:
        """Register or override an action handler.

        This supports feature growth without changing the executor core
        dispatch flow.
        """
        self._handlers[action_type] = handler

    def unregister_handler(self, action_type: str) -> None:
        """Remove an action handler if present."""
        self._handlers.pop(action_type, None)

    def has_handler(self, action_type: str) -> bool:
        """Whether an action handler is currently registered."""
        return action_type in self._handlers

    def list_actions(self) -> tuple[str, ...]:
        """List currently registered action types."""
        return tuple(self._handlers.keys())

    async def execute(self, payload: SchedulePayload) -> None:
        """Dispatch a scheduled payload by action type."""
        handler = self._handlers.get(payload.action_type)
        if handler is None:
            logger.warning(
                "Unsupported scheduler action_type=%s for schedule_id=%s",
                payload.action_type,
                payload.schedule_id,
            )
            return

        await handler(payload)

    async def _execute_remind(self, payload: SchedulePayload) -> None:
        """Send a reminder as an outbound message."""
        logger.info(
            "Executing reminder task: schedule_id=%s, channel=%s, chat_id=%s",
            payload.schedule_id,
            payload.channel_name,
            payload.chat_id,
        )

        try:
            outbound = OutboundMessage(
                channel_name=payload.channel_name,
                chat_id=payload.chat_id,
                thread_id=payload.thread_id or "",
                text=payload.content,
                artifacts=[],
                attachments=[],
                is_final=True,
                thread_ts=payload.thread_ts,
                metadata={
                    "source": "scheduler",
                    "schedule_id": payload.schedule_id,
                    "trigger_type": "once",
                    "is_system_initiated": True,
                    "original_user_id": payload.user_id,
                    "timezone": payload.timezone,
                },
            )

            await self._bus.publish_outbound(outbound)

            logger.info(
                "Reminder task completed: schedule_id=%s, delivered to %s",
                payload.schedule_id,
                payload.channel_name,
            )
        except Exception as exc:
            logger.exception(
                "Error executing reminder task %s: %s",
                payload.schedule_id,
                exc,
                extra={"schedule_id": payload.schedule_id, "channel": payload.channel_name},
            )
