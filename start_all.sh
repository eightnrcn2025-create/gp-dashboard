#!/bin/bash
# =============================================================
# Gamepark 看板 — 一键启动（macOS / Linux）
# 启动 refresh_server（port 5002）+ api_server（port 5001）
# =============================================================

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOGS_DIR="$PROJECT_DIR/logs"
REFRESH_LOG="$LOGS_DIR/refresh_server.log"
API_LOG="$LOGS_DIR/api_server.log"
REFRESH_PID="$LOGS_DIR/refresh_server.pid"
API_PID_FILE="$LOGS_DIR/api_server.pid"

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

# ── 停止旧进程 ─────────────────────────────────────────────────
for PF in "$REFRESH_PID" "$API_PID_FILE"; do
    if [ -f "$PF" ]; then
        OLD=$(cat "$PF")
        kill "$OLD" 2>/dev/null && echo "[INFO] 已停止旧进程 PID=$OLD"
        rm -f "$PF"
        sleep 0.5
    fi
done

# ── 启动 refresh_server（port 5002）──────────────────────────
if lsof -i :5002 -t &>/dev/null 2>&1; then
    echo "[WARN] 端口 5002 已被占用，跳过启动刷新服务"
else
    echo "[INFO] 启动刷新服务 (port 5002)..."
    python3 refresh_server.py >> "$REFRESH_LOG" 2>&1 &
    RPID=$!
    echo $RPID > "$REFRESH_PID"
    sleep 2
    if kill -0 "$RPID" 2>/dev/null; then
        echo "[OK]  刷新服务已启动 → http://localhost:5002  (PID=$RPID)"
    else
        echo "[WARN] 刷新服务启动失败，请检查: $REFRESH_LOG"
    fi
fi

# ── 启动 api_server（port 5001，历史查询备用）────────────────
if lsof -i :5001 -t &>/dev/null 2>&1; then
    echo "[WARN] 端口 5001 已被占用，跳过启动 API 服务"
else
    echo "[INFO] 启动 API 服务 (port 5001)..."
    python3 api_server.py >> "$API_LOG" 2>&1 &
    APID=$!
    echo $APID > "$API_PID_FILE"
    sleep 1
    if kill -0 "$APID" 2>/dev/null; then
        echo "[OK]  API 服务已启动 → http://localhost:5001  (PID=$APID)"
    else
        echo "[WARN] API 服务启动失败，请检查: $API_LOG"
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
echo "  停止全部:  kill \$(cat $REFRESH_PID) \$(cat $API_PID_FILE)"
echo "================================================"
echo ""
