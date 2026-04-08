#!/bin/bash
# =============================================================
# Gamepark 看板 — 一键启动（macOS / Linux）
# 使用 nohup 持久启动 refresh_server + api_server，再打开看板
# =============================================================

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOGS_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOGS_DIR"
cd "$PROJECT_DIR"

echo "================================================"
echo "  Gamepark 看板 - 一键启动"
echo "  项目路径: $PROJECT_DIR"
echo "================================================"
echo ""

# ── 检查 Python ───────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] 未找到 python3，请先安装 Python 3"
    exit 1
fi

# ── 启动 refresh_server（port 5002）──────────────────────────
if lsof -Pi :5002 -sTCP:LISTEN -t &>/dev/null 2>&1; then
    echo "[INFO] 刷新服务已在运行（端口 5002）"
else
    echo "[INFO] 启动刷新服务 (port 5002)..."
    nohup python3 refresh_server.py > "$LOGS_DIR/refresh_server.log" 2>&1 &
    echo $! > "$LOGS_DIR/refresh_server.pid"
    sleep 2
    if lsof -Pi :5002 -sTCP:LISTEN -t &>/dev/null 2>&1; then
        echo "[OK]  刷新服务已启动 → http://localhost:5002  (PID=$(cat "$LOGS_DIR/refresh_server.pid"))"
    else
        echo "[WARN] 刷新服务启动失败，请检查: $LOGS_DIR/refresh_server.log"
    fi
fi

# ── 启动 api_server（port 5001）──────────────────────────────
if lsof -Pi :5001 -sTCP:LISTEN -t &>/dev/null 2>&1; then
    echo "[INFO] API 服务已在运行（端口 5001）"
else
    echo "[INFO] 启动 API 服务 (port 5001)..."
    nohup python3 api_server.py > "$LOGS_DIR/api_server.log" 2>&1 &
    echo $! > "$LOGS_DIR/api_server.pid"
    sleep 1
    if lsof -Pi :5001 -sTCP:LISTEN -t &>/dev/null 2>&1; then
        echo "[OK]  API 服务已启动 → http://localhost:5001  (PID=$(cat "$LOGS_DIR/api_server.pid"))"
    else
        echo "[WARN] API 服务启动失败，请检查: $LOGS_DIR/api_server.log"
    fi
fi

echo ""

# ── 打开看板页面 ──────────────────────────────────────────────
INDEX="$PROJECT_DIR/index.html"
if [ -f "$INDEX" ]; then
    echo "[INFO] 打开看板页面..."
    if command -v open &>/dev/null; then
        open "$INDEX"
    elif command -v xdg-open &>/dev/null; then
        xdg-open "$INDEX"
    fi
    echo "[OK]  index.html 已在浏览器中打开"
fi

echo ""
echo "================================================"
echo "  刷新服务: http://localhost:5002/ping"
echo "  API 服务:  http://localhost:5001/api/status"
echo "  服务日志:  $LOGS_DIR/"
echo "================================================"
echo ""
