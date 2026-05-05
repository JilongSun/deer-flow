# DeerFlow Scheduler Module

Task scheduling engine for DeerFlow, built on APScheduler 3.x.

## Overview

The scheduler allows users to create timed tasks that execute at specified times. Tasks are routed through IM channels (Feishu, Slack, etc.) and currently support reminder delivery.

### Current Capabilities

- **Task Type**: `once` — one-time execution at a specified time
- **Action Type**: `remind` — direct message send (no agent invocation)
- **Storage Backend**:
  - `memory` → in-memory (no persistence, development only)
  - `sqlite` → shared `deerflow.db` file (single-node production)
  - `postgres` → not supported yet for scheduler job storage

### Architecture

```text
SchedulerService (this module)
├── start()          — initialize APScheduler, restore jobs from storage
├── stop()           — graceful shutdown
├── create_once()    — create a one-time reminder task
├── list_jobs()      — list active scheduled tasks
├── cancel()         — cancel a task by schedule_id
└── _job_executor()  — internal: triggered callback, publishes OutboundMessage to bus
```

The scheduler is **decoupled** from IM channels:

- No direct IM SDK dependencies (no Feishu, Slack imports)
- Tasks are stored as `SchedulePayload` dataclass, serialized to dict for JobStore
- At trigger time, scheduler publishes `OutboundMessage` directly to MessageBus
- ChannelManager and Channel implementation handle delivery to the user

## Configuration

Enable the schedule tool in `config.yaml`:

```yaml
tools:
  - name: schedule
    group: web
    use: deerflow.community.scheduler.tools:schedule_tool
    enabled: true
    timezone: Asia/Shanghai
    misfire_grace_time: 60
    coalesce: true
    max_instances: 1
```

The scheduler automatically selects its JobStore backend from `database.backend`:

- `database.backend: memory` → `MemoryJobStore`
- `database.backend: sqlite` → `SQLAlchemyJobStore` sharing `deerflow.db`
- `database.backend: postgres` → not supported yet

## Usage (LLM/Tool)

Users interact with the scheduler via the `schedule` tool:

```text
User: "Remind me in 5 minutes to check my email"

LLM → calls schedule_tool with:
  {
    "action": "create_once",
    "when": "2026-05-05T14:35:00+08:00",  # ISO 8601 with timezone
    "content": "Check your email"
  }

Tool → calls SchedulerService.create_once()
      → creates job, returns schedule_id for tracking

At 2026-05-05 14:35 UTC+8:
  APScheduler triggers _job_executor()
  → constructs OutboundMessage
  → publishes to MessageBus
  → ChannelManager delivers via Feishu/etc
```

## Limitations & Warnings

### ⚠️ IM-Only

Scheduled task delivery requires an **active IM channel**. If no channel is running:

- Jobs still trigger on time (execute internally)
- But `OutboundMessage` has nowhere to go
- Message is logged but not delivered

**Solution**: Ensure at least one IM channel (e.g. Feishu) is configured and `enabled: true` before creating tasks.

### ⚠️ Single-Instance Only

APScheduler 3.x with SQLite uses file-based locking. In multi-instance deployments:

- Each Gateway process independently triggers the same jobs
- Users receive **duplicate messages**

**Mitigation**: Run a single Gateway instance when using scheduler + sqlite.

### ⚠️ Timezone Handling

- **Storage**: All times stored as UTC in the database
- **Input**: User provides times in local timezone (tool parameter)
- **Display**: Converted back to user's timezone when listing jobs
- **Execution**: APScheduler triggers at UTC time; outbound message carries original timezone for logging

## Testing

```bash
# Unit tests (in backend/tests/)
pytest tests/test_scheduler_service.py
pytest tests/test_scheduler_tools.py

# Integration test (manual)
# 1. Enable tools.schedule + feishu channel in config.yaml
# 2. Start DeerFlow (make dev)
# 3. Send to Feishu: "remind me in 1 minute"
# 4. Wait for reminder delivery
```

## Roadmap

- `recurring` support (daily/weekly)
- `execute` action (agent-driven task execution)
- Enhanced logging and scheduler query APIs
- PostgreSQL job store support for multi-instance deployments

## Implementation Details

See [SCHEDULER_DESIGN_NOTES.md](../../.github/SCHEDULER_DESIGN_NOTES.md) for the complete architecture.
