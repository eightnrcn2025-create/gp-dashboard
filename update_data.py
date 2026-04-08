# =============================================================================
# Gamepark 运营数据看板 — 数据采集脚本
# =============================================================================
# 安装依赖：
#   pip install gspread google-auth playwright pandas openpyxl python-dotenv requests
#   playwright install chromium
#
# 使用方式：
#   python3 update_data.py
# =============================================================================

import os, re, json, time, traceback, requests, sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

# ── 路径 ──────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent.resolve()
DATA_DIR   = BASE_DIR / "data"
LOGS_DIR   = BASE_DIR / "logs"
DEBUG_DIR  = BASE_DIR / "debug"
DATA_FILE  = DATA_DIR  / "data.json"
LOG_FILE   = LOGS_DIR  / "update_log.txt"
CREDS_FILE = BASE_DIR  / "credentials.json"
ENV_FILE   = BASE_DIR  / ".env"
DB_DIR     = BASE_DIR  / "database"
DB_FILE    = DB_DIR    / "gamepark.db"
WEEKLY_DATA_FILE = DATA_DIR / "weekly_data.json"

# Google Sheets
SHEET1_ID  = "1oB5lVRHJ3g80wFpWy4w5yq2XiQ6ytCji1R_bddKOGEk"
SHEET1_GID = "769980440"
SHEET2_ID  = "1Ob7HPc3BRRGGD0ZFC6Yfaf4s0eQhkPPD5Qz0UnxReII"
SHEET2_GID = "866845188"

# Gamepark 后台
ADMIN_HOST  = "https://admin.gamepark.co"
API_BASE    = f"{ADMIN_HOST}/api"
# 单机游戏付费排行（gameType=alone，后台直接过滤，结果最准确）
STATS_URL_PAYMENT_SOLO = (
    f"{ADMIN_HOST}/?time=1756199148799"
    "#/statistics/game-statistics-more"
    "?statType=payment&gameType=alone&timeFilter=yesterday"
)
# 全游戏付费排行（gameType 留空；注意 gameType=publisher 后台返回结果与 all 相同，
# 所以"开发者游戏" = all 中不在 alone 中的游戏，用集合差求得）
STATS_URL_PAYMENT_ALL = (
    f"{ADMIN_HOST}/?time=1756199148799"
    "#/statistics/game-statistics-more"
    "?statType=payment&gameType=&timeFilter=yesterday"
)
# 7天兜底（无昨日数据时）
STATS_URL_PAYMENT_7D = (
    f"{ADMIN_HOST}/?time=1756199148799"
    "#/statistics/game-statistics-more"
    "?statType=payment&gameType=&timeFilter=7days"
)
# 全游戏访问量排行（昨日）
STATS_URL_VIEWS_ALL = (
    f"{ADMIN_HOST}/?time=1756199148799"
    "#/statistics/game-statistics-more"
    "?statType=views&gameType=&timeFilter=yesterday"
)
# 流量统计页
FLOW_STATS_URL = (
    f"{ADMIN_HOST}/?time=1756199148799"
    "#/statistics/flow-statistics"
)

# ── 厂商游戏白名单（名称包含以下关键词 → 归为厂商游戏，其余为单机游戏）────────
PUBLISHER_GAMES = [
    # 后台实际显示为简体中文，以下已校对（2026-04-07 debug 确认）
    "淫乱斗罗",        # 调试确认 ✓
    "全明星动漫乐园",  # 原繁体 全明星動漫樂園 → 简体
    "次元色潮",
    "火影娇妻村",      # 原繁体 火影嬌妻村 → 简体
    "海王传奇海王篇",
    "次元少女",
    "三国：红艳无双",
    "解禁无双",        # 原繁体 解禁無雙 → 简体，调试确认 ✓
    "火影色欲传",
    "三国：一统天下",
    "忍娘24",
    "口袋觉醒：成人版",
    "妻龙珠",
]

def clean_name(name: str) -> str:
    """
    去掉括号内容（含全角/半角/方括号）和多余空白，便于模糊匹配。
    注意：必须先去掉括号内容再去空白，防止括号开头的游戏名被清洗成空字符串
    后与所有白名单关键词产生假阳性匹配（"" in any_str 永远为 True）。
    """
    # 第1步：删除括号 + 括号内的内容（包括嵌套括号的情况）
    result = re.sub(r'[（(【\[][^）)\]】]*[）)\]】]', '', name)
    # 第2步：删除空白
    result = re.sub(r'\s+', '', result).strip()
    # 第3步：若清洗后为空（如整个名字就是括号内容），退回仅删空白的版本
    return result if result else re.sub(r'\s+', '', name).strip()

def is_publisher_game(game_name: str) -> bool:
    """
    游戏名匹配厂商游戏白名单：
    1. clean_name 去掉括号内容/空白后比较（防空字符串假阳性）
    2. 白名单关键词 in 游戏名（正向匹配）—— 不做反向匹配，避免空字符串误判
    """
    cleaned = clean_name(game_name)
    if not cleaned:
        return False
    return any(clean_name(kw) in cleaned for kw in PUBLISHER_GAMES)

# ── 日志 ──────────────────────────────────────────────────────────────────────
def log(msg, level="INFO"):
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line)
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def log_ok(msg):   log(msg, "OK")
def log_err(msg):  log(msg, "ERROR")
def log_warn(msg): log(msg, "WARN")

# ── 上次数据（容错保底）──────────────────────────────────────────────────────
def load_last_data():
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log_warn(f"读取上次 data.json 失败: {e}")
    return {
        "last_updated": "", "data_date": "", "update_time": "",
        "kpi": {"today_sales": 0, "yesterday_sales": 0,
                "growth_rate": 0, "total_traffic": 0, "conversion_rate": 0},
        "daily_sales": [], "solo_game_top5": [], "publisher_game_top5": [],
        "weekly_heatmap": [], "traffic_source": [], "detail_table": [],
        "monthly_total": 0, "active_games": 0
    }

