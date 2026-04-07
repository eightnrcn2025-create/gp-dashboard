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

import os, re, json, time, traceback, requests
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

# Google Sheets
SHEET1_ID  = "1oB5lVRHJ3g80wFpWy4w5yq2XiQ6ytCji1R_bddKOGEk"
SHEET1_GID = "769980440"
SHEET2_ID  = "1Ob7HPc3BRRGGD0ZFC6Yfaf4s0eQhkPPD5Qz0UnxReII"
SHEET2_GID = "866845188"

# Gamepark 后台
ADMIN_HOST  = "https://admin.gamepark.co"
API_BASE    = f"{ADMIN_HOST}/api"
STATS_URL_SOLO = (
    f"{ADMIN_HOST}/?time=1756199148799"
    "#/statistics/game-statistics-more"
    "?statType=payment&gameType=alone&timeFilter=yesterday"
)
STATS_URL_PUBLISHER = (
    f"{ADMIN_HOST}/?time=1756199148799"
    "#/statistics/game-statistics-more"
    "?statType=payment&gameType=publisher&timeFilter=yesterday"
)

# ── 厂商游戏白名单（名称包含以下关键词 → 归为厂商游戏，其余为单机游戏）────────
PUBLISHER_GAMES = [
    "淫乱斗罗", "全明星動漫樂園", "次元色潮", "火影嬌妻村",
    "海王传奇海王篇", "次元少女", "三国：红艳无双", "解禁無雙",
    "火影色欲传", "三国：一统天下", "忍娘24", "口袋觉醒：成人版", "妻龙珠",
]

def is_publisher_game(game_name: str) -> bool:
    """游戏名称包含厂商游戏白名单中的任意关键词则返回 True"""
    return any(kw in game_name for kw in PUBLISHER_GAMES)

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
    try:
        headers = admin_login()
        log_ok("后台 API 登录成功")

        # ── 1. 昨日/前日/本月订单统计（脚本在 0:05 运行，以"昨日"为主数据）────
        stats = api_get(headers, "/admin/orders/stats/recent")
        # 脚本于凌晨运行，API 的 yestoday = 昨日完整数据 = data_date
        result["today_sales"]     = to_num(stats.get("yestoday", {}).get("total_amount", 0))
        result["yesterday_sales"] = to_num(stats.get("today",    {}).get("total_amount", 0))  # 暂存，稍后用 daily_sales[-2] 覆盖
        result["today_orders"]    = int(stats.get("yestoday",    {}).get("total_count", 0))
        result["month_sales"]     = to_num(stats.get("month",    {}).get("total_amount", 0))
        log_ok(f"订单统计 → 昨日¥{result['today_sales']}  (data_date={yesterday})")

        # ── 2. 近30天每日订单（作为 daily_sales 主数据源）───────────────────
        daily_raw = api_get(headers, "/admin/orders/stats/recentDaily", {"period_type": "30d"})
        daily_list = daily_raw.get("daily_list", []) if isinstance(daily_raw, dict) else []
        if daily_list:
            result["daily_sales"] = [
                {"date": row["order_date"], "amount": to_num(row["total_amount"])}
                for row in sorted(daily_list, key=lambda x: x["order_date"])
            ]
            log_ok(f"日销售额 → {len(result['daily_sales'])} 条（近30天）")

        # ── 3. 流量汇总（今日 UV/PV/新注册/活跃/付费用户）───────────────────
        summary_list = api_get(headers, "/admin/platform/userstats/summary",
                                {"started_at": today, "ended_at": today})
        summary = {item["title"]: item.get("today", 0) for item in (summary_list or [])}
        uv            = int(summary.get("uv", 0))
        pv            = int(summary.get("pv", 0))
        new_reg       = int(summary.get("register_new", 0))
        active_users  = int(summary.get("active_user", 0))
        paid_users    = int(summary.get("recharged_count", 0))  # 充值用户数
        result["total_traffic"] = uv
        log_ok(f"流量汇总 → UV={uv}  PV={pv}  新注册={new_reg}  活跃={active_users}  付费={paid_users}")

        # ── 4. 转化率（付费用户 / UV）────────────────────────────────────────
        result["conversion_rate"] = round(result["today_orders"] / uv * 100, 2) if uv > 0 else 0

        # ── 5. 用户行为分布（替代伪造的流量来源）────────────────────────────
        # 数据完全来自后台 API，真实可靠
        browse_only   = max(0, uv - new_reg)
        result["traffic_source"] = [
            {"source": "仅浏览（未注册）", "value": browse_only},
            {"source": "新注册用户",       "value": new_reg},
            {"source": "活跃老用户",       "value": active_users},
            {"source": "付费/充值用户",    "value": paid_users},
        ]
        log_ok(f"用户行为分布 → 仅浏览:{browse_only}  注册:{new_reg}  活跃:{active_users}  付费:{paid_users}")

        return result

    except Exception as e:
        log_err(f"后台 API 失败: {e}\n{traceback.format_exc()}")
        return result


