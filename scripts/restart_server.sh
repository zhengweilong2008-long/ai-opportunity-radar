#!/bin/bash
# 重启本地开发服务器（避免 pkill 自匹配：模式写在文件里）
pkill -f "uvicorn app.main:app"
sleep 1
cd "$(dirname "$0")/.." || exit 1
nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/radar_server.log 2>&1 &
sleep 4
curl -s -o /dev/null -w "server HTTP %{http_code}\n" http://127.0.0.1:8000/healthz
