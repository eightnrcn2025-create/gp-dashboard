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
# 全游戏付费排行（昨日，gameType 留空 = 全部，用 PUBLISHER_GAMES 白名单再分类）
STATS_URL_PAYMENT_ALL = (
    f"{ADMIN_HOST}/?time=1756199148799"
    "#/statistics/game-statistics-more"
    "?statType=payment&gameType=&timeFilter=yesterday"
)
# 全游戏付费排行（近7天，厂商游戏无昨日数据时兜底）
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
        result["pv"]            = pv
        result["new_reg"]       = new_reg
        result["active_users"]  = active_users
        result["paid_users"]    = paid_users
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

            def scrape_game_table(url, label):
                """抓取游戏统计表格，col2=游戏名 col4=主指标 col6=次指标 col8=金额"""
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
                    if len(cells) < 5:
                        continue
                    game_name = cells[2].inner_text().strip()
                    if not game_name:
                        continue
                    col4 = to_num(cells[4].inner_text())
                    col6 = to_num(cells[6].inner_text()) if len(cells) > 6 else 0
                    col8 = to_num(cells[8].inner_text()) if len(cells) > 8 else 0
                    rows.append({
                        "game": game_name,
                        "uv":      int(col4),
                        "orders":  int(col6),
                        "payment": col8,
                    })
                log_ok(f"{label}: 抓取 {len(rows)} 条")
                return rows

            # ── 1. 昨日全游戏付费排行（gameType 留空 = 全部游戏）────────────
            payment_rows = scrape_game_table(STATS_URL_PAYMENT_ALL, "payment_all")
            log(f"原始付费数据共 {len(payment_rows)} 条游戏：")
            for r in payment_rows:
                print(f"原始游戏数据：{r['game']} | 销售额：{r['payment']}")

            # ── 2. 按 PUBLISHER_GAMES 白名单分类，打印每条结果 ───────────────
            log("--- 游戏分类明细 ---")
            solo_pool      = []
            publisher_pool = []
            for r in payment_rows:
                is_pub = is_publisher_game(r["game"])
                print(f"→ {'厂商游戏' if is_pub else '单机游戏'}: {r['game']}")
                if is_pub:
                    publisher_pool.append(r)
                else:
                    solo_pool.append(r)

            # ── 3. 若昨日无厂商游戏，改用7天数据兜底 ────────────────────────
            if not publisher_pool:
                log_warn("昨日无厂商游戏销售数据，改用近7天数据兜底...")
                rows_7d = scrape_game_table(STATS_URL_PAYMENT_7D, "payment_7d")
                existing_names = {r["game"] for r in payment_rows}
                for r in rows_7d:
                    if is_publisher_game(r["game"]) and r["game"] not in existing_names:
                        log(f"  [7天补充·厂商] {r['game']}  ¥{r['payment']}")
                        publisher_pool.append(r)
                log_ok(f"7天兜底后 → 厂商 {len(publisher_pool)} 款")

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

            solo_top5      = rows_to_top5(solo_pool)
            publisher_top5 = rows_to_top5(publisher_pool)

            log_ok(f"分类结果 → 单机 {len(solo_pool)} 款 / 厂商 {len(publisher_pool)} 款")
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

        return {
            "solo_game_top5":            solo_top5,
            "publisher_game_top5":       publisher_top5,
            "game_views_top5":           game_views_top5,
            "game_views_publisher_top5": game_views_publisher_top5,
            "detail_rows":               detail_rows,
            "flow_stats":                flow_stats,
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
    flow_stats    = game_data.get("flow_stats", {})
    uv            = api_data.get("total_traffic", 0)
    pv_val        = api_data.get("pv", 0)
    new_reg       = api_data.get("new_reg", 0)
    active_users  = api_data.get("active_users", 0)
    paid_users    = api_data.get("paid_users", 0)
    today_orders  = api_data.get("today_orders", 0)

    traffic_stats = {
        "pv":              int(flow_stats.get("pv",             pv_val)),
        "uv":              int(flow_stats.get("uv",             uv)),
        "ip":              int(flow_stats.get("ip",             0)),
        "bounce_rate":     flow_stats.get("bounce_rate",        ""),
        "avg_duration":    flow_stats.get("avg_duration",       ""),
        "total_users":     int(flow_stats.get("total_users",    0)),
        "new_users":       int(flow_stats.get("new_users",      new_reg)),
        "active_users":    int(flow_stats.get("active_users",   active_users)),
        "paying_users":    int(flow_stats.get("paying_users",   paid_users)),
        "payment_amount":  round(float(flow_stats.get("payment_amount", today_sales)), 2),
        "order_count":     int(flow_stats.get("order_count",    today_orders)),
        "order_amount":    round(float(flow_stats.get("order_amount",  today_sales)), 2),
        "arpu":            round(float(flow_stats.get("arpu",
                               today_sales / active_users if active_users else 0)), 2),
        "avg_order_value": round(float(flow_stats.get("avg_order_value",
                               today_sales / today_orders if today_orders else 0)), 2),
    }
    log_ok(f"流量统计汇总 → UV={traffic_stats['uv']}  PV={traffic_stats['pv']}"
           f"  新注册={traffic_stats['new_users']}  付费={traffic_stats['paying_users']}"
           f"  ARPU=¥{traffic_stats['arpu']}  客单价=¥{traffic_stats['avg_order_value']}")

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
