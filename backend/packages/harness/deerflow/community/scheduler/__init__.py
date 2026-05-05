"""Scheduler community module for DeerFlow.

Provides time-based task scheduling with IM channel integration.
Phase 1: One-time reminders delivered to Feishu/Slack.
"""

from .executor import SchedulerExecutor
from .job_model import SchedulePayload
from .service import (
    SchedulerService,
    get_scheduler_service,
    start_scheduler_service,
    start_scheduler_service_with_tool_config,
    stop_scheduler_service,
    stop_scheduler_service_with_timeout,
)
from .tools import schedule_tool

__all__ = [
    "SchedulerExecutor",
    "SchedulePayload",
    "SchedulerService",
    "get_scheduler_service",
    "start_scheduler_service_with_tool_config",
    "stop_scheduler_service_with_timeout",
    "start_scheduler_service",
    "stop_scheduler_service",
    "schedule_tool",
]
