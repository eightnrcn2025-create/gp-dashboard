#!/bin/bash
# =============================================================
# Gamepark 看板 — 本地启动脚本（macOS / Linux）
# 启动 api_server（port 5001）供历史查询备用，然后打开看板
# 注：刷新功能已改为 GitHub Actions，无需本地刷新服务
# =============================================================

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOGS_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOGS_DIR"
cd "$PROJECT_DIR"

echo "================================================"
echo "  Gamepark 看板"
echo "  项目路径: $PROJECT_DIR"
echo "================================================"
echo ""

if ! command -v python3 &>/dev/null; then
    echo "[ERROR] 未找到 python3"
    exit 1
fi

# ── 启动 api_server（port 5001，历史查询备用）────────────────
if lsof -Pi :5001 -sTCP:LISTEN -t &>/dev/null 2>&1; then
    echo "[INFO] API 服务已在运行（端口 5001）"
else
    echo "[INFO] 启动 API 服务 (port 5001)..."
    nohup python3 api_server.py > "$LOGS_DIR/api_server.log" 2>&1 &
    echo $! > "$LOGS_DIR/api_server.pid"
    sleep 1
    lsof -Pi :5001 -sTCP:LISTEN -t &>/dev/null 2>&1 \
        && echo "[OK]  API 服务已启动 → http://localhost:5001" \
        || echo "[WARN] API 服务启动失败，请检查: $LOGS_DIR/api_server.log"
fi

echo ""

# ── 打开看板页面 ──────────────────────────────────────────────
INDEX="$PROJECT_DIR/index.html"
if [ -f "$INDEX" ]; then
    command -v open    &>/dev/null && open    "$INDEX"
    command -v xdg-open &>/dev/null && xdg-open "$INDEX" 2>/dev/null
    echo "[OK]  已打开 index.html"
fi

echo ""
echo "================================================"
echo "  看板地址（GitHub Pages）："
echo "  https://eightnrcn2025-create.github.io/gp-dashboard/"
echo "  刷新功能配置说明：SETUP_REFRESH.md"
echo "================================================"
echo ""
