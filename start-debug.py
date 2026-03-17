"""
start-debug.py — 调试模式启动脚本

与 start.py 不同，Gateway 服务直接在当前进程中运行（非子进程），
VS Code 断点可在 Gateway 及其导入的所有后端代码中生效。

LangGraph Server 仍以子进程启动（langgraph dev 是 CLI 工具，无法嵌入线程），
如需调试 LangGraph 内的代码（如 setup_agent_tool），请使用 debugpy attach。

使用方式：
  1. 在 VS Code 中打开此文件，按 F5 选择 "Python: Current File" 运行
  2. 在 backend/ 下任意 .py 文件中设置断点（如 agents.py, feishu.py, manager.py）
  3. 通过飞书发消息触发流程，断点将命中 Gateway 路径下的代码

可调试的代码范围（Gateway 进程内）：
  - backend/app/channels/feishu.py          — 飞书消息收发
  - backend/app/channels/manager.py         — 线程管理 + Agent 调用
  - backend/app/gateway/routers/agents.py   — Agent CRUD API（含 SOUL.md 读写）
  - backend/packages/harness/deerflow/config/agents_config.py — load_agent_soul
  - backend/packages/harness/deerflow/config/paths.py         — 路径解析

不可调试的代码（LangGraph 子进程内）：
  - backend/packages/harness/deerflow/tools/builtins/setup_agent_tool.py — setup_agent 工具
  - backend/packages/harness/deerflow/agents/lead_agent/agent.py         — make_lead_agent
  - backend/packages/harness/deerflow/agents/lead_agent/prompt.py        — SOUL.md 注入 prompt
"""

import subprocess
import threading
import time
import signal
import sys
import os

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")


def run_langgraph():
    """启动 LangGraph Server（子进程，langgraph dev 是 CLI 工具无法嵌入）"""
    try:
        subprocess.run(
            "uv run langgraph dev --no-browser --allow-blocking --port 2024",
            cwd=BACKEND_DIR,
            shell=True,
        )
    except Exception as e:
        print(f"❌ LangGraph Server 异常: {e}")


def run_gateway():
    """启动 API Gateway + Channels — 直接在当前进程运行，断点生效"""
    try:
        import uvicorn

        uvicorn.run(
            "app.gateway.app:app",
            host="0.0.0.0",
            port=8001,
        )
    except Exception as e:
        print(f"❌ Gateway 异常: {e}")


def main():
    print("🚀 正在启动后端服务 (Debug Mode)...")

    # 1) 守护线程中启动 LangGraph Server（子进程）
    langgraph_thread = threading.Thread(target=run_langgraph, name="LangGraph", daemon=True)
    langgraph_thread.start()
    print("👉 LangGraph Server 启动中... (子进程, http://localhost:2024)")

    # 等待 LangGraph 初始化
    time.sleep(2)

    # 2) 设置环境，使 Gateway 代码可以正确导入
    sys.path.insert(0, BACKEND_DIR)
    os.environ["PYTHONPATH"] = "."
    os.chdir(BACKEND_DIR)  # 让 Paths 类的 cwd 检测正常工作

    print("👉 API Gateway 启动中... (当前进程, http://localhost:8001)")
    print("\n✅ 后端服务已启动 (Debug Mode)！")
    print("   - LangGraph: http://localhost:2024 (子进程，断点不生效)")
    print("   - Gateway:   http://localhost:8001 (当前进程，断点生效 ✅)")
    print("   (按 Ctrl+C 停止)")

    # 3) 主线程直接运行 Gateway — 断点在此进程内全部生效
    run_gateway()


if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda *_: (print("\n🛑 正在停止服务..."), sys.exit(0)))
    main()
