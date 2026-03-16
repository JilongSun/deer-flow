import subprocess
import time
import signal
import sys
import os
from pathlib import Path

# 定义后端服务命令 (Windows下使用 shell=True)
SERVICES = [
    {
        "name": "LangGraph Server",
        "cwd": "backend",
        "command": "uv run langgraph dev --no-browser --allow-blocking --port 2024",
    },
    {
        "name": "API Gateway + Channels",
        "cwd": "backend",
        # 设置 PYTHONPATH=. 确保 backend 目录被加入 Python 路径
        "env": {**os.environ, "PYTHONPATH": "."},
        "command": "uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001",
    }
]

processes = []

def start_services():
    print("🚀 正在启动后端服务 (Feishu Mode)...")
    for service in SERVICES:
        print(f"👉 启动 {service['name']}...")
        p = subprocess.Popen(
            service["command"],
            cwd=service["cwd"],
            env=service.get("env"),
            shell=True # Windows 需要
        )
        processes.append(p)

def stop_services(signum, frame):
    print("\n🛑 正在停止服务...")
    for p in processes:
        p.terminate()
    print("✅ 服务已停止")
    sys.exit(0)

if __name__ == "__main__":
    # 注册 Ctrl+C 处理
    signal.signal(signal.SIGINT, stop_services)
    
    start_services()
    
    print("\n✅ 后端服务已启动！")
    print("   - LangGraph: http://localhost:2024")
    print("   - Gateway:   http://localhost:8001 (承载飞书 WebSocket)")
    print("   (按 Ctrl+C 停止)")
    
    # 保持主进程运行
    while True:
        time.sleep(1)