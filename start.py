import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import TextIO


REPO_ROOT = Path(__file__).resolve().parent
BACKEND_DIR = REPO_ROOT / "backend"
LOG_DIR = REPO_ROOT / "logs"
CONFIG_FILE = REPO_ROOT / "config.yaml"


def _read_config_log_level() -> str:
    if not CONFIG_FILE.is_file():
        return "info"

    try:
        for line in CONFIG_FILE.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("log_level:"):
                value = stripped.split(":", 1)[1].strip()
                if value:
                    return value
    except OSError:
        pass

    return "info"


def _build_langgraph_args() -> list[str]:
    log_level = os.getenv("LANGGRAPH_LOG_LEVEL", _read_config_log_level())
    jobs_per_worker = os.getenv("LANGGRAPH_JOBS_PER_WORKER", "10")
    allow_blocking = os.getenv("LANGGRAPH_ALLOW_BLOCKING", "1") == "1"

    args = [
        "uv",
        "run",
        "langgraph",
        "dev",
        "--no-browser",
        "--no-reload",
        "--n-jobs-per-worker",
        jobs_per_worker,
        "--server-log-level",
        log_level,
        "--port",
        "2024",
    ]
    if allow_blocking:
        args.insert(5, "--allow-blocking")
    return args


SERVICES = [
    {
        "name": "LangGraph Server",
        "cwd": BACKEND_DIR,
        "env": {**os.environ, "NO_COLOR": "1"},
        "args": _build_langgraph_args(),
        "log_path": LOG_DIR / "langgraph.log",
    },
    {
        "name": "API Gateway + Channels",
        "cwd": BACKEND_DIR,
        "env": {**os.environ, "PYTHONPATH": "."},
        "args": [
            "uv",
            "run",
            "uvicorn",
            "app.gateway.app:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8001",
        ],
        "log_path": LOG_DIR / "gateway.log",
    },
]


processes: list[subprocess.Popen] = []
log_handles: list[TextIO] = []


def start_services() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    print("🚀 正在启动后端服务 (Production Mode)...")
    for service in SERVICES:
        print(f"👉 启动 {service['name']}...")
        log_handle = open(service["log_path"], "a", encoding="utf-8")
        process = subprocess.Popen(
            service["args"],
            cwd=service["cwd"],
            env=service["env"],
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            shell=False,
        )
        log_handles.append(log_handle)
        processes.append(process)


def stop_services(signum, frame) -> None:
    print("\n🛑 正在停止服务...")
    for process in processes:
        process.terminate()
    for log_handle in log_handles:
        try:
            log_handle.close()
        except OSError:
            pass
    print("✅ 服务已停止")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, stop_services)

    start_services()

    print("\n✅ 后端服务已启动 (Production Mode)！")
    print("   - LangGraph: http://localhost:2024 (no-reload)")
    print("   - Gateway:   http://localhost:8001 (承载飞书 WebSocket, no-reload)")
    print("   - Logs:      ./logs/langgraph.log, ./logs/gateway.log")
    print("   (按 Ctrl+C 停止)")

    while True:
        time.sleep(1)