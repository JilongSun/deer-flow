"""LangChain tool for scheduler (exposed to agent as @tool-decorated functions)."""

from __future__ import annotations

import logging
from typing import Literal

from langchain_core.tools import tool

from .service import get_scheduler_service

logger = logging.getLogger(__name__)


@tool
async def schedule_tool(
    action: Literal["create_once", "list", "cancel"],
    when: str | None = None,
    content: str | None = None,
    schedule_id: str | None = None,
    timezone: str | None = None,
    channel: str | None = None,
) -> dict:
    """Schedule reminder tasks or manage existing ones.
    
    This tool provides three main operations:
    
    1. **create_once**: Create a one-time reminder task
       - action: "create_once"
       - when: ISO 8601 datetime with timezone (e.g., "2026-05-05T14:35:00+08:00")
       - content: Reminder text to send
       - timezone: Optional IANA timezone name (extracted from 'when' if not provided)
       - Returns: {"success": true, "schedule_id": "..."}
       
    2. **list**: List all active scheduled tasks
       - action: "list"
       - Returns: {"success": true, "tasks": [...]}
       
    3. **cancel**: Cancel a scheduled task
       - action: "cancel"
       - schedule_id: The task ID to cancel
       - Returns: {"success": true}
    
    Args:
        action: Operation to perform: 'create_once', 'list', or 'cancel'.
        when: ISO 8601 datetime for 'create_once' (e.g., "2026-05-05T14:35:00+08:00").
        content: Reminder text for 'create_once'.
        schedule_id: Task ID for 'cancel'.
        timezone: Optional IANA timezone name (e.g., "Asia/Shanghai").
        channel: Channel hint (currently unused, for future compatibility).
        
    Returns:
        Result dict with "success" bool and operation-specific fields.
        For errors, returns {"success": false, "error": "message"}.
    """
    service = await get_scheduler_service()

    if service is None:
        return {
            "success": False,
            "error": "Scheduler service not running. Enable tools.schedule in config.yaml.",
        }

    try:
        if action == "create_once":
            # Validation
            if not when:
                return {"success": False, "error": "Parameter 'when' is required for create_once"}
            if not content:
                return {"success": False, "error": "Parameter 'content' is required for create_once"}

            # TODO: Extract channel_name, chat_id, user_id, thread_id from agent context.
            # For now, use placeholder values. In production, these come from
            # agent.state or channel context passed through middleware.
            schedule_id = await service.create_once(
                channel_name="feishu",  # Placeholder: should come from context
                chat_id="placeholder_chat",  # Placeholder
                user_id="placeholder_user",  # Placeholder
                content=content,
                run_at=when,
                timezone=timezone,
            )

            return {
                "success": True,
                "schedule_id": schedule_id,
                "message": f"Reminder scheduled for {when}",
            }

        elif action == "list":
            jobs = await service.list_jobs()
            return {
                "success": True,
                "task_count": len(jobs),
                "tasks": jobs,
            }

        elif action == "cancel":
            if not schedule_id:
                return {"success": False, "error": "Parameter 'schedule_id' is required for cancel"}

            result = await service.cancel(schedule_id)
            if result:
                return {
                    "success": True,
                    "message": f"Task {schedule_id} cancelled",
                }
            else:
                return {
                    "success": False,
                    "error": f"Task {schedule_id} not found",
                }

        else:
            return {
                "success": False,
                "error": f"Unknown action: {action}. Supported: create_once, list, cancel",
            }

    except Exception as e:
        logger.exception(f"Error in schedule_tool(action={action}): {e}")
        return {
            "success": False,
            "error": f"Internal error: {str(e)}",
        }
