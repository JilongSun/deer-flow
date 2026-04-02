"""Middleware to rewrite virtual paths to actual paths for MCP tool calls."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, override

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from deerflow.agents.thread_state import ThreadState
from deerflow.config.paths import get_paths

logger = logging.getLogger(__name__)


class McpPathRewriteMiddleware(AgentMiddleware[ThreadState]):
    """Rewrite virtual paths to actual paths in MCP tool args.

    Scans all tool arguments recursively and converts values starting waith
    /mnt/user-data (or mnt/user-data) to actual filesystem paths.
    """

    state_schema = ThreadState

    def __init__(self, mcp_tool_prefixes: list[str] | None = None):
        """Initialize middleware.

        Args:
            mcp_tool_prefixes: Tool name prefixes to target (e.g., ["videoflow-mcp"]).
        """
        self._prefixes = tuple(mcp_tool_prefixes or [])

    def _is_target_mcp_tool(self, tool_name: str) -> bool:
        """Check if tool is an MCP tool to process."""
        if not self._prefixes:
            return False
        return tool_name.startswith(self._prefixes)

    def _rewrite_path(self, path: str, thread_id: str) -> str:
        """Convert virtual path to actual path."""
        normalized_path = path
        if path.startswith("mnt/user-data"):
            normalized_path = f"/{path}"

        if not normalized_path.startswith("/mnt/user-data"):
            return path
        try:
            rpath = str(get_paths().resolve_virtual_path(thread_id, normalized_path))
            logger.info(f"[McpPathRewrite] Rewrote {path} to {rpath}")
            return rpath
        except Exception as e:
            logger.warning(f"Failed to resolve path {path}: {e}")
            return path

    def _rewrite_virtual_paths(self, obj: Any, thread_id: str) -> Any:
        """Recursively rewrite all virtual path values in args."""
        if isinstance(obj, str):
            return self._rewrite_path(obj, thread_id)
        if isinstance(obj, list):
            return [self._rewrite_virtual_paths(v, thread_id) for v in obj]
        if isinstance(obj, tuple):
            return tuple(self._rewrite_virtual_paths(v, thread_id) for v in obj)
        if isinstance(obj, dict):
            return {k: self._rewrite_virtual_paths(v, thread_id) for k, v in obj.items()}
        return obj

    def _rewrite_args_if_needed(self, request: ToolCallRequest) -> None:
        """Rewrite virtual paths in tool arguments."""
        tool_name = str(request.tool_call.get("name") or "")
        if not self._is_target_mcp_tool(tool_name):
            return

        runtime = request.runtime
        ctx = getattr(runtime, "context", {}) or {}
        thread_id = ctx.get("thread_id")
        if not thread_id:
            return

        args = request.tool_call.get("args")
        if isinstance(args, dict):
            request.tool_call["args"] = self._rewrite_virtual_paths(args, thread_id)
            logger.info(f"[McpPathRewrite] Rewrote virtual paths for {tool_name}")

    @override
    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        self._rewrite_args_if_needed(request)
        return handler(request)

    @override
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        self._rewrite_args_if_needed(request)
        return await handler(request)
