# =============================================================================
# Gamepark 看板 — 轻量刷新服务（Flask, port 5002）
# =============================================================================
# 仅提供两个接口：
#   GET  /ping    — 存活检测
#   POST /refresh — 后台启动 update_data.py
#   GET  /status  — 查询是否正在运行
# =============================================================================

import os
import subprocess
import threading
from pathlib import Path

from flask import Flask, jsonify
from flask_cors import CORS

app      = Flask(__name__)
CORS(app)

SCRIPT_DIR = Path(__file__).parent.resolve()
is_running = False
last_result = {"returncode": None, "message": ""}


@app.route("/ping")
def ping():
    return jsonify({"alive": True})


@app.route("/status")
def status():
    return jsonify({"is_running": is_running, "last": last_result})


@app.route("/refresh", methods=["GET", "POST"])
def refresh():
    global is_running
    if is_running:
        return jsonify({"status": "running", "message": "数据更新中，请稍候..."})

    def run_update():
        global is_running, last_result
        is_running = True
        try:
            proc = subprocess.run(
                ["python3", "update_data.py"],
                cwd=str(SCRIPT_DIR),
                capture_output=True,
                text=True,
                timeout=180,
            )
            tail = (proc.stdout or "")[-800:]
            if proc.returncode == 0:
                last_result = {"returncode": 0, "message": tail}
                print("[refresh_server] 更新完成")
            else:
                err = (proc.stderr or "")[-400:]
                last_result = {"returncode": proc.returncode, "message": err}
                print(f"[refresh_server] 更新失败 (code={proc.returncode}):\n{err}")
        except subprocess.TimeoutExpired:
            last_result = {"returncode": -1, "message": "执行超时（>180s）"}
            print("[refresh_server] update_data.py 超时")
        except Exception as e:
            last_result = {"returncode": -1, "message": str(e)}
            print(f"[refresh_server] 异常: {e}")
        finally:
            is_running = False

    t = threading.Thread(target=run_update, daemon=True)
    t.start()
    return jsonify({"status": "started", "message": "数据更新已启动，约需 30-90 秒"})


if __name__ == "__main__":
    print("=" * 50)
    print("  Gamepark 刷新服务")
    print("  http://localhost:5002/ping")
    print("  POST http://localhost:5002/refresh")
    print("=" * 50)
    app.run(host="localhost", port=5002, debug=False)
