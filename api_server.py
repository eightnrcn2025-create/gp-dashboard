# =============================================================================
# Gamepark 看板 — 本地数据查询 API（Flask, port 5001）
# =============================================================================
# 安装依赖：pip install flask flask-cors
# 启动：  python3 api_server.py
# =============================================================================

import csv
import io
import json
import sqlite3
from pathlib import Path

from flask import Flask, Response, jsonify, request
from flask_cors import CORS

BASE_DIR         = Path(__file__).parent.resolve()
DB_FILE          = BASE_DIR / "database" / "gamepark.db"
WEEKLY_DATA_FILE = BASE_DIR / "data" / "weekly_data.json"
DATA_FILE        = BASE_DIR / "data" / "data.json"

app = Flask(__name__)
CORS(app)


# ── DB 连接 ───────────────────────────────────────────────────────────────────
def get_db():
    if not DB_FILE.exists():
        return None
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def _query(sql, params=()):
    conn = get_db()
    if conn is None:
        return []
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── 公共查询参数解析 ───────────────────────────────────────────────────────────
def date_filters():
    start = request.args.get("start", "")
    end   = request.args.get("end", "")
    clauses, params = [], []
    if start:
        clauses.append("date >= ?")
        params.append(start)
    if end:
        clauses.append("date <= ?")
        params.append(end)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


# =============================================================================
# 接口
# =============================================================================

@app.route("/api/daily")
def api_daily():
    """每日汇总指标（UV/PV/销售额/订单数/ARPU 等）"""
    where, params = date_filters()
    rows = _query(f"SELECT * FROM daily_stats {where} ORDER BY date DESC", params)
    return jsonify(rows)


@app.route("/api/games")
def api_games():
    """每日游戏销售明细，可按 type=solo|publisher 筛选"""
    start     = request.args.get("start", "")
    end       = request.args.get("end", "")
    game_type = request.args.get("type", "")
    clauses, params = [], []
    if start:     clauses.append("date >= ?");      params.append(start)
    if end:       clauses.append("date <= ?");      params.append(end)
    if game_type: clauses.append("game_type = ?"); params.append(game_type)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = _query(
        f"SELECT * FROM daily_game_sales {where} ORDER BY date DESC, sales DESC",
        params
    )
    return jsonify(rows)


@app.route("/api/weekly")
def api_weekly():
    """周数据报告（来自 weekly_data.json）"""
    try:
        with open(WEEKLY_DATA_FILE, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify({"weeks": [], "updated_at": ""})


@app.route("/api/summary")
def api_summary():
    """区间汇总统计（总销售额 / 平均 UV / 总订单 / 平均 ARPU）"""
    where, params = date_filters()
    rows = _query(f"SELECT * FROM daily_stats {where} ORDER BY date ASC", params)
    if not rows:
        return jsonify({
            "total_sales": 0, "avg_uv": 0,
            "total_orders": 0, "avg_arpu": 0,
            "days": 0, "start": "", "end": ""
        })
    total_sales   = sum(r["sales"]  for r in rows)
    total_orders  = sum(r["orders"] for r in rows)
    total_paying  = sum(r.get("paying_users", 0) for r in rows)
    avg_uv        = round(sum(r["uv"] for r in rows) / len(rows)) if rows else 0
    avg_arpu      = round(total_sales / total_paying, 2) if total_paying else 0
    return jsonify({
        "total_sales":  round(total_sales, 2),
        "avg_uv":       int(avg_uv),
        "total_orders": total_orders,
        "avg_arpu":     avg_arpu,
        "days":         len(rows),
        "start":        rows[0]["date"],
        "end":          rows[-1]["date"],
    })


@app.route("/api/export")
def api_export():
    """导出 CSV（daily_stats 区间数据）"""
    where, params = date_filters()
    rows = _query(
        f"""SELECT date,uv,pv,new_users,active_users,paying_users,
                   sales,orders,arpu,growth_rate,conversion_rate
            FROM daily_stats {where} ORDER BY date ASC""",
        params
    )
    out = io.StringIO()
    w   = csv.writer(out)
    w.writerow(["日期","UV","PV","新注册","活跃用户","付费用户",
                "销售额","订单数","ARPU","环比增长率%","转化率%"])
    for r in rows:
        w.writerow([r["date"], r["uv"], r["pv"], r["new_users"],
                    r["active_users"], r["paying_users"], r["sales"],
                    r["orders"], r["arpu"], r["growth_rate"], r["conversion_rate"]])
    start = request.args.get("start", "start")
    end   = request.args.get("end",   "end")
    return Response(
        out.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 f"attachment; filename=gamepark_{start}_{end}.csv"}
    )


@app.route("/api/status")
def api_status():
    """服务状态检查"""
    conn  = get_db()
    stats = {}
    if conn:
        for tbl in ["daily_stats", "daily_game_sales", "weekly_summary",
                    "weekly_daily_detail", "fetch_log"]:
            stats[tbl] = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        conn.close()
    return jsonify({"ok": True, "db": str(DB_FILE), "tables": stats})


# =============================================================================
if __name__ == "__main__":
    print("=" * 50)
    print("  Gamepark API 服务")
    print("  http://localhost:5001/api/status")
    print("  http://localhost:5001/api/daily")
    print("  http://localhost:5001/api/weekly")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5001, debug=False)
