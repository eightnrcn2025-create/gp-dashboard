#!/bin/bash
# =============================================================
# Gamepark 看板 - 立即执行数据更新（macOS / Linux）
# =============================================================

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "================================================"
echo "  Gamepark 看板 - 立即执行数据更新"
echo "================================================"
echo ""

# 切换到项目目录
cd "$PROJECT_DIR" || { echo "[ERROR] 无法进入目录: $PROJECT_DIR"; exit 1; }

# 检查 Python
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] 未找到 python3，请先安装 Python 3"
    exit 1
fi

# 检查脚本
if [ ! -f "update_data.py" ]; then
    echo "[ERROR] 未找到 update_data.py"
    exit 1
fi

echo "[INFO] 开始时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "[INFO] 项目路径: $PROJECT_DIR"
echo ""
echo "------------------------------------------------"

python3 update_data.py
EXIT_CODE=$?

echo "------------------------------------------------"
echo ""

if [ $EXIT_CODE -ne 0 ]; then
    echo "[ERROR] 更新执行过程中出现错误，请查看日志："
    echo "        $PROJECT_DIR/logs/update_log.txt"
else
    echo "[OK] 更新完成"
    echo "[OK] 结束时间: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "[OK] 数据文件: $PROJECT_DIR/data/data.json"
fi

echo ""

# =============================================================
# crontab 定时任务配置说明（每天 08:00 自动执行）
# 执行以下命令添加定时任务：
#
#   crontab -e
#
# 然后在编辑器中添加以下一行：
#
#   0 8 * * * cd ~/Desktop/gp活动看板 && python3 update_data.py >> ~/Desktop/gp活动看板/logs/update_log.txt 2>&1
#
# 保存退出后，通过以下命令确认任务已添加：
#   crontab -l
# =============================================================
