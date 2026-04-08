#!/bin/bash
# =============================================================
# Gamepark 看板 — 一键启动（macOS / Linux）
# 启动 API 服务 + 打开看板页面
# =============================================================

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
API_LOG="$PROJECT_DIR/logs/api_server.log"
PID_FILE="$PROJECT_DIR/logs/api_server.pid"

mkdir -p "$PROJECT_DIR/logs"

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

# ── 停止旧的 API 进程 ─────────────────────────────────────────
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "[INFO] 停止旧的 API 进程 (PID=$OLD_PID)..."
        kill "$OLD_PID" 2>/dev/null
        sleep 1
    fi
    rm -f "$PID_FILE"
fi

# ── 检查端口 5001 是否已被占用 ────────────────────────────────
if lsof -i :5001 -t &>/dev/null 2>&1; then
    echo "[WARN] 端口 5001 已被占用，跳过启动 API 服务"
else
    # 启动 API 服务（后台）
    echo "[INFO] 启动 API 服务 (port 5001)..."
    cd "$PROJECT_DIR"
    python3 api_server.py >> "$API_LOG" 2>&1 &
    API_PID=$!
    echo $API_PID > "$PID_FILE"
    sleep 2

    # 检查是否启动成功
    if kill -0 "$API_PID" 2>/dev/null; then
        echo "[OK]  API 服务已启动 → http://localhost:5001  (PID=$API_PID)"
    else
        echo "[WARN] API 服务启动失败，请检查日志: $API_LOG"
    fi
fi

echo ""

# ── 打开看板页面 ──────────────────────────────────────────────
INDEX="$PROJECT_DIR/index.html"
if [ -f "$INDEX" ]; then
    echo "[INFO] 打开看板页面..."
    if command -v open &>/dev/null; then
        open "$INDEX"          # macOS
    elif command -v xdg-open &>/dev/null; then
        xdg-open "$INDEX"     # Linux
    fi
    echo "[OK]  index.html 已在浏览器中打开"
else
    echo "[WARN] 未找到 index.html: $INDEX"
fi

echo ""
echo "================================================"
echo "  API 服务: http://localhost:5001/api/status"
echo "  停止服务: kill \$(cat $PID_FILE)"
echo "================================================"
echo ""
echo "如需立即抓取数据，运行："
echo "  python3 $PROJECT_DIR/update_data.py"
echo ""