# =============================================================================
# SQLite 数据库
# =============================================================================
def init_db():
    """初始化数据库表（幂等）"""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS daily_stats (
        date              TEXT PRIMARY KEY,
        uv                INTEGER DEFAULT 0,
        pv                INTEGER DEFAULT 0,
        new_users         INTEGER DEFAULT 0,
        active_users      INTEGER DEFAULT 0,
        paying_users      INTEGER DEFAULT 0,
        sales             REAL    DEFAULT 0,
        orders            INTEGER DEFAULT 0,
        arpu              REAL    DEFAULT 0,
        growth_rate       REAL    DEFAULT 0,
        conversion_rate   REAL    DEFAULT 0,
        created_at        TEXT    DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS daily_game_sales (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        date        TEXT    NOT NULL,
        game        TEXT    NOT NULL,
        sales       REAL    DEFAULT 0,
        uv          INTEGER DEFAULT 0,
        orders      INTEGER DEFAULT 0,
        game_type   TEXT    DEFAULT 'unknown',
        UNIQUE(date, game)
    );
    CREATE TABLE IF NOT EXISTS weekly_summary (
        period          TEXT PRIMARY KEY,
        sheet_name      TEXT,
        total_sales     REAL    DEFAULT 0,
        avg_daily_sales REAL    DEFAULT 0,
        total_uv        INTEGER DEFAULT 0,
        avg_uv          REAL    DEFAULT 0,
        new_users       INTEGER DEFAULT 0,
        created_at      TEXT    DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS weekly_daily_detail (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        period    TEXT    NOT NULL,
        date      TEXT    NOT NULL,
        sales     REAL    DEFAULT 0,
        uv        INTEGER DEFAULT 0,
        new_users INTEGER DEFAULT 0,
        UNIQUE(period, date)
    );
    CREATE TABLE IF NOT EXISTS fetch_log (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        run_time  TEXT NOT NULL,
        data_date TEXT,
        status    TEXT,
        message   TEXT
    );
    """)
    conn.commit()
    conn.close()
    log("DB 初始化完成")


def save_to_db(output, yesterday, weekly_weeks=None):
    """将本次采集结果存入 SQLite（INSERT OR IGNORE 防重复）"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c    = conn.cursor()
        ts   = output.get("traffic_stats", {})
        kpi  = output.get("kpi", {})

        # ── daily_stats ──────────────────────────────────────────────────────
        c.execute("""
        INSERT OR IGNORE INTO daily_stats
          (date,uv,pv,new_users,active_users,paying_users,sales,orders,arpu,growth_rate,conversion_rate)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (yesterday,
              ts.get("uv", 0), ts.get("pv", 0),
              ts.get("new_users", 0), ts.get("active_users", 0),
              ts.get("paying_users", 0),
              kpi.get("today_sales", 0),
              ts.get("order_count", 0),
              ts.get("arpu", 0),
              kpi.get("growth_rate", 0),
              kpi.get("conversion_rate", 0)))

        # ── daily_game_sales（TOP5 + detail_table）───────────────────────────
        for row in output.get("solo_game_top5", []):
            c.execute("INSERT OR IGNORE INTO daily_game_sales (date,game,sales,uv,orders,game_type) VALUES (?,?,?,?,?,?)",
                      (yesterday, row["game"], row.get("sales", 0), 0, 0, "solo"))
        for row in output.get("publisher_game_top5", []):
            c.execute("INSERT OR IGNORE INTO daily_game_sales (date,game,sales,uv,orders,game_type) VALUES (?,?,?,?,?,?)",
                      (yesterday, row["game"], row.get("sales", 0), 0, 0, "publisher"))
        for row in output.get("detail_table", []):
            name = str(row.get("game", ""))
            if not name or name == "所有游戏（汇总）":
                continue
            gtype = "publisher" if is_publisher_game(name) else "solo"
            traffic = row.get("traffic", 0) or 0
            conv    = row.get("conversion", 0) or 0
            c.execute("INSERT OR IGNORE INTO daily_game_sales (date,game,sales,uv,orders,game_type) VALUES (?,?,?,?,?,?)",
                      (row.get("date", yesterday), name,
                       row.get("sales", 0),
                       traffic,
                       int(conv * traffic / 100) if traffic else 0,
                       gtype))

        # ── weekly_summary + weekly_daily_detail ─────────────────────────────
        if weekly_weeks:
            for week in weekly_weeks:
                period = week.get("period", "")
                if not period:
                    continue
                sm = week.get("summary", {})
                c.execute("""
                INSERT OR IGNORE INTO weekly_summary
                  (period,sheet_name,total_sales,avg_daily_sales,total_uv,avg_uv,new_users)
                VALUES (?,?,?,?,?,?,?)
                """, (period, week.get("sheet_name",""),
                      sm.get("total_sales",0), sm.get("avg_daily_sales",0),
                      sm.get("total_uv",0), sm.get("avg_uv",0),
                      sm.get("new_users",0)))
                for day in week.get("daily", []):
                    c.execute("""
                    INSERT OR IGNORE INTO weekly_daily_detail (period,date,sales,uv,new_users)
                    VALUES (?,?,?,?,?)
                    """, (period, day.get("date",""),
                          day.get("sales",0), day.get("uv",0), day.get("new_users",0)))

        # ── fetch_log ─────────────────────────────────────────────────────────
        c.execute("INSERT INTO fetch_log (run_time,data_date,status,message) VALUES (?,?,?,?)",
                  (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), yesterday, "ok", "正常完成"))

        conn.commit()
        conn.close()
        log_ok("DB 存档完成")

        # 打印各表记录数
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        print("\n" + "=" * 50)
        print("数据库存档记录数：")
        for tbl in ["daily_stats","daily_game_sales","weekly_summary","weekly_daily_detail","fetch_log"]:
            c.execute(f"SELECT COUNT(*) FROM {tbl}")
            print(f"  {tbl}: {c.fetchone()[0]} 条")
        print("=" * 50)
        conn.close()

    except Exception as e:
        log_err(f"DB 存档失败: {e}\n{traceback.format_exc()}")


def export_history_cache():
    """
    将本次采集数据追加合并到 data/history_cache.json。
    CI 环境下 DB 不跨 run 持久化，通过合并已提交的 JSON 保留历史记录。
    """
    try:
        cache_path = DATA_DIR / "history_cache.json"

        # ── 1. 从 DB 读取本次采集结果 ─────────────────────────────────
        new_daily: list = []
        new_games: list = []
        if DB_FILE.exists():
            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row
            new_daily = [dict(r) for r in conn.execute(
                "SELECT * FROM daily_stats ORDER BY date ASC").fetchall()]
            new_games = [dict(r) for r in conn.execute(
                """SELECT date AS data_date, game AS game_name, game_type,
                          sales AS sales_amount, uv, orders
                   FROM daily_game_sales
                   ORDER BY date DESC, sales DESC""").fetchall()]
            conn.close()
        else:
            log_warn("DB 文件不存在，history_cache 仅合并现有 JSON")

        # ── 2. 加载已有历史（若存在）────────────────────────────────
        existing = {"daily_stats": [], "game_sales": []}
        if cache_path.exists():
            try:
                with open(cache_path, encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception as e:
                log_warn(f"读取已有 history_cache.json 失败: {e}")

        # ── 3. 按 key 合并去重（新数据覆盖旧）────────────────────────
        # daily_stats: key = date
        daily_map = {r["date"]: r for r in existing.get("daily_stats", [])}
        for r in new_daily:
            daily_map[r["date"]] = r

        # game_sales: key = (data_date, game_name)
        games_map = {(r["data_date"], r["game_name"]): r
                     for r in existing.get("game_sales", [])}
        for r in new_games:
            games_map[(r["data_date"], r["game_name"])] = r

        merged_daily = sorted(daily_map.values(), key=lambda x: x["date"])
        merged_games = sorted(games_map.values(),
                              key=lambda x: (x["data_date"], -(x.get("sales_amount") or 0)))

        result = {
            "export_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "daily_stats": merged_daily,
            "game_sales":  merged_games,
        }
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        log_ok(f"history_cache.json 导出完成：{len(merged_daily)} 天 · {len(merged_games)} 条游戏记录")

    except Exception as e:
        log_err(f"导出 history_cache.json 失败: {e}\n{traceback.format_exc()}")


# ── 工具 ──────────────────────────────────────────────────────────────────────
def to_num(val, default=0.0):
    try:
        return float(re.sub(r"[,，¥￥%\s\u00a0]", "", str(val)))
    except Exception:
        return default

def parse_date(val):
    val = str(val).strip()
    m = re.match(r'^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$', val)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    for fmt in ("%Y年%m月%d日", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(val, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None

def parse_chinese_date(val, year):
    m = re.search(r'(\d{1,2})月(\d{1,2})日', val)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{year:04d}-{mo:02d}-{d:02d}"
    return None

def save_shot(page, name):
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(DEBUG_DIR / f"{name}.png"), full_page=True)
        log(f"截图: {name}.png")
    except Exception as e:
        log_warn(f"截图失败: {e}")


# =============================================================================
# 后台 API 登录（返回 token + headers）
# =============================================================================
def admin_login():
    load_dotenv(ENV_FILE)
    account  = os.getenv("GAMEPARK_ACCOUNT", "")
    password = os.getenv("GAMEPARK_PASSWORD", "")
    r = requests.post(f"{API_BASE}/auth/admin/login",
                      json={"username": account, "password": password},
                      timeout=15)
    r.raise_for_status()
    token = r.json()["data"]["token"]
    return {"Authorization": f"Bearer {token}"}

def api_get(headers, path, params=None):
    r = requests.get(f"{API_BASE}{path}", headers=headers, params=params, timeout=15)
    r.raise_for_status()
    return r.json().get("data", {})


# =============================================================================
# 数据源一：后台 API — KPI + 日销售额 + 流量 + 用户行为
# =============================================================================
def fetch_admin_api(last):
    log("=== [API] 后台 REST 接口 ===")
    today     = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    month_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    result = {
        "today_sales":     last.get("kpi", {}).get("today_sales", 0),
        "yesterday_sales": last.get("kpi", {}).get("yesterday_sales", 0),
        "total_traffic":   last.get("kpi", {}).get("total_traffic", 0),
        "conversion_rate": last.get("kpi", {}).get("conversion_rate", 0),
        "daily_sales":     last.get("daily_sales", []),
        "traffic_source":  last.get("traffic_source", []),
    }
    dbg = {"run_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "steps": {}}

    def _save_dbg():
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(DATA_DIR / "debug_last_run.json", "w", encoding="utf-8") as _f:
                json.dump(dbg, _f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    try:
        headers = admin_login()
        log_ok("后台 API 登录成功")
        dbg["steps"]["login"] = "ok"

        # ── 1. 昨日/前日/本月订单统计（脚本在 0:05 运行，以"昨日"为主数据）────
        stats = api_get(headers, "/admin/orders/stats/recent")
        result["today_sales"]     = to_num(stats.get("yestoday", {}).get("total_amount", 0))
        result["yesterday_sales"] = to_num(stats.get("today",    {}).get("total_amount", 0))
        result["today_orders"]    = int(stats.get("yestoday",    {}).get("total_count", 0))
        result["month_sales"]     = to_num(stats.get("month",    {}).get("total_amount", 0))
        dbg["steps"]["orders_recent"] = {
            "yestoday_amount": result["today_sales"],
            "today_amount":    result["yesterday_sales"],
            "today_orders":    result["today_orders"],
        }
        log_ok(f"订单统计 → 昨日¥{result['today_sales']}  (data_date={yesterday})")

        # ── 2. 近30天每日订单（作为 daily_sales 主数据源）───────────────────
        daily_raw = api_get(headers, "/admin/orders/stats/recentDaily", {"period_type": "30d"})
        daily_list = daily_raw.get("daily_list", []) if isinstance(daily_raw, dict) else []
        if daily_list:
            # 过滤掉今日数据：脚本于 00:05 运行，今日数据极少且不完整，会造成图表误导性下跌
            result["daily_sales"] = [
                {"date": row["order_date"], "amount": to_num(row["total_amount"])}
                for row in sorted(daily_list, key=lambda x: x["order_date"])
                if row["order_date"] != today
            ]
            dbg["steps"]["daily_sales"] = {"count": len(result["daily_sales"]),
                                            "last3": result["daily_sales"][-3:]}
            log_ok(f"日销售额 → {len(result['daily_sales'])} 条（近30天，不含今日）")

        # ── 3. 流量汇总（昨日 UV/PV/新注册/活跃/付费用户）
        # API 不受日期参数影响，始终返回 yesterday（昨日完整）和 today（今日截至当前）
        # 脚本于 00:05 运行，必须用 "yesterday" 字段取昨日完整数据
        summary_list = api_get(headers, "/admin/platform/userstats/summary",
                                {"started_at": yesterday, "ended_at": yesterday})
        dbg["steps"]["userstats_raw"] = summary_list   # 保存完整原始返回
        summary = {item["title"]: item.get("yesterday", 0) for item in (summary_list or [])}
        uv               = int(summary.get("uv", 0))
        pv               = int(summary.get("pv", 0))
        new_reg          = int(summary.get("register_new", 0))
        active_users     = int(summary.get("active_user", 0))
        paid_users       = int(summary.get("recharged_count", 0))
        recharged_amount = float(summary.get("recharged_amount", 0))
        arpu_api         = float(summary.get("arpu", 0))
        avg_order_val    = float(summary.get("average_order_value", 0))
        result["total_traffic"]     = uv
        result["pv"]                = pv
        result["new_reg"]           = new_reg
        result["active_users"]      = active_users
        result["paid_users"]        = paid_users
        result["recharged_amount"]  = recharged_amount
        result["arpu_api"]          = arpu_api
        result["avg_order_val_api"] = avg_order_val
        dbg["steps"]["userstats_parsed"] = {
            "uv": uv, "pv": pv, "new_reg": new_reg, "active_users": active_users,
            "paid_users": paid_users, "recharged_amount": recharged_amount,
            "arpu": arpu_api, "avg_order_value": avg_order_val,
        }
        log_ok(f"流量汇总 → UV={uv}  PV={pv}  新注册={new_reg}  活跃={active_users}"
               f"  充值用户={paid_users}  充值金额=¥{recharged_amount}  ARPU=¥{arpu_api}")

        # ── 4. 转化率（付费用户 / UV）────────────────────────────────────────
        result["conversion_rate"] = round(result["today_orders"] / uv * 100, 2) if uv > 0 else 0

        # ── 5. 用户行为分布（替代伪造的流量来源）────────────────────────────
        browse_only   = max(0, uv - new_reg)
        result["traffic_source"] = [
            {"source": "仅浏览（未注册）", "value": browse_only},
            {"source": "新注册用户",       "value": new_reg},
            {"source": "活跃老用户",       "value": active_users},
            {"source": "付费/充值用户",    "value": paid_users},
        ]
        log_ok(f"用户行为分布 → 仅浏览:{browse_only}  注册:{new_reg}  活跃:{active_users}  付费:{paid_users}")

        _save_dbg()
        return result

    except Exception as e:
        dbg["steps"]["error"] = {"msg": str(e), "trace": traceback.format_exc()}
        log_err(f"后台 API 失败: {e}\n{traceback.format_exc()}")
        _save_dbg()
        return result


# =============================================================================
# 数据源二：后台 Playwright — 游戏付费/访问排行 + 流量统计页
# =============================================================================
def fetch_admin_game_stats(last):
    log("=== [Playwright] 游戏排行 + 流量统计 ===")
    fallback = {
        "solo_game_top5":            last.get("solo_game_top5", []),
        "publisher_game_top5":       last.get("publisher_game_top5", []),
        "game_views_top5":           last.get("game_views_top5", []),
        "game_views_publisher_top5": last.get("game_views_publisher_top5", []),
        "detail_rows":               last.get("detail_table", []),
        "flow_stats":                last.get("traffic_stats", {}),
    }
    load_dotenv(ENV_FILE)
    account  = os.getenv("GAMEPARK_ACCOUNT", "")
    password = os.getenv("GAMEPARK_PASSWORD", "")

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            ctx  = browser.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()

            # ── 登录 ──────────────────────────────────────────────────────────
            page.goto(ADMIN_HOST, wait_until="networkidle", timeout=30000)
            time.sleep(1)
            page.fill('input[type="text"]',     account)
            page.fill('input[type="password"]', password)
            page.click('button:has-text("登录")')
            page.wait_for_load_state("networkidle", timeout=20000)
            time.sleep(2)
            save_shot(page, "login_success")

            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

            def click_time_filter(label_text="昨日"):
                """尝试点击时间筛选按钮（昨日/7天等）"""
                for sel in [
                    f'button:has-text("{label_text}")',
                    f'.el-button:has-text("{label_text}")',
                    f'[class*="btn"]:has-text("{label_text}")',
                    f'span:has-text("{label_text}")',
                    f'li:has-text("{label_text}")',
                ]:
                    try:
                        page.click(sel, timeout=2000)
                        time.sleep(2)
                        log(f"点击时间筛选「{label_text}」成功（{sel}）")
                        return True
                    except Exception:
                        pass
                log_warn(f"未找到时间筛选按钮「{label_text}」")
                return False

            def extract_tables_rows(label):
                """从当前页面所有 table 中提取游戏统计行，打印页面文字辅助调试"""
                tables = page.query_selector_all("table")
                log(f"[{label}] 页面共 {len(tables)} 个 table")
                # 打印页面文本前1500字（辅助调试）
                try:
                    txt = page.inner_text("body")
                    log(f"[{label}] 页面文本前1500字:\n{txt[:1500]}")
                except Exception:
                    pass

                rows = []
                for t_idx, tbl in enumerate(tables):
                    for tr in tbl.query_selector_all("tr"):
                        cells = tr.query_selector_all("td")
                        if len(cells) < 5:
                            continue
                        # 尝试不同列位置：找包含金额数字的行
                        # 优先 col2=游戏名，尝试 col8 / col6 / col4 作为金额
                        game_name = cells[2].inner_text().strip()
                        if not game_name:
                            continue
                        # 尝试从多个列位找金额（销售额通常是最后几列最大的数）
                        amounts = []
                        for ci in [8, 6, 4]:
                            if len(cells) > ci:
                                v = to_num(cells[ci].inner_text())
                                if v > 0:
                                    amounts.append((ci, v))
                        if not amounts:
                            continue
                        payment = amounts[0][1]   # 取第一个非零金额列
                        col4    = to_num(cells[4].inner_text()) if len(cells) > 4 else 0
                        col6    = to_num(cells[6].inner_text()) if len(cells) > 6 else 0
                        rows.append({
                            "game": game_name, "table_idx": t_idx,
                            "uv": int(col4), "orders": int(col6), "payment": payment,
                        })
                return rows

            def scrape_game_table(url, label, need_time_click=False):
                """
                导航到 URL，截图，用 .el-table__row 提取数据。
                URL 里已含 timeFilter=xxx 时不需要点按钮（need_time_click=False）。
                """
                log(f"[{label}] 正在导航: {url}")
                page.goto(url, wait_until="networkidle", timeout=40000)
                # 等 8 秒确保 Vue + Element UI 完全渲染
                time.sleep(8)
                save_shot(page, f"game_statistics_{label}")

                if need_time_click:
                    click_time_filter("昨日")
                    time.sleep(3)
                    save_shot(page, f"game_statistics_{label}_after_click")

                # 优先用 Element UI 行选择器
                rows = []
                el_rows = page.query_selector_all(".el-table__row")
                if el_rows:
                    log(f"[{label}] .el-table__row 找到 {len(el_rows)} 行")
                    for tr in el_rows:
                        cells = tr.query_selector_all("td")
                        if len(cells) < 9:
                            continue
                        game_name = cells[2].inner_text().strip()
                        if not game_name:
                            continue
                        payment = to_num(cells[8].inner_text())
                        col4    = to_num(cells[4].inner_text())
                        col6    = to_num(cells[6].inner_text())
                        rows.append({
                            "game": game_name,
                            "uv":      int(col4),
                            "orders":  int(col6),
                            "payment": payment,
                        })
                else:
                    # 降级：扫描所有 table
                    log_warn(f"[{label}] .el-table__row 为空，降级扫描 tables")
                    rows = extract_tables_rows(label)

                log_ok(f"[{label}] 抓取 {len(rows)} 条")
                for r in rows:
                    print(f"原始游戏数据：{r['game']} | 销售额：{r['payment']}")
                return rows

            def scrape_via_menu(time_filter="昨日"):
                """方案B：通过左侧菜单导航到游戏统计页面"""
                try:
                    log("尝试菜单导航：数据统计 → 游戏统计")
                    # 展开「数据统计」菜单
                    for sel in ['li:has-text("数据统计")', '.el-menu-item:has-text("数据统计")',
                                '[class*="menu"]:has-text("数据统计")', 'span:has-text("数据统计")']:
                        try:
                            page.click(sel, timeout=3000)
                            time.sleep(1)
                            log(f"点击「数据统计」成功（{sel}）")
                            break
                        except Exception:
                            pass
                    # 点击「游戏统计」子菜单
                    for sel in ['li:has-text("游戏统计")', '.el-menu-item:has-text("游戏统计")',
                                'a:has-text("游戏统计")', 'span:has-text("游戏统计")']:
                        try:
                            page.click(sel, timeout=3000)
                            time.sleep(3)
                            log(f"点击「游戏统计」成功（{sel}）")
                            break
                        except Exception:
                            pass
                    save_shot(page, "game_statistics_page")
                    time.sleep(8)
                    click_time_filter(time_filter)  # 菜单导航没有URL时间参数，需手动点击
                    time.sleep(3)
                    save_shot(page, "game_statistics_yesterday")
                    # 菜单导航用 .el-table__row
                    rows = []
                    el_rows = page.query_selector_all(".el-table__row")
                    for tr in el_rows:
                        cells = tr.query_selector_all("td")
                        if len(cells) < 9:
                            continue
                        gname = cells[2].inner_text().strip()
                        if not gname:
                            continue
                        rows.append({
                            "game": gname,
                            "uv":      int(to_num(cells[4].inner_text())),
                            "orders":  int(to_num(cells[6].inner_text())),
                            "payment": to_num(cells[8].inner_text()),
                        })
                    if not rows:
                        rows = extract_tables_rows("menu_nav")
                    log_ok(f"菜单导航抓取 {len(rows)} 条")
                    return rows
                except Exception as e:
                    log_err(f"菜单导航失败: {e}")
                    return []

            # ── 1. 单机游戏付费排行（gameType=alone，后台直接过滤最准确）────────
            solo_rows = scrape_game_table(STATS_URL_PAYMENT_SOLO, "payment_solo")
            if not solo_rows:
                log_warn("单机URL无数据，尝试菜单导航...")
                solo_rows = scrape_via_menu("昨日")
            if not solo_rows:
                log_warn("改用7天单机数据兜底...")
                solo_rows = scrape_game_table(
                    STATS_URL_PAYMENT_7D.replace("gameType=", "gameType=alone"), "solo_7d")

            solo_names = {r["game"] for r in solo_rows}
            log_ok(f"单机游戏 {len(solo_rows)} 款")
            for r in solo_rows:
                print(f"[单机] {r['game']} | ¥{r['payment']}")

            # ── 2. 全游戏排行；开发者游戏 = all 中不在 alone 的游戏 ───────────
            # （调试证实 gameType=publisher URL 返回结果与 gameType=all 相同，不能用）
            all_rows = scrape_game_table(STATS_URL_PAYMENT_ALL, "payment_all")
            if not all_rows:
                all_rows = solo_rows  # 极端兜底
            all_names  = {r["game"] for r in all_rows}
            publisher_pool = [r for r in all_rows if r["game"] not in solo_names]

            log_ok(f"全部游戏 {len(all_rows)} 款 → 开发者游戏 {len(publisher_pool)} 款")
            for r in publisher_pool:
                print(f"[开发者] {r['game']} | ¥{r['payment']}")

            # ── 3. 若开发者池为空，用7天数据兜底 ────────────────────────────
            if not publisher_pool:
                log_warn("昨日无开发者游戏数据，改用近7天兜底...")
                rows_7d = scrape_game_table(STATS_URL_PAYMENT_7D, "payment_7d")
                solo_names_7d = {r["game"] for r in solo_rows}
                publisher_pool = [r for r in rows_7d if r["game"] not in solo_names_7d]
                log_ok(f"7天兜底后 → 开发者 {len(publisher_pool)} 款")

            # 合并all+solo去重，供 detail_table 用
            payment_rows = list({r["game"]: r for r in (all_rows + solo_rows)}.values())

            # ── 4. 昨日全游戏访问量排行 ──────────────────────────────────────
            views_rows = scrape_game_table(STATS_URL_VIEWS_ALL, "views_all")
            # views 表中 col4 = 访问量（存储在 uv 字段）
            views_solo_pool = [r for r in views_rows if not is_publisher_game(r["game"])]
            views_pub_pool  = [r for r in views_rows if     is_publisher_game(r["game"])]

            def views_rows_to_top5(rows):
                sorted_rows = sorted(rows, key=lambda x: x.get("uv", 0), reverse=True)
                return [
                    {"rank": i + 1, "game": r["game"], "views": r.get("uv", 0)}
                    for i, r in enumerate(sorted_rows[:5])
                ]

            game_views_top5           = views_rows_to_top5(views_solo_pool)
            game_views_publisher_top5 = views_rows_to_top5(views_pub_pool)

            # ── 5. 流量统计页抓取 ─────────────────────────────────────────────
            flow_stats = {}
            FLOW_LABEL_MAP = {
                "pv":              ["PV", "浏览量"],
                "uv":              ["UV", "访客数"],
                "ip":              ["IP数", "IP"],
                "bounce_rate":     ["跳出率"],
                "avg_duration":    ["平均访问时长", "访问时长"],
                "total_users":     ["总注册用户数", "累计注册"],
                "new_users":       ["新增注册用户数", "新增注册", "新注册"],
                "active_users":    ["活跃用户数", "活跃用户"],
                "paying_users":    ["充值用户数", "充值用户"],
                "payment_amount":  ["充值额度", "充值金额"],
                "order_count":     ["订单支付人数", "支付人数"],
                "order_amount":    ["订单支付额度", "支付额度"],
                "arpu":            ["ARPU"],
                "avg_order_value": ["客单价"],
            }
            try:
                page.goto(FLOW_STATS_URL, wait_until="networkidle", timeout=30000)
                time.sleep(3)
                # 点击"昨日"按钮
                for sel in ['button:has-text("昨日")', '.el-button:has-text("昨日")',
                            '[class*="btn"]:has-text("昨日")', 'span:has-text("昨日")']:
                    try:
                        page.click(sel, timeout=2000)
                        time.sleep(2)
                        log(f"流量统计：点击昨日按钮成功（{sel}）")
                        break
                    except Exception:
                        pass
                save_shot(page, "flow_stats")

                # 方法1：查找统计卡片元素
                for css in [".el-statistic", ".stat-item", ".data-item",
                            "[class*='statistic']", "[class*='number-card']"]:
                    items = page.query_selector_all(css)
                    if items:
                        log(f"流量统计 - {css} 找到 {len(items)} 个元素")
                        for item in items:
                            try:
                                text = item.inner_text().strip()
                                if not text:
                                    continue
                                log(f"  [{css}] {repr(text[:80])}")
                                for field, labels in FLOW_LABEL_MAP.items():
                                    for lbl in labels:
                                        if lbl in text and field not in flow_stats:
                                            nums = re.findall(r'[\d,]+\.?\d*', text)
                                            if nums:
                                                val = nums[0].replace(',', '')
                                                flow_stats[field] = float(val) if '.' in val else int(val)
                                            break
                            except Exception:
                                pass
                        if flow_stats:
                            break

                # 方法2：扫描整页文本行
                if not flow_stats:
                    lines = [l.strip() for l in page.inner_text("body").split("\n") if l.strip()]
                    for i, line in enumerate(lines):
                        for field, labels in FLOW_LABEL_MAP.items():
                            for lbl in labels:
                                if lbl in line and field not in flow_stats:
                                    for candidate in [line] + lines[i+1:i+3]:
                                        nums = re.findall(r'[\d,]+\.?\d*', candidate)
                                        if nums:
                                            val = nums[0].replace(',', '')
                                            flow_stats[field] = float(val) if '.' in val else int(val)
                                            break
                                    break

                log_ok(f"流量统计页抓取结果（{len(flow_stats)} 项）: {flow_stats}")
            except Exception as e:
                log_err(f"流量统计页抓取失败: {e}")

            # ── 6. 整理付费 TOP5 ──────────────────────────────────────────────
            def rows_to_top5(rows):
                sorted_rows = sorted(rows, key=lambda x: x["payment"], reverse=True)
                return [
                    {"rank": i + 1, "game": r["game"], "sales": r["payment"], "growth": 0}
                    for i, r in enumerate(sorted_rows[:5])
                ]

            solo_top5      = rows_to_top5(solo_rows)
            publisher_top5 = rows_to_top5(publisher_pool)

            log_ok(f"分类结果 → 单机 {len(solo_rows)} 款 / 厂商 {len(publisher_pool)} 款")
            log(f"  单机 TOP5   : {[r['game'] for r in solo_top5]}")
            log(f"  厂商 TOP5   : {[r['game'] for r in publisher_top5]}")
            log(f"  访问 TOP5   : {[r['game'] for r in game_views_top5]}")
            log(f"  厂商访问TOP5: {[r['game'] for r in game_views_publisher_top5]}")

            detail_rows = [{
                "date":       yesterday,
                "game":       r["game"],
                "traffic":    r["uv"],
                "sales":      r["payment"],
                "conversion": round(r["orders"] / r["uv"] * 100, 2) if r["uv"] > 0 else 0,
            } for r in payment_rows]

            browser.close()

        result_data = {
            "solo_game_top5":            solo_top5,
            "publisher_game_top5":       publisher_top5,
            "game_views_top5":           game_views_top5,
            "game_views_publisher_top5": game_views_publisher_top5,
            "detail_rows":               detail_rows,
            "flow_stats":                flow_stats,
            "_playwright_ok":            True,
        }
        # 写 Playwright 调试摘要
        try:
            dbg_pw = {
                "status": "success",
                "solo_top5":      [{"game": r["game"], "sales": r["sales"]} for r in solo_top5[:3]],
                "publisher_top5": [{"game": r["game"], "sales": r["sales"]} for r in publisher_top5[:3]],
                "views_top5":     [{"game": r["game"], "views": r["views"]} for r in game_views_top5[:3]],
                "detail_rows_count": len(detail_rows),
            }
            dbg_path = Path(__file__).parent / "data" / "debug_last_run.json"
            if dbg_path.exists():
                with open(dbg_path, encoding="utf-8") as _f:
                    existing = json.load(_f)
            else:
                existing = {}
            existing.setdefault("steps", {})["playwright"] = dbg_pw
            with open(dbg_path, "w", encoding="utf-8") as _f:
                json.dump(existing, _f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return result_data

    except Exception as e:
        log_err(f"Playwright 失败: {e}\n{traceback.format_exc()}")
        # 记录 Playwright 失败原因
        try:
            dbg_path = Path(__file__).parent / "data" / "debug_last_run.json"
            if dbg_path.exists():
                with open(dbg_path, encoding="utf-8") as _f:
                    existing = json.load(_f)
            else:
                existing = {}
            existing.setdefault("steps", {})["playwright"] = {
                "status": "failed",
                "error": str(e),
                "trace": traceback.format_exc(),
            }
            with open(dbg_path, "w", encoding="utf-8") as _f:
                json.dump(existing, _f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return fallback




# =============================================================================
# 数据源三：Google Sheets — Sheet2 每日明细（补充 detail_table）
# =============================================================================
def fetch_sheet2_detail(last):
    log("=== [Sheet2] 每日明细补充 ===")
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = ["https://spreadsheets.google.com/feeds",
                  "https://www.googleapis.com/auth/drive"]
        creds  = Credentials.from_service_account_file(str(CREDS_FILE), scopes=scopes)
        client = gspread.authorize(creds)

        sh = client.open_by_key(SHEET2_ID)
        ws = next((w for w in sh.worksheets() if str(w.id) == SHEET2_GID), sh.sheet1)
        rows = ws.get_all_values()
        log(f"Sheet2 '{ws.title}'  {len(rows)} 行")

        # 提取年份
        year = datetime.now().year
        for row in rows:
            for cell in row:
                m = re.search(r'(\d{4})-\d{2}-\d{2}', cell)
                if m:
                    year = int(m.group(1))
                    break

        # 找每日明细表头
        detail_header_idx = next((i for i, r in enumerate(rows) if r and r[0].strip() == "日期"), None)
        if detail_header_idx is None:
            log_warn("Sheet2 未找到'日期'明细行")
            return []

        detail = []
        for row in rows[detail_header_idx + 1:]:
            if not row or not row[0].strip() or row[0].strip() in ("合计/均值", "合计"):
                continue
            date_str = parse_chinese_date(row[0], year) or parse_date(row[0])
            if not date_str:
                continue
            sales = to_num(row[1]) if len(row) > 1 else 0
            uv    = int(to_num(row[3])) if len(row) > 3 else 0
            if sales > 0:
                detail.append({
                    "date":       date_str,
                    "game":       "所有游戏（汇总）",
                    "traffic":    uv,
                    "sales":      sales,
                    "conversion": 0,
                })
        log_ok(f"Sheet2 每日明细 → {len(detail)} 条")
        return detail

    except Exception as e:
        log_err(f"Sheet2 失败: {e}\n{traceback.format_exc()}")
        return []


# =============================================================================
# 数据源四：Google Sheets — 全部 Sheet 周数据汇总
# =============================================================================
def parse_sheet_period(title: str) -> str:
    """
    将 Sheet 标题解析为标准周期字符串，例如：
    "2026.4.3-4.9"  → "2026-04-03~2026-04-09"
    "4.3-4.9"       → "<当前年>-04-03~<当前年>-04-09"
    "2026-04-03~2026-04-09" → "2026-04-03~2026-04-09"（直通）
    """
    year_m = re.search(r'(\d{4})', title)
    year   = int(year_m.group(1)) if year_m else datetime.now().year

    # 去掉年份前缀，只保留月日部分
    rest = re.sub(r'^\d{4}[.\-_]?', '', title).strip()

    # "4.3-4.9" / "4.3~4.9" / "4/3-4/9"
    m = re.match(r'(\d{1,2})[./](\d{1,2})\s*[-~]\s*(\d{1,2})[./](\d{1,2})', rest)
    if m:
        m1, d1, m2, d2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        return f"{year}-{m1:02d}-{d1:02d}~{year}-{m2:02d}-{d2:02d}"

    # "2026-04-03~2026-04-09"
    m2 = re.match(r'(\d{4}-\d{2}-\d{2})\s*[~-]\s*(\d{4}-\d{2}-\d{2})', title)
    if m2:
        return f"{m2.group(1)}~{m2.group(2)}"

    return ""


def fetch_weekly_data_all_sheets():
    """读取 SHEET2 所有工作表，合并为 data/weekly_data.json"""
    log("=== [Sheets] 多 Sheet 周数据读取 ===")
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = ["https://spreadsheets.google.com/feeds",
                  "https://www.googleapis.com/auth/drive"]
        creds  = Credentials.from_service_account_file(str(CREDS_FILE), scopes=scopes)
        client = gspread.authorize(creds)

        sh         = client.open_by_key(SHEET2_ID)
        worksheets = sh.worksheets()
        log(f"发现 {len(worksheets)} 个工作表")

        weeks = []
        for ws in worksheets:
            title  = ws.title.strip()
            period = parse_sheet_period(title)
            if not period:
                log_warn(f"  无法解析周期，跳过: {title}")
                continue
            log(f"处理工作表: {title} → period={period}")

            try:
                rows = ws.get_all_values()
                if not rows:
                    continue

                # 年份：优先从标题提取
                year_m = re.search(r'(\d{4})', title)
                year   = int(year_m.group(1)) if year_m else datetime.now().year

                # 找"日期"表头行
                detail_header_idx = next(
                    (i for i, r in enumerate(rows) if r and r[0].strip() == "日期"), None)

                # 每日明细
                daily = []
                if detail_header_idx is not None:
                    for row in rows[detail_header_idx + 1:]:
                        if not row or not row[0].strip():
                            continue
                        if row[0].strip() in ("合计/均值", "合计", "平均"):
                            continue
                        date_str = parse_chinese_date(row[0], year) or parse_date(row[0])
                        if not date_str:
                            continue
                        # Sheet 列顺序：日期 / 销售额 / 浏览量(PV) / 访客数(UV) / ARPU
                        sales = to_num(row[1]) if len(row) > 1 else 0
                        pv    = int(to_num(row[2])) if len(row) > 2 else 0
                        uv    = int(to_num(row[3])) if len(row) > 3 else 0
                        arpu  = round(to_num(row[4]), 4) if len(row) > 4 else 0
                        daily.append({
                            "date":  date_str,
                            "sales": round(sales, 2),
                            "pv":    pv,
                            "uv":    uv,
                            "arpu":  arpu,
                        })

                # 汇总（Sheet 列：日期/销售额/PV/UV/ARPU，无新增用户列）
                summary: dict = {}
                if daily:
                    total_sales = round(sum(d["sales"] for d in daily), 2)
                    total_pv    = sum(d["pv"] for d in daily)
                    total_uv    = sum(d["uv"] for d in daily)
                    n           = len(daily)
                    summary = {
                        "total_sales":     total_sales,
                        "avg_daily_sales": round(total_sales / n, 2) if n else 0,
                        "total_pv":        total_pv,
                        "total_uv":        total_uv,
                        "avg_uv":          round(total_uv / n, 2) if n else 0,
                        "avg_arpu":        round(sum(d["arpu"] for d in daily) / n, 4) if n else 0,
                        "new_users":       0,   # Sheet 中无此列
                    }

                weeks.append({
                    "period":     period,
                    "sheet_name": title,
                    "summary":    summary,
                    "daily":      sorted(daily, key=lambda x: x["date"]),
                    "totals": {
                        "sales": summary.get("total_sales", 0),
                        "uv":    summary.get("total_uv", 0),
                    },
                })
                log_ok(f"  {title} → {len(daily)} 天  总¥{summary.get('total_sales',0):,.2f}")

            except Exception as e:
                log_err(f"  工作表 {title} 处理失败: {e}")
                continue

        # 按周期倒序（最新在前）
        weeks.sort(key=lambda x: x["period"], reverse=True)

        result = {
            "weeks":      weeks,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(WEEKLY_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        log_ok(f"weekly_data.json 已保存：{len(weeks)} 周数据")
        return weeks

    except Exception as e:
        log_err(f"多 Sheet 读取失败: {e}\n{traceback.format_exc()}")
        return []


# =============================================================================
# 主流程
# =============================================================================
def main():
    t0 = datetime.now()
    yesterday = (t0 - timedelta(days=1)).strftime("%Y-%m-%d")
    log("=" * 60)
    log(f"正在抓取 [{yesterday}]（昨日）的数据...")
    log(f"脚本执行时间：{t0.strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 60)

    load_dotenv(ENV_FILE)
    init_db()
    last = load_last_data()

    # ── 四路采集 ──────────────────────────────────────────────────────────────
    api_data      = fetch_admin_api(last)
    game_data     = fetch_admin_game_stats(last)
    sheet2_det    = fetch_sheet2_detail(last)
    weekly_weeks  = fetch_weekly_data_all_sheets()

    # ── 整理日销售数据 ──────────────────────────────────────────────────────
    daily_sales = api_data.get("daily_sales") or last.get("daily_sales", [])

    # ── 计算环比（昨日 vs 前日，两个完整日的对比）───────────────────────────
    # api_data["today_sales"] = API的 yestoday（昨日完整数据，脚本在 00:05 运行）
    # recentDaily 末尾结构: [-3]=前日完整  [-2]=昨日完整  [-1]=今天(不完整)
    # 前日 = yesterday-2天，按日期精确匹配避免偏移
    today_sales    = api_data["today_sales"]
    day_before_str = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    day_before_entry = next(
        (r for r in daily_sales if r["date"] == day_before_str), None
    )
    if day_before_entry:
        yesterday_sales = day_before_entry["amount"]
    elif len(daily_sales) >= 3:
        yesterday_sales = daily_sales[-3]["amount"]   # 兜底：倒数第三条
    else:
        yesterday_sales = api_data.get("yesterday_sales", 0)
    growth_rate = (
        round((today_sales - yesterday_sales) / yesterday_sales * 100, 2)
        if yesterday_sales else 0.0
    )

    # ── 合并 detail_table（游戏明细 + 汇总行）────────────────────────────────
    detail_table = game_data.get("detail_rows", []) + sheet2_det
    detail_table.sort(key=lambda x: (x["date"], x["game"]), reverse=True)

    # ── 新增字段计算 ──────────────────────────────────────────────────────────
    solo_game_top5           = game_data.get("solo_game_top5")            or last.get("solo_game_top5", [])
    publisher_game_top5      = game_data.get("publisher_game_top5")       or last.get("publisher_game_top5", [])
    game_views_top5          = game_data.get("game_views_top5")           or last.get("game_views_top5", [])
    game_views_publisher_top5= game_data.get("game_views_publisher_top5") or last.get("game_views_publisher_top5", [])

    # 周环比热力图 = daily_sales（前端JS自动补齐56天格子）
    weekly_heatmap = daily_sales

    # 本月累计销售额 = 后台 API month 字段，兜底用当月 daily_sales 求和
    month_sales = api_data.get("month_sales", 0)
    if not month_sales:
        this_month = (datetime.now() - timedelta(days=1)).strftime("%Y-%m")  # 昨日所在月
        month_sales = round(
            sum(r["amount"] for r in daily_sales if r["date"].startswith(this_month)), 2
        )

    # 活跃游戏数 = 昨日有付费记录的游戏数（排除汇总行）
    detail_rows_raw = game_data.get("detail_rows", [])
    active_games = len({
        r["game"] for r in detail_rows_raw
        if r.get("game") and r["game"] != "所有游戏（汇总）"
    }) or (len(solo_game_top5) + len(publisher_game_top5))

    # ── 流量统计（API + Playwright 流量页融合）────────────────────────────────
    flow_stats        = game_data.get("flow_stats", {})
    # ── 以下字段 API 已提供准确值，不从 flow_stats 覆盖 ────────────────────────
    # API userstats/summary 的 "yesterday" 字段是权威来源；
    # Playwright 抓的流量统计页不稳定（昨日按钮未必点成功、值可能为0），
    # 且 dict.get(key, default) 在 key=0 时不会使用 default，会导致 0 覆盖正确值。
    uv                = api_data.get("total_traffic", 0)
    pv_val            = api_data.get("pv", 0)
    new_reg           = api_data.get("new_reg", 0)
    active_users      = api_data.get("active_users", 0)
    paid_users        = api_data.get("paid_users", 0)
    today_orders      = api_data.get("today_orders", 0)
    recharged_amount  = api_data.get("recharged_amount", 0)
    arpu_api          = api_data.get("arpu_api", 0)
    avg_order_val_api = api_data.get("avg_order_val_api", 0)

    traffic_stats = {
        # 核心用户/流量指标：完全来自 API，不被 Playwright 覆盖
        "pv":              pv_val,
        "uv":              uv,
        "new_users":       new_reg,
        "active_users":    active_users,
        "paying_users":    paid_users,
        "payment_amount":  round(recharged_amount, 2),       # 充值金额
        "order_count":     today_orders,
        "order_amount":    round(float(today_sales), 2),     # 订单支付总额
        "arpu":            round(arpu_api, 2),               # API 直接返回
        "avg_order_value": round(avg_order_val_api, 2),      # API 直接返回
        # 以下字段 API 无法提供，仅 Playwright 可抓（不存在时留空）
        "ip":           int(flow_stats.get("ip", 0)),
        "bounce_rate":  flow_stats.get("bounce_rate", ""),
        "avg_duration": flow_stats.get("avg_duration", ""),
        "total_users":  int(flow_stats.get("total_users", 0)),
    }
    log_ok(f"流量统计汇总 → UV={traffic_stats['uv']}  PV={traffic_stats['pv']}"
           f"  新注册={traffic_stats['new_users']}  活跃={traffic_stats['active_users']}"
           f"  充值用户={traffic_stats['paying_users']}  充值¥{traffic_stats['payment_amount']}"
           f"  订单¥{traffic_stats['order_amount']}  ARPU=¥{traffic_stats['arpu']}"
           f"  客单价=¥{traffic_stats['avg_order_value']}")

    # ── 组装输出 ──────────────────────────────────────────────────────────────
    update_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    output = {
        "last_updated":  update_ts,
        "data_date":     yesterday,                        # 昨日日期（数据日期）
        "update_time":   update_ts,                        # 脚本运行时间
        "kpi": {
            "today_sales":     round(today_sales, 2),      # 昨日完整销售额
            "yesterday_sales": round(yesterday_sales, 2),  # 前日销售额（环比基准）
            "growth_rate":     growth_rate,
            "total_traffic":   api_data["total_traffic"],
            "conversion_rate": api_data["conversion_rate"],
        },
        "daily_sales":               daily_sales,
        "solo_game_top5":            solo_game_top5,
        "publisher_game_top5":       publisher_game_top5,
        "game_views_top5":           game_views_top5,
        "game_views_publisher_top5": game_views_publisher_top5,
        "weekly_heatmap":            weekly_heatmap,
        "monthly_total":             month_sales,
        "active_games":              active_games,
        "traffic_stats":             traffic_stats,
        "traffic_source":            api_data.get("traffic_source") or last.get("traffic_source", []),
        "detail_table":              detail_table or last.get("detail_table", []),
    }

    # ── 强制兜底：从 detail_table 重建 TOP5（防止 Playwright 分类失败导致空列表）──
    final_detail = output["detail_table"]
    if final_detail and (not output["publisher_game_top5"] or not output["solo_game_top5"]):
        log("=== 从 detail_table 重建 TOP5（兜底） ===")
        game_sales_map: dict = {}
        for row in final_detail:
            name = str(row.get("game", ""))
            if not name or name == "所有游戏（汇总）":
                continue
            sales = float(row.get("sales", 0) or 0)
            game_sales_map[name] = game_sales_map.get(name, 0) + sales

        fb_pub, fb_solo = [], []
        for name, sales in game_sales_map.items():
            entry = {"game": name, "sales": round(sales, 2)}
            (fb_pub if is_publisher_game(name) else fb_solo).append(entry)

        fb_pub.sort(key=lambda x: x["sales"],  reverse=True)
        fb_solo.sort(key=lambda x: x["sales"], reverse=True)
        for i, item in enumerate(fb_pub[:5]):  item["rank"] = i + 1
        for i, item in enumerate(fb_solo[:5]): item["rank"] = i + 1

        log(f"  兜底厂商TOP5 : {[x['game'] for x in fb_pub[:5]]}")
        log(f"  兜底单机TOP5 : {[x['game'] for x in fb_solo[:5]]}")

        if not output["publisher_game_top5"]:
            output["publisher_game_top5"] = fb_pub[:5]
        if not output["solo_game_top5"]:
            output["solo_game_top5"] = fb_solo[:5]

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # ── 存入数据库 & 导出前端缓存 ─────────────────────────────────────────────
    save_to_db(output, yesterday, weekly_weeks)
    export_history_cache()

    elapsed = (datetime.now() - t0).total_seconds()
    total   = sum(len(output[k]) for k in ["daily_sales","detail_table"])

    log("=" * 60)
    log_ok(f"更新完成  数据日期={output['data_date']}（昨日）  耗时 {elapsed:.1f}s")
    log(f"  昨日销售额   : ¥{output['kpi']['today_sales']:,.2f}")
    log(f"  前日销售额   : ¥{output['kpi']['yesterday_sales']:,.2f}")
    log(f"  日环比       : {output['kpi']['growth_rate']:+.2f}%")
    log(f"  昨日流量     : {output['kpi']['total_traffic']:,} UV")
    log(f"  昨日转化率   : {output['kpi']['conversion_rate']:.2f}%")
    log(f"  本月累计     : ¥{output['monthly_total']:,.2f}")
    log(f"  活跃游戏数   : {output['active_games']} 款")
    log(f"  日销记录     : {len(output['daily_sales'])} 条")
    log(f"  单机 TOP5    : {len(output['solo_game_top5'])} 条")
    log(f"  厂商 TOP5    : {len(output['publisher_game_top5'])} 条")
    log(f"  访问 TOP5    : {len(output['game_views_top5'])} 条")
    log(f"  明细表       : {len(output['detail_table'])} 条")
    log(f"  用户行为分布 : {len(output['traffic_source'])} 项")
    log(f"  流量统计字段 : {list(output['traffic_stats'].keys())}")
    log("=" * 60)
    # 打印所有新采集字段，确认写入正确
    ts = output['traffic_stats']
    print("=" * 50)
    print("新增流量统计字段汇总：")
    for k, v in ts.items():
        print(f"  traffic_stats.{k} = {v}")
    print(f"  game_views_top5           = {[r['game'] for r in output['game_views_top5']]}")
    print(f"  game_views_publisher_top5 = {[r['game'] for r in output['game_views_publisher_top5']]}")
    print("=" * 50)


if __name__ == "__main__":
    main()
