"""Scheduler service lifecycle and job management."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.channels.message_bus import MessageBus
from deerflow.config.database_config import DatabaseConfig

from .executor import SchedulerExecutor
from .job_model import SchedulePayload

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SchedulerToolConfig:
    """Scheduler runtime config sourced from tools.schedule model_extra."""

    enabled: bool = True
    timezone: str = "UTC"
    misfire_grace_time: int = 60
    coalesce: bool = True
    max_instances: int = 1
    enabled_actions: tuple[str, ...] = ("remind",)


def _scheduler_tool_config_from_dict(extra: dict[str, Any] | None) -> SchedulerToolConfig:
    """Build validated runtime config from tool model_extra dictionary."""
    extra = extra or {}
    enabled = extra.get("enabled", True)
    timezone = extra.get("timezone", "UTC")
    misfire_grace_time = extra.get("misfire_grace_time", 60)
    coalesce = extra.get("coalesce", True)
    max_instances = extra.get("max_instances", 1)
    raw_enabled_actions = extra.get("enabled_actions", ["remind"])

    enabled_actions: tuple[str, ...]
    if isinstance(raw_enabled_actions, str):
        enabled_actions = (raw_enabled_actions,)
    elif isinstance(raw_enabled_actions, list | tuple | set):
        normalized = [str(action).strip() for action in raw_enabled_actions if str(action).strip()]
        enabled_actions = tuple(normalized) if normalized else ("remind",)
    else:
        enabled_actions = ("remind",)

    return SchedulerToolConfig(
        enabled=bool(enabled),
        timezone=str(timezone),
        misfire_grace_time=int(misfire_grace_time),
        coalesce=bool(coalesce),
        max_instances=int(max_instances),
        enabled_actions=enabled_actions,
    )


class SchedulerService:
    """Manages APScheduler lifecycle and job operations.
    
    Decoupled from IM channels: only uses MessageBus to publish outbound messages.
    JobStore backend automatically derived from database.backend config.
    """

    def __init__(
        self,
        message_bus: MessageBus,
        database_config: DatabaseConfig,
        tool_config: dict[str, Any] | None = None,
    ):
        """Initialize scheduler (does not start yet).
        
        Args:
            message_bus: MessageBus for publishing OutboundMessage to channels.
            database_config: DatabaseConfig to derive JobStore backend.
        """
        self.database_config = database_config
        self.runtime_config = _scheduler_tool_config_from_dict(tool_config)
        self.executor = SchedulerExecutor(message_bus)
        self._configure_executor_actions()
        self.scheduler: AsyncIOScheduler | None = None
        self._running = False

    def _configure_executor_actions(self) -> None:
        """Apply tool-config action allowlist to executor handlers."""
        enabled_actions = set(self.runtime_config.enabled_actions)
        for action in list(self.executor.list_actions()):
            if action not in enabled_actions:
                self.executor.unregister_handler(action)

        for action in enabled_actions:
            if not self.executor.has_handler(action):
                logger.warning(
                    "No handler registered for enabled scheduler action '%s'; it will be ignored",
                    action,
                )

    async def start(self) -> None:
        """Start the scheduler and restore jobs from persistent storage."""
        if self._running:
            logger.warning("Scheduler already running")
            return

        config = self.runtime_config
        if not config.enabled:
            logger.info("Scheduler disabled in tools.schedule config, skipping startup")
            return

        logger.info("Starting SchedulerService")

        # Build jobstore from database backend
        jobstore = self._create_jobstore()

        # Configure scheduler with AsyncIOExecutor for async job support
        self.scheduler = AsyncIOScheduler(
            jobstores={"default": jobstore},
            executors={"default": AsyncIOExecutor()},
            job_defaults={
                "coalesce": config.coalesce,
                "max_instances": config.max_instances,
                "misfire_grace_time": config.misfire_grace_time,
            },
            timezone=config.timezone,
        )

        # Start scheduler
        self.scheduler.start()
        self._running = True

        # Log restored jobs count
        jobs_count = len(self.scheduler.get_jobs())
        logger.info(f"SchedulerService started with {jobs_count} restored job(s)")

    async def stop(self) -> None:
        """Stop the scheduler gracefully."""
        if not self._running or self.scheduler is None:
            return

        logger.info("Stopping SchedulerService")
        self.scheduler.shutdown(wait=True)
        self._running = False
        self.scheduler = None
        logger.info("SchedulerService stopped")

    def _create_jobstore(self) -> MemoryJobStore | SQLAlchemyJobStore:
        """Create appropriate JobStore based on database backend.
        
        Returns:
            MemoryJobStore for backend='memory'
            SQLAlchemyJobStore for backend='sqlite' (auto-creates apscheduler_jobs table)
            SQLAlchemyJobStore for backend='postgres' (future)
        
        Raises:
            ValueError if unsupported backend.
        """
        backend = self.database_config.backend

        if backend == "memory":
            logger.info("Using in-memory job store (no persistence)")
            return MemoryJobStore()

        if backend == "sqlite":
            # Use synchronous SQLite URL (SQLAlchemyJobStore does not support async)
            sqlite_url = f"sqlite:///{self.database_config.sqlite_path}"
            logger.info(f"Using SQLAlchemy job store with SQLite: {sqlite_url}")
            return SQLAlchemyJobStore(url=sqlite_url)

        if backend == "postgres":
            raise NotImplementedError(
                "Scheduler does not yet support PostgreSQL backend. "
                "Use database.backend: sqlite for now."
            )

        raise ValueError(f"Unknown database backend: {backend}")

    async def create_once(
        self,
        channel_name: str,
        chat_id: str,
        user_id: str,
        content: str,
        run_at: str,  # ISO 8601 string with timezone info
        timezone: str | None = None,
        topic_id: str | None = None,
        thread_ts: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        """Create a one-time reminder task.
        
        Args:
            channel_name: Target IM channel (e.g. 'feishu', 'slack').
            chat_id: Channel-specific conversation ID.
            user_id: User who requested the task.
            content: Reminder text to send.
            run_at: ISO 8601 datetime with timezone (e.g. '2026-05-05T14:35:00+08:00').
            timezone: IANA timezone name (optional, defaults from config or extracted from run_at).
            topic_id: Optional topic/channel ID.
            thread_ts: Optional platform thread timestamp.
            thread_id: Optional DeerFlow thread ID.
            
        Returns:
            schedule_id: Unique identifier for this task.
            
        Raises:
            ValueError: If scheduler not running or parameters invalid.
        """
        if not self._running or self.scheduler is None:
            raise ValueError("Scheduler not running; cannot create task")

        # Parse run_at and extract timezone if not provided
        try:
            dt = datetime.fromisoformat(run_at)
            if dt.tzinfo is None:
                raise ValueError(f"run_at must include timezone: {run_at}")

            tz_name = timezone
            if not tz_name:
                inferred_tz = dt.tzinfo.tzname(dt) if hasattr(dt.tzinfo, "tzname") else None
                tz_name = inferred_tz if isinstance(inferred_tz, str) and inferred_tz else "UTC"
        except ValueError as e:
            raise ValueError(f"Invalid run_at format (expected ISO 8601 with tz): {run_at}") from e

        # Generate unique schedule_id
        schedule_id = uuid.uuid4().hex

        # Build payload
        payload = SchedulePayload(
            schedule_id=schedule_id,
            mode="once",
            action_type="remind",
            channel_name=channel_name,
            chat_id=chat_id,
            user_id=user_id,
            content=content,
            run_at=run_at,
            timezone=tz_name,
            topic_id=topic_id,
            thread_ts=thread_ts,
            thread_id=thread_id,
        )

        # Add job to scheduler (convert to UTC for APScheduler)
        self.scheduler.add_job(
            # Use a module-level function path so persisted jobs remain picklable.
            func="deerflow.community.scheduler.service:run_scheduler_job",
            trigger="date",
            run_date=dt,
            args=[payload.to_dict()],
            id=schedule_id,
            replace_existing=False,
        )

        logger.info(
            f"Created one-time reminder: schedule_id={schedule_id}, "
            f"channel={channel_name}, run_at={run_at}"
        )

        return schedule_id

    async def list_jobs(self) -> list[dict[str, Any]]:
        """List all active scheduled tasks.
        
        Returns:
            List of dicts with schedule_id, next_run_time, and payload summary.
        """
        if not self._running or self.scheduler is None:
            return []

        jobs = self.scheduler.get_jobs()
        result = []

        for job in jobs:
            payload_dict = job.args[0] if job.args else {}
            result.append(
                {
                    "schedule_id": job.id,
                    "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
                    "channel": payload_dict.get("channel_name"),
                    "content_preview": payload_dict.get("content", "")[:50],
                }
            )

        return result

    async def cancel(self, schedule_id: str) -> bool:
        """Cancel a scheduled task by ID.
        
        Args:
            schedule_id: The task to cancel.
            
        Returns:
            True if task was found and removed, False otherwise.
        """
        if not self._running or self.scheduler is None:
            return False

        try:
            self.scheduler.remove_job(schedule_id)
            logger.info(f"Cancelled task: schedule_id={schedule_id}")
            return True
        except Exception as e:
            logger.warning(f"Failed to cancel task {schedule_id}: {e}")
            return False

    async def _job_executor(self, payload: SchedulePayload) -> None:
        """Execute a reminder task: publish OutboundMessage to bus.
        
        This is the callback invoked by APScheduler when a job is triggered.
        Only 'remind' action is supported (direct outbound, no agent).
        
        Args:
            payload: SchedulePayload deserialized from job storage.
        """
        await self.executor.execute(payload)


# Singleton access (for Gateway lifespan integration)
_scheduler_service: SchedulerService | None = None


async def get_scheduler_service() -> SchedulerService | None:
    """Get the singleton SchedulerService instance (if started)."""
    return _scheduler_service


async def start_scheduler_service(
    message_bus: MessageBus,
    database_config: DatabaseConfig,
    tool_config: dict[str, Any] | None = None,
) -> SchedulerService:
    """Create and start the global SchedulerService from configs."""
    global _scheduler_service
    if _scheduler_service is not None:
        logger.warning("SchedulerService already started, returning existing instance")
        return _scheduler_service
    _scheduler_service = SchedulerService(message_bus, database_config, tool_config)
    await _scheduler_service.start()
    return _scheduler_service


async def start_scheduler_service_with_tool_config(app_config: Any) -> SchedulerService | None:
    """Start scheduler when `tools.schedule` exists and is enabled.

    Returns:
        SchedulerService instance when started, otherwise None.
    """
    schedule_tool_config = app_config.get_tool_config("schedule")
    if schedule_tool_config is None:
        return None

    tool_extra = schedule_tool_config.model_extra or {}
    if not bool(tool_extra.get("enabled", True)):
        return None

    from app.channels.service import get_channel_service

    channel_service = get_channel_service()
    if channel_service is None:
        logger.info("Channel service not running; skipping scheduler startup")
        return None

    try:
        service = await start_scheduler_service(
            channel_service.bus,
            app_config.database,
            tool_extra,
        )
        logger.info("Scheduler service started")
        return service
    except Exception:
        logger.exception("Failed to start scheduler service")
        return None


async def stop_scheduler_service() -> None:
    """Stop the global SchedulerService."""
    global _scheduler_service
    if _scheduler_service is not None:
        await _scheduler_service.stop()
        _scheduler_service = None


async def stop_scheduler_service_with_timeout(timeout_seconds: float) -> None:
    """Stop scheduler when running; swallow errors and keep shutdown flow alive."""
    if _scheduler_service is None:
        return

    try:
        await asyncio.wait_for(stop_scheduler_service(), timeout=timeout_seconds)
    except TimeoutError:
        logger.warning(
            "Scheduler service shutdown exceeded %.1fs; proceeding with channel shutdown.",
            timeout_seconds,
        )
    except Exception:
        logger.exception("Failed to stop scheduler service")


async def run_scheduler_job(payload_data: dict[str, Any]) -> None:
    """Module-level APScheduler entrypoint for persisted jobs.

    SQLAlchemyJobStore pickles callable references; bound instance methods are
    not reliable across process restarts. This function is importable by path
    and receives only serializable data.
    """
    service = await get_scheduler_service()
    if service is None:
        logger.warning("Scheduler service not running while executing persisted job")
        return

    payload = SchedulePayload.from_dict(payload_data)
    await service._job_executor(payload)