# =============================================================================
# 数据源二：后台 Playwright — 游戏付费排行（game_compare + detail_table）
# =============================================================================
def fetch_admin_game_stats(last):
    log("=== [Playwright] 单机/厂商游戏排行 ===")
    fallback = {
        "solo_game_top5":      last.get("solo_game_top5", []),
        "publisher_game_top5": last.get("publisher_game_top5", []),
        "detail_rows":         last.get("detail_table", []),
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

            page.goto(ADMIN_HOST, wait_until="networkidle", timeout=30000)
            time.sleep(1)
            page.fill('input[type="text"]',     account)
            page.fill('input[type="password"]', password)
            page.click('button:has-text("登录")')
            page.wait_for_load_state("networkidle", timeout=20000)
            time.sleep(2)
            save_shot(page, "login_success")

            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

            def scrape_game_table(url, label):
                """导航到指定排行URL，抓取游戏付费表格数据"""
                page.goto(url, wait_until="networkidle", timeout=30000)
                time.sleep(4)
                save_shot(page, f"data_page_{label}")
                tables = page.query_selector_all("table")
                if len(tables) < 2:
                    log_warn(f"{label}: 仅找到 {len(tables)} 个 table，跳过")
                    return []
                rows = []
                for tr in tables[1].query_selector_all("tr"):
                    cells = tr.query_selector_all("td")
                    if len(cells) < 9:
                        continue
                    game_name = cells[2].inner_text().strip()
                    if not game_name:
                        continue
                    uv      = int(to_num(cells[4].inner_text()))
                    orders  = int(to_num(cells[6].inner_text()))
                    payment = to_num(cells[8].inner_text())
                    rows.append({"game": game_name, "uv": uv, "orders": orders, "payment": payment})
                log_ok(f"{label}: 抓取 {len(rows)} 条")
                return rows

            solo_rows      = scrape_game_table(STATS_URL_SOLO,      "solo")
            publisher_rows = scrape_game_table(STATS_URL_PUBLISHER,  "publisher")

            # 合并两批数据，按游戏名去重（取销售额较高的那条）
            all_games_map = {}
            for r in solo_rows + publisher_rows:
                name = r["game"]
                if name not in all_games_map or r["payment"] > all_games_map[name]["payment"]:
                    all_games_map[name] = r
            all_rows  = list(all_games_map.values())
            game_rows = all_rows  # detail_table 使用全量数据

            browser.close()

        def rows_to_top5(rows):
            sorted_rows = sorted(rows, key=lambda x: x["payment"], reverse=True)
            return [
                {"rank": i + 1, "game": r["game"], "sales": r["payment"], "growth": 0}
                for i, r in enumerate(sorted_rows[:5])
            ]

        # 按 PUBLISHER_GAMES 白名单分类，而非依赖后台 gameType 参数
        solo_pool      = [r for r in all_rows if not is_publisher_game(r["game"])]
        publisher_pool = [r for r in all_rows if     is_publisher_game(r["game"])]

        solo_top5      = rows_to_top5(solo_pool)
        publisher_top5 = rows_to_top5(publisher_pool)
        log_ok(f"分类结果 → 单机 {len(solo_pool)} 款 / 厂商 {len(publisher_pool)} 款")

        detail_rows = [{
            "date":       yesterday,
            "game":       r["game"],
            "traffic":    r["uv"],
            "sales":      r["payment"],
            "conversion": round(r["orders"] / r["uv"] * 100, 2) if r["uv"] > 0 else 0,
        } for r in game_rows]

        log_ok(f"单机 TOP5 → {len(solo_top5)} 条 | 厂商 TOP5 → {len(publisher_top5)} 条")
        return {
            "solo_game_top5":      solo_top5,
            "publisher_game_top5": publisher_top5,
            "detail_rows":         detail_rows,
        }

    except Exception as e:
        log_err(f"Playwright 失败: {e}\n{traceback.format_exc()}")
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
    last = load_last_data()

    # ── 三路采集 ──────────────────────────────────────────────────────────────
    api_data   = fetch_admin_api(last)
    game_data  = fetch_admin_game_stats(last)
    sheet2_det = fetch_sheet2_detail(last)

    # ── 整理日销售数据 ──────────────────────────────────────────────────────
    daily_sales = api_data.get("daily_sales") or last.get("daily_sales", [])

    # ── 计算环比（昨日 vs 前日，两个完整日的对比）───────────────────────────
    # api_data["today_sales"] = API的 yestoday（昨日完整数据）
    # 前日销售 = daily_sales 倒数第二条（昨日之前一天）
    today_sales = api_data["today_sales"]
    if len(daily_sales) >= 2:
        yesterday_sales = daily_sales[-2]["amount"]
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
    solo_game_top5      = game_data.get("solo_game_top5")      or last.get("solo_game_top5", [])
    publisher_game_top5 = game_data.get("publisher_game_top5") or last.get("publisher_game_top5", [])

    # 周环比热力图 = daily_sales（前端JS自动补齐56天格子）
    weekly_heatmap = daily_sales

    # 本月累计销售额 = 后台 API month 字段，兜底用当月 daily_sales 求和
    month_sales = api_data.get("month_sales", 0)
    if not month_sales:
        this_month = (datetime.now() - timedelta(days=1)).strftime("%Y-%m")  # 昨日所在月
        month_sales = round(
            sum(r["amount"] for r in daily_sales if r["date"].startswith(this_month)), 2
        )

    # 活跃游戏数 = solo + publisher 总数
    active_games = len(solo_game_top5) + len(publisher_game_top5)

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
        "daily_sales":          daily_sales,
        "solo_game_top5":       solo_game_top5,
        "publisher_game_top5":  publisher_game_top5,
        "weekly_heatmap":       weekly_heatmap,
        "monthly_total":        month_sales,
        "active_games":         active_games,
        "traffic_source":       api_data.get("traffic_source") or last.get("traffic_source", []),
        "detail_table":         detail_table or last.get("detail_table", []),
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

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
    log(f"  明细表       : {len(output['detail_table'])} 条")
    log(f"  用户行为分布 : {len(output['traffic_source'])} 项")
    log("=" * 60)


if __name__ == "__main__":
    main()
