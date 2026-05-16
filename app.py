import sqlite3
import shutil
from datetime import date, datetime
from pathlib import Path
import calendar

import pandas as pd
import streamlit as st

# ============================================================
# 物品管理アプリ Ver2.1 SQLite安定性強化版
# ・SQLiteリレーショナルDB保存
# ・自動バックアップ / 手動バックアップ
# ・削除確認チェック
# ・数量・単価・在庫マイナス警告
# ・重複登録警告
# ・管理者 / 職員 ログイン
# ============================================================

st.set_page_config(page_title="物品管理アプリ Ver2.1 ", layout="wide")

DATA = Path("data")
DATA.mkdir(exist_ok=True)
DB_PATH = DATA / "buppin_app.db"
BACKUP_DIR = DATA / "backups"
BACKUP_DIR.mkdir(exist_ok=True)

ADMIN_MENUS = [
    "管理ダッシュボード",
    "使用記録 登録",
    "使用記録 検索・更新・削除",
    "現在庫 登録・更新",
    "月間集計",
    "請求書作成",
    "FEED発注候補",
    "利用者マスタ 登録・更新・削除",
    "物品マスタ 登録・更新・削除",
    "ログイン設定",
    "バックアップ管理",
    "データ確認",
]

STAFF_MENUS = [
    "使用記録 登録",
    "使用記録 検索・更新・削除",
]


# ============================================================
# DB共通
# ============================================================

def get_conn():
    return sqlite3.connect(DB_PATH)


def execute(sql, params=()):
    with get_conn() as conn:
        conn.execute(sql, params)
        conn.commit()


def query_df(sql, params=()):
    with get_conn() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def safe_int(v):
    try:
        if pd.isna(v) or v == "":
            return 0
        return int(float(v))
    except Exception:
        return 0


def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def backup_db(reason="manual"):
    """DBをバックアップする。reason: auto / manual"""
    if not DB_PATH.exists():
        return None

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"buppin_app_backup_{reason}_{stamp}.db"
    shutil.copy2(DB_PATH, backup_path)
    return backup_path


def auto_backup_once_per_day():
    """1日1回だけ自動バックアップ"""
    if not DB_PATH.exists():
        return None

    today = date.today().strftime("%Y%m%d")
    existing = list(BACKUP_DIR.glob(f"buppin_app_backup_auto_{today}_*.db"))

    if existing:
        return existing[0]

    return backup_db(reason="auto")


def list_backups():
    files = sorted(BACKUP_DIR.glob("*.db"), reverse=True)
    rows = []
    for f in files:
        rows.append({
            "ファイル名": f.name,
            "サイズKB": round(f.stat().st_size / 1024, 1),
            "作成日時": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "path": str(f),
        })
    return pd.DataFrame(rows)


def init_db():
    with get_conn() as conn:
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                login_id TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL,
                display_name TEXT NOT NULL,
                created_at TEXT,
                updated_at TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_name TEXT UNIQUE NOT NULL,
                billing_name TEXT,
                note TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_name TEXT UNIQUE NOT NULL,
                unit_price INTEGER DEFAULT 0,
                minimum_stock INTEGER DEFAULT 0,
                feed_url TEXT,
                note TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS stock (
                item_id INTEGER PRIMARY KEY,
                current_stock INTEGER DEFAULT 0,
                updated_at TEXT,
                FOREIGN KEY(item_id) REFERENCES items(id)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS usage_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                use_date TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                note TEXT,
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(item_id) REFERENCES items(id)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS dashboard_memos (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                memo TEXT,
                updated_at TEXT
            )
        """)

        cur.execute("SELECT COUNT(*) FROM accounts")
        if cur.fetchone()[0] == 0:
            cur.execute("""
                INSERT INTO accounts (login_id, password, role, display_name, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, ("admin", "admin123", "管理者", "管理者", now_text(), now_text()))
            cur.execute("""
                INSERT INTO accounts (login_id, password, role, display_name, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, ("staff", "staff123", "職員", "職員", now_text(), now_text()))

        cur.execute(
            "INSERT OR IGNORE INTO dashboard_memos (id, memo, updated_at) VALUES (1, '', ?)",
            (now_text(),)
        )

        conn.commit()


def ensure_stock_for_items():
    items = query_df("SELECT id FROM items")
    with get_conn() as conn:
        for _, row in items.iterrows():
            conn.execute("""
                INSERT OR IGNORE INTO stock (item_id, current_stock, updated_at)
                VALUES (?, 0, ?)
            """, (int(row["id"]), now_text()))
        conn.commit()


# ============================================================
# データ取得
# ============================================================

def get_accounts():
    return query_df("""
        SELECT id, login_id AS ログインID, password AS パスワード, role AS 権限, display_name AS 表示名,
               created_at AS 登録日時, updated_at AS 更新日時
        FROM accounts
        ORDER BY id
    """)


def get_users():
    return query_df("""
        SELECT id AS 利用者ID, user_name AS 利用者名, billing_name AS 請求先, note AS 備考,
               created_at AS 登録日時, updated_at AS 更新日時
        FROM users
        ORDER BY user_name
    """)


def get_items():
    return query_df("""
        SELECT id AS 物品ID, item_name AS 物品名, unit_price AS 単価, minimum_stock AS 最低在庫,
               feed_url AS FEED商品URL, note AS 備考, created_at AS 登録日時, updated_at AS 更新日時
        FROM items
        ORDER BY item_name
    """)


def get_stock_view():
    ensure_stock_for_items()
    return query_df("""
        SELECT
            i.id AS 物品ID,
            i.item_name AS 物品,
            COALESCE(s.current_stock, 0) AS 現在庫,
            COALESCE(i.minimum_stock, 0) AS 最低在庫,
            i.unit_price AS 単価,
            i.feed_url AS FEED商品URL,
            s.updated_at AS 更新日時
        FROM items i
        LEFT JOIN stock s ON i.id = s.item_id
        ORDER BY i.item_name
    """)


def get_usage_view():
    return query_df("""
        SELECT
            ul.id AS 記録ID,
            ul.use_date AS 日付,
            u.user_name AS 利用者,
            i.item_name AS 物品,
            ul.quantity AS 数量,
            ul.unit_price AS 単価,
            ul.amount AS 金額,
            ul.note AS 備考,
            ul.created_at AS 登録日時,
            ul.updated_at AS 更新日時,
            ul.user_id AS user_id,
            ul.item_id AS item_id
        FROM usage_logs ul
        JOIN users u ON ul.user_id = u.id
        JOIN items i ON ul.item_id = i.id
        ORDER BY ul.use_date DESC, ul.id DESC
    """)


def make_stock_status():
    df = get_stock_view()
    if df.empty:
        return pd.DataFrame(columns=["状態", "物品", "現在庫", "最低在庫", "不足数", "単価", "FEED商品URL"])

    df["現在庫"] = df["現在庫"].apply(safe_int)
    df["最低在庫"] = df["最低在庫"].apply(safe_int)
    df["不足数"] = df["最低在庫"] - df["現在庫"]

    def status(row):
        current = safe_int(row["現在庫"])
        minimum = safe_int(row["最低在庫"])

        if current <= 0:
            return "🔴 在庫0"
        if current <= minimum:
            return "🔴 発注必要"
        if current <= minimum + max(2, minimum // 2):
            return "🟡 注意"
        return "🟢 OK"

    df["状態"] = df.apply(status, axis=1)
    return df[["状態", "物品ID", "物品", "現在庫", "最低在庫", "不足数", "単価", "FEED商品URL", "更新日時"]]


def month_schedule():
    today = date.today()
    last_day = calendar.monthrange(today.year, today.month)[1]
    return pd.DataFrame([
        {"時期": "月初 1〜5日", "やること": "棚卸・現在庫確認", "目的": "前月のズレを直す", "状態": "今月の土台作り"},
        {"時期": "10日前後", "やること": "中間在庫チェック", "目的": "急な減りに気づく", "状態": "ショート予防"},
        {"時期": "20日前後", "やること": "FEED発注候補確認", "目的": "月末前に不足を防ぐ", "状態": "発注判断"},
        {"時期": f"月末 {last_day}日前後", "やること": "利用者別請求確認", "目的": "月末請求を作成", "状態": "請求処理"},
    ])


def duplicate_usage_exists(use_date, user_id, item_id, exclude_id=None):
    if exclude_id is None:
        df = query_df("""
            SELECT COUNT(*) AS cnt
            FROM usage_logs
            WHERE use_date = ? AND user_id = ? AND item_id = ?
        """, (use_date, user_id, item_id))
    else:
        df = query_df("""
            SELECT COUNT(*) AS cnt
            FROM usage_logs
            WHERE use_date = ? AND user_id = ? AND item_id = ? AND id <> ?
        """, (use_date, user_id, item_id, exclude_id))

    return safe_int(df.iloc[0]["cnt"]) > 0


def get_current_stock(item_id):
    df = query_df("SELECT current_stock FROM stock WHERE item_id = ?", (item_id,))
    if df.empty:
        return 0
    return safe_int(df.iloc[0]["current_stock"])


def usage_warnings(use_date, user_id, item_id, qty, unit_price, exclude_id=None):
    warnings = []

    if qty >= 20:
        warnings.append(f"数量が多めです（{qty}）。入力ミスでないか確認してください。")

    if unit_price <= 0:
        warnings.append("単価が0円です。請求対象外でよいか確認してください。")

    current_stock = get_current_stock(item_id)
    if current_stock - qty < 0:
        warnings.append(f"在庫がマイナスになります。現在庫：{current_stock}、使用数：{qty}")

    if duplicate_usage_exists(use_date, user_id, item_id, exclude_id=exclude_id):
        warnings.append("同じ日付・同じ利用者・同じ物品の記録がすでにあります。重複登録でないか確認してください。")

    return warnings


# ============================================================
# ログイン
# ============================================================

def login_screen():
    st.title("📦 物品管理アプリ Ver2.1 SQLite安定性強化版")
    st.subheader("ログイン")

    with st.form("login_form"):
        login_id = st.text_input("ログインID")
        password = st.text_input("パスワード", type="password")
        ok = st.form_submit_button("ログイン")

    if ok:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT login_id, password, role, display_name
                FROM accounts
                WHERE login_id = ? AND password = ?
            """, (login_id, password))
            row = cur.fetchone()

        if row:
            st.session_state["logged_in"] = True
            st.session_state["login_id"] = row[0]
            st.session_state["role"] = row[2]
            st.session_state["user_name"] = row[3]
            st.success("ログインしました。")
            st.rerun()
        else:
            st.error("ログインIDまたはパスワードが違います。")

    st.info("初期設定：管理者 admin / admin123　職員 staff / staff123")


def require_login():
    if "logged_in" not in st.session_state:
        st.session_state["logged_in"] = False

    if not st.session_state["logged_in"]:
        login_screen()
        st.stop()


def logout_button():
    with st.sidebar:
        st.markdown("---")
        st.write(f"ログイン：{st.session_state.get('user_name', '')}")
        st.write(f"権限：{st.session_state.get('role', '')}")
        if st.button("ログアウト"):
            st.session_state.clear()
            st.rerun()


# ============================================================
# 初期化
# ============================================================
init_db()
auto_backup_once_per_day()
require_login()

st.title("📦 物品管理アプリ Ver2.1 SQLite安定性強化版")
st.caption("自動バックアップ／手動バックアップ／削除確認／入力ミス警告／SQLiteリレーショナルDB")

role = st.session_state.get("role", "職員")
available_menus = ADMIN_MENUS if role == "管理者" else STAFF_MENUS

menu = st.sidebar.radio("メニュー", available_menus)
logout_button()


# ============================================================
# 管理ダッシュボード
# ============================================================
if menu == "管理ダッシュボード":
    st.subheader("📋 物品担当 管理ダッシュボード")

    users = get_users()
    items = get_items()
    usage = get_usage_view()
    stock_status = make_stock_status()

    total_items = len(items)
    stock_zero = len(stock_status[stock_status["状態"] == "🔴 在庫0"]) if not stock_status.empty else 0
    order_needed = len(stock_status[stock_status["状態"] == "🔴 発注必要"]) if not stock_status.empty else 0

    if not usage.empty:
        usage["日付_dt"] = pd.to_datetime(usage["日付"], errors="coerce")
        this_month = date.today().strftime("%Y-%m")
        month_usage = usage[usage["日付_dt"].dt.strftime("%Y-%m") == this_month].copy()
        month_usage["金額"] = month_usage["金額"].apply(safe_int)
        month_total = int(month_usage["金額"].sum())
    else:
        month_usage = pd.DataFrame()
        month_total = 0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("登録物品数", f"{total_items}件")
    col2.metric("在庫0", f"{stock_zero}件")
    col3.metric("発注必要", f"{order_needed}件")
    col4.metric("今月物品費", f"{month_total:,}円")

    st.markdown("---")

    if st.button("手動バックアップを作成"):
        path = backup_db(reason="manual")
        if path:
            st.success(f"バックアップを作成しました：{path.name}")
        else:
            st.error("DBファイルが見つかりません。")

    left, right = st.columns([1.3, 1])

    with left:
        st.markdown("### 🔴 発注・注意が必要な物品")
        if stock_status.empty:
            st.info("物品マスタと在庫を登録してください。")
        else:
            alert = stock_status[stock_status["状態"].isin(["🔴 在庫0", "🔴 発注必要", "🟡 注意"])].copy()
            if alert.empty:
                st.success("現在、在庫ショートの注意物品はありません。")
            else:
                st.dataframe(alert[["状態", "物品", "現在庫", "最低在庫", "不足数", "FEED商品URL"]], use_container_width=True)

                st.markdown("#### FEED商品ページ")
                for _, r in alert.iterrows():
                    url = str(r.get("FEED商品URL", "")).strip()
                    if url.startswith("http"):
                        st.link_button(f"{r['物品']} を開く", url)

    with right:
        st.markdown("### 🗓 月間注文スケジュール")
        st.dataframe(month_schedule(), use_container_width=True, hide_index=True)

    st.markdown("---")
    c1, c2 = st.columns(2)

    with c1:
        st.markdown("### 📊 今月の物品別使用量")
        if month_usage.empty:
            st.info("今月の使用記録はまだありません。")
        else:
            item_summary = month_usage.groupby("物品")[["数量", "金額"]].sum().reset_index()
            st.dataframe(item_summary.sort_values("数量", ascending=False), use_container_width=True)

    with c2:
        st.markdown("### 👤 今月の利用者別物品費")
        if month_usage.empty:
            st.info("今月の使用記録はまだありません。")
        else:
            user_summary = month_usage.groupby("利用者")[["金額"]].sum().reset_index()
            st.dataframe(user_summary.sort_values("金額", ascending=False), use_container_width=True)

    st.markdown("---")
    st.markdown("### 📝 物品担当メモ・申し送り")

    memo_df = query_df("SELECT memo FROM dashboard_memos WHERE id = 1")
    memo = memo_df.iloc[0]["memo"] if not memo_df.empty else ""
    new_memo = st.text_area("次回発注予定日、注意物品、申し送りなどを記録できます。", value=memo, height=180)

    if st.button("担当メモを保存"):
        execute("UPDATE dashboard_memos SET memo = ?, updated_at = ? WHERE id = 1", (new_memo, now_text()))
        st.success("担当メモを保存しました。")


# ============================================================
# 使用記録 登録
# ============================================================
elif menu == "使用記録 登録":
    st.subheader("使用記録 登録")

    users = get_users()
    items = get_items()

    if users.empty:
        st.warning("先に利用者マスタを登録してください。")
    elif items.empty:
        st.warning("先に物品マスタを登録してください。")
    else:
        user_map = dict(zip(users["利用者名"], users["利用者ID"]))
        item_map = dict(zip(items["物品名"], items["物品ID"]))

        with st.form("usage_create"):
            d = st.date_input("日付", date.today())
            user_name = st.selectbox("利用者", list(user_map.keys()))
            item_name = st.selectbox("物品", list(item_map.keys()))
            qty = st.number_input("数量", min_value=1, max_value=9999, value=1)
            note = st.text_input("備考")

            item_row = items[items["物品名"] == item_name].iloc[0]
            price = safe_int(item_row["単価"])
            amount = qty * price

            st.write(f"単価：{price:,}円")
            st.write(f"金額：{amount:,}円")

            user_id = int(user_map[user_name])
            item_id = int(item_map[item_name])
            warn_list = usage_warnings(d.strftime("%Y-%m-%d"), user_id, item_id, qty, price)

            if warn_list:
                for w in warn_list:
                    st.warning(w)
                confirm_warning = st.checkbox("警告内容を確認しました。この内容で登録します。")
            else:
                confirm_warning = True

            ok = st.form_submit_button("登録する")

        if ok:
            if warn_list and not confirm_warning:
                st.error("警告があるため、確認チェックを入れてから登録してください。")
                st.stop()

            with get_conn() as conn:
                conn.execute("""
                    INSERT INTO usage_logs
                    (use_date, user_id, item_id, quantity, unit_price, amount, note, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (d.strftime("%Y-%m-%d"), user_id, item_id, qty, price, amount, note, now_text(), now_text()))

                conn.execute("""
                    INSERT OR IGNORE INTO stock (item_id, current_stock, updated_at)
                    VALUES (?, 0, ?)
                """, (item_id, now_text()))

                conn.execute("""
                    UPDATE stock
                    SET current_stock = COALESCE(current_stock, 0) - ?, updated_at = ?
                    WHERE item_id = ?
                """, (qty, now_text(), item_id))

                conn.commit()

            st.success("使用記録を登録しました。在庫も減算しました。")
            st.rerun()


# ============================================================
# 使用記録 検索・更新・削除
# ============================================================
elif menu == "使用記録 検索・更新・削除":
    st.subheader("使用記録 検索・更新・削除")

    usage = get_usage_view()
    users = get_users()
    items = get_items()

    if usage.empty:
        st.info("使用記録がありません。")
    else:
        work = usage.copy()
        work["日付_dt"] = pd.to_datetime(work["日付"], errors="coerce")

        col1, col2, col3 = st.columns(3)
        keyword = col1.text_input("検索語（利用者・物品・備考）")
        year = col2.number_input("年", 2024, 2035, date.today().year)
        month = col3.number_input("月", 1, 12, date.today().month)

        filtered = work[work["日付_dt"].dt.strftime("%Y-%m") == f"{year}-{month:02d}"].copy()

        if keyword:
            filtered = filtered[
                filtered["利用者"].astype(str).str.contains(keyword, na=False) |
                filtered["物品"].astype(str).str.contains(keyword, na=False) |
                filtered["備考"].astype(str).str.contains(keyword, na=False)
            ]

        st.dataframe(filtered[["記録ID", "日付", "利用者", "物品", "数量", "単価", "金額", "備考", "登録日時", "更新日時"]], use_container_width=True)

        if not filtered.empty:
            selected_id = st.selectbox("更新・削除する記録ID", filtered["記録ID"].astype(int))
            row = usage[usage["記録ID"].astype(int) == int(selected_id)].iloc[0]

            user_map = dict(zip(users["利用者名"], users["利用者ID"]))
            item_map = dict(zip(items["物品名"], items["物品ID"]))
            user_list = list(user_map.keys())
            item_list = list(item_map.keys())

            with st.form("usage_edit"):
                new_date = st.date_input("日付", pd.to_datetime(row["日付"]).date())

                new_user_name = st.selectbox(
                    "利用者",
                    user_list,
                    index=user_list.index(str(row["利用者"])) if str(row["利用者"]) in user_list else 0
                )

                new_item_name = st.selectbox(
                    "物品",
                    item_list,
                    index=item_list.index(str(row["物品"])) if str(row["物品"]) in item_list else 0
                )

                new_qty = st.number_input("数量", min_value=1, max_value=9999, value=max(1, safe_int(row["数量"])))
                new_note = st.text_input("備考", str(row.get("備考", "")))

                new_user_id = int(user_map[new_user_name])
                new_item_id = int(item_map[new_item_name])
                item_row = items[items["物品ID"].astype(int) == new_item_id].iloc[0]
                new_price = safe_int(item_row["単価"])
                warn_list = usage_warnings(
                    new_date.strftime("%Y-%m-%d"),
                    new_user_id,
                    new_item_id,
                    new_qty,
                    new_price,
                    exclude_id=int(selected_id)
                )

                if warn_list:
                    for w in warn_list:
                        st.warning(w)
                    confirm_warning = st.checkbox("警告内容を確認しました。この内容で更新します。")
                else:
                    confirm_warning = True

                st.markdown("#### 削除する場合の確認")
                delete_confirm = st.checkbox("この使用記録を削除することを確認しました。")
                delete_text = st.text_input("削除する場合は DELETE と入力")

                c1, c2 = st.columns(2)
                update = c1.form_submit_button("更新する")
                delete = c2.form_submit_button("削除する")

            if update:
                if warn_list and not confirm_warning:
                    st.error("警告があるため、確認チェックを入れてから更新してください。")
                    st.stop()

                amount = new_qty * new_price

                execute("""
                    UPDATE usage_logs
                    SET use_date = ?, user_id = ?, item_id = ?, quantity = ?, unit_price = ?, amount = ?, note = ?, updated_at = ?
                    WHERE id = ?
                """, (
                    new_date.strftime("%Y-%m-%d"), new_user_id, new_item_id,
                    new_qty, new_price, amount, new_note, now_text(), int(selected_id)
                ))

                st.success("使用記録を更新しました。※在庫は必要に応じて現在庫画面で調整してください。")
                st.rerun()

            if delete:
                if not delete_confirm or delete_text != "DELETE":
                    st.error("削除するには確認チェックを入れ、DELETE と入力してください。")
                    st.stop()

                execute("DELETE FROM usage_logs WHERE id = ?", (int(selected_id),))
                st.success("使用記録を削除しました。※在庫は必要に応じて現在庫画面で調整してください。")
                st.rerun()


# ============================================================
# 現在庫 登録・更新
# ============================================================
elif menu == "現在庫 登録・更新":
    st.subheader("現在庫 登録・更新")

    ensure_stock_for_items()
    stock_status = make_stock_status()

    if not stock_status.empty:
        st.markdown("### 在庫状況")
        st.dataframe(stock_status[["状態", "物品", "現在庫", "最低在庫", "不足数", "更新日時"]], use_container_width=True)
    else:
        st.info("物品マスタを登録してください。")

    if not stock_status.empty:
        item_map = dict(zip(stock_status["物品"], stock_status["物品ID"]))

        st.markdown("### 入庫・棚卸修正")
        with st.form("stock_update"):
            item_name = st.selectbox("物品", list(item_map.keys()))
            mode = st.radio("処理", ["入庫として加算", "実在庫数に修正"])
            qty = st.number_input("数量", min_value=0, max_value=99999, value=1)

            if qty >= 100:
                st.warning("数量が多めです。入力ミスでないか確認してください。")
                confirm_large_qty = st.checkbox("数量を確認しました。")
            else:
                confirm_large_qty = True

            ok = st.form_submit_button("在庫を更新する")

        if ok:
            if not confirm_large_qty:
                st.error("数量確認チェックを入れてください。")
                st.stop()

            item_id = int(item_map[item_name])
            if mode == "入庫として加算":
                execute("""
                    UPDATE stock
                    SET current_stock = COALESCE(current_stock, 0) + ?, updated_at = ?
                    WHERE item_id = ?
                """, (qty, now_text(), item_id))
            else:
                execute("""
                    UPDATE stock
                    SET current_stock = ?, updated_at = ?
                    WHERE item_id = ?
                """, (qty, now_text(), item_id))

            st.success("在庫を更新しました。")
            st.rerun()


# ============================================================
# 月間集計
# ============================================================
elif menu == "月間集計":
    st.subheader("月間集計")

    usage = get_usage_view()

    if usage.empty:
        st.info("使用記録がありません。")
    else:
        usage["日付_dt"] = pd.to_datetime(usage["日付"], errors="coerce")
        ym = st.selectbox("対象月", sorted(usage["日付_dt"].dt.strftime("%Y-%m").dropna().unique(), reverse=True))

        target = usage[usage["日付_dt"].dt.strftime("%Y-%m") == ym].copy()

        st.markdown("### 利用者別合計")
        st.dataframe(target.groupby("利用者")[["金額"]].sum().reset_index(), use_container_width=True)

        st.markdown("### 物品別合計")
        st.dataframe(target.groupby("物品")[["数量", "金額"]].sum().reset_index(), use_container_width=True)

        st.markdown("### 利用者別・物品別")
        st.dataframe(target.groupby(["利用者", "物品"])[["数量", "金額"]].sum().reset_index(), use_container_width=True)


# ============================================================
# 請求書作成
# ============================================================
elif menu == "請求書作成":
    st.subheader("請求書作成")

    usage = get_usage_view()

    if usage.empty:
        st.info("使用記録がありません。")
    else:
        usage["日付_dt"] = pd.to_datetime(usage["日付"], errors="coerce")
        ym = st.selectbox("請求月", sorted(usage["日付_dt"].dt.strftime("%Y-%m").dropna().unique(), reverse=True))
        user = st.selectbox("利用者", sorted(usage["利用者"].dropna().astype(str).unique()))

        target = usage[
            (usage["日付_dt"].dt.strftime("%Y-%m") == ym) &
            (usage["利用者"].astype(str) == str(user))
        ].copy()

        bill = target.groupby("物品")[["数量", "金額"]].sum().reset_index()
        total = int(bill["金額"].sum()) if not bill.empty else 0

        st.dataframe(bill, use_container_width=True)
        st.markdown(f"## 合計：{total:,}円")

        text = f"請求書\n\n対象月：{ym}\n利用者：{user}\n\n"
        for _, r in bill.iterrows():
            text += f"{r['物品']}　数量：{int(r['数量'])}　金額：{int(r['金額']):,}円\n"
        text += f"\n合計：{total:,}円"

        st.text_area("請求書本文", text, height=300)
        st.download_button("請求書をダウンロード", text, file_name=f"invoice_{user}_{ym}.txt", mime="text/plain")


# ============================================================
# FEED発注候補
# ============================================================
elif menu == "FEED発注候補":
    st.subheader("FEED発注候補")

    stock_status = make_stock_status()

    if stock_status.empty:
        st.info("物品マスタと在庫データを登録してください。")
    else:
        order = stock_status[stock_status["状態"].isin(["🔴 在庫0", "🔴 発注必要", "🟡 注意"])].copy()

        if order.empty:
            st.success("現在、発注候補はありません。")
        else:
            st.warning("発注確認が必要な物品があります。")
            show = order[["状態", "物品", "現在庫", "最低在庫", "不足数", "単価", "FEED商品URL"]]
            st.dataframe(show, use_container_width=True)

            st.markdown("### FEED商品ページ")
            for _, r in order.iterrows():
                url = str(r.get("FEED商品URL", "")).strip()
                if url.startswith("http"):
                    st.link_button(f"{r['物品']} の商品ページを開く", url)

            csv = show.to_csv(index=False).encode("utf-8-sig")
            st.download_button("発注候補CSVをダウンロード", csv, file_name="feed_order_candidates.csv", mime="text/csv")


# ============================================================
# 利用者マスタ CRUD
# ============================================================
elif menu == "利用者マスタ 登録・更新・削除":
    st.subheader("利用者マスタ 登録・更新・削除")

    st.markdown("### 登録")
    with st.form("user_create"):
        name = st.text_input("利用者名")
        billing = st.text_input("請求先")
        note = st.text_input("備考")
        ok = st.form_submit_button("登録する")

    if ok:
        if not name.strip():
            st.error("利用者名を入力してください。")
        else:
            try:
                execute("""
                    INSERT INTO users (user_name, billing_name, note, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (name.strip(), billing.strip(), note.strip(), now_text(), now_text()))
                st.success("利用者を登録しました。")
                st.rerun()
            except sqlite3.IntegrityError:
                st.error("同じ利用者名がすでに登録されています。")

    st.markdown("### 検索・更新・削除")
    keyword = st.text_input("検索語（利用者名・請求先）", key="user_search")
    users = get_users()

    filtered = users.copy()
    if keyword:
        filtered = filtered[
            filtered["利用者名"].astype(str).str.contains(keyword, na=False) |
            filtered["請求先"].astype(str).str.contains(keyword, na=False)
        ]

    st.dataframe(filtered, use_container_width=True)

    if not filtered.empty:
        selected = st.selectbox("更新・削除する利用者ID", filtered["利用者ID"].astype(int))
        row = users[users["利用者ID"].astype(int) == int(selected)].iloc[0]

        with st.form("user_edit"):
            new_name = st.text_input("利用者名", str(row["利用者名"]))
            new_billing = st.text_input("請求先", str(row["請求先"]))
            new_note = st.text_input("備考", str(row["備考"]))

            st.markdown("#### 削除する場合の確認")
            delete_confirm = st.checkbox("この利用者を削除することを確認しました。")
            delete_text = st.text_input("削除する場合は DELETE と入力")

            c1, c2 = st.columns(2)
            update = c1.form_submit_button("更新する")
            delete = c2.form_submit_button("削除する")

        if update:
            if not new_name.strip():
                st.error("利用者名は空欄にできません。")
                st.stop()

            try:
                execute("""
                    UPDATE users
                    SET user_name = ?, billing_name = ?, note = ?, updated_at = ?
                    WHERE id = ?
                """, (new_name.strip(), new_billing.strip(), new_note.strip(), now_text(), int(selected)))
                st.success("利用者を更新しました。")
                st.rerun()
            except sqlite3.IntegrityError:
                st.error("同じ利用者名がすでに登録されています。")

        if delete:
            if not delete_confirm or delete_text != "DELETE":
                st.error("削除するには確認チェックを入れ、DELETE と入力してください。")
                st.stop()

            count = query_df("SELECT COUNT(*) AS cnt FROM usage_logs WHERE user_id = ?", (int(selected),)).iloc[0]["cnt"]
            if int(count) > 0:
                st.error("使用記録に使われている利用者は削除できません。")
            else:
                execute("DELETE FROM users WHERE id = ?", (int(selected),))
                st.success("利用者を削除しました。")
                st.rerun()


# ============================================================
# 物品マスタ CRUD
# ============================================================
elif menu == "物品マスタ 登録・更新・削除":
    st.subheader("物品マスタ 登録・更新・削除")

    st.markdown("### 登録")
    with st.form("item_create"):
        name = st.text_input("物品名")
        price = st.number_input("単価", min_value=0, max_value=999999, value=0)
        min_stock = st.number_input("最低在庫", min_value=0, max_value=99999, value=0)
        url = st.text_input("FEED商品URL")
        note = st.text_input("備考")

        if price <= 0:
            st.warning("単価が0円です。請求対象外でよいか確認してください。")
            confirm_zero_price = st.checkbox("単価0円で登録することを確認しました。")
        else:
            confirm_zero_price = True

        ok = st.form_submit_button("登録する")

    if ok:
        if not name.strip():
            st.error("物品名を入力してください。")
        elif not confirm_zero_price:
            st.error("単価0円の確認チェックを入れてください。")
        else:
            try:
                with get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute("""
                        INSERT INTO items (item_name, unit_price, minimum_stock, feed_url, note, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (name.strip(), price, min_stock, url.strip(), note.strip(), now_text(), now_text()))
                    item_id = cur.lastrowid
                    cur.execute("""
                        INSERT INTO stock (item_id, current_stock, updated_at)
                        VALUES (?, 0, ?)
                    """, (item_id, now_text()))
                    conn.commit()

                st.success("物品を登録しました。")
                st.rerun()
            except sqlite3.IntegrityError:
                st.error("同じ物品名がすでに登録されています。")

    st.markdown("### 検索・更新・削除")
    keyword = st.text_input("検索語（物品名・URL・備考）", key="item_search")
    items = get_items()

    filtered = items.copy()
    if keyword:
        filtered = filtered[
            filtered["物品名"].astype(str).str.contains(keyword, na=False) |
            filtered["FEED商品URL"].astype(str).str.contains(keyword, na=False) |
            filtered["備考"].astype(str).str.contains(keyword, na=False)
        ]

    st.dataframe(filtered, use_container_width=True)

    if not filtered.empty:
        selected = st.selectbox("更新・削除する物品ID", filtered["物品ID"].astype(int))
        row = items[items["物品ID"].astype(int) == int(selected)].iloc[0]

        with st.form("item_edit"):
            new_name = st.text_input("物品名", str(row["物品名"]))
            new_price = st.number_input("単価", min_value=0, max_value=999999, value=safe_int(row["単価"]))
            new_min = st.number_input("最低在庫", min_value=0, max_value=99999, value=safe_int(row["最低在庫"]))
            new_url = st.text_input("FEED商品URL", str(row["FEED商品URL"]))
            new_note = st.text_input("備考", str(row["備考"]))

            if new_price <= 0:
                st.warning("単価が0円です。請求対象外でよいか確認してください。")
                confirm_zero_price_edit = st.checkbox("単価0円で更新することを確認しました。")
            else:
                confirm_zero_price_edit = True

            st.markdown("#### 削除する場合の確認")
            delete_confirm = st.checkbox("この物品を削除することを確認しました。")
            delete_text = st.text_input("削除する場合は DELETE と入力")

            c1, c2 = st.columns(2)
            update = c1.form_submit_button("更新する")
            delete = c2.form_submit_button("削除する")

        if update:
            if not new_name.strip():
                st.error("物品名は空欄にできません。")
                st.stop()

            if not confirm_zero_price_edit:
                st.error("単価0円の確認チェックを入れてください。")
                st.stop()

            try:
                execute("""
                    UPDATE items
                    SET item_name = ?, unit_price = ?, minimum_stock = ?, feed_url = ?, note = ?, updated_at = ?
                    WHERE id = ?
                """, (new_name.strip(), new_price, new_min, new_url.strip(), new_note.strip(), now_text(), int(selected)))
                ensure_stock_for_items()
                st.success("物品を更新しました。")
                st.rerun()
            except sqlite3.IntegrityError:
                st.error("同じ物品名がすでに登録されています。")

        if delete:
            if not delete_confirm or delete_text != "DELETE":
                st.error("削除するには確認チェックを入れ、DELETE と入力してください。")
                st.stop()

            count = query_df("SELECT COUNT(*) AS cnt FROM usage_logs WHERE item_id = ?", (int(selected),)).iloc[0]["cnt"]
            if int(count) > 0:
                st.error("使用記録に使われている物品は削除できません。")
            else:
                execute("DELETE FROM stock WHERE item_id = ?", (int(selected),))
                execute("DELETE FROM items WHERE id = ?", (int(selected),))
                st.success("物品を削除しました。")
                st.rerun()


# ============================================================
# ログイン設定
# ============================================================
elif menu == "ログイン設定":
    st.subheader("ログイン設定")

    if st.session_state.get("role") != "管理者":
        st.error("このメニューは管理者のみ使用できます。")
        st.stop()

    accounts = get_accounts()

    st.markdown("### 現在のログイン一覧")
    safe_view = accounts.copy()
    safe_view["パスワード"] = "********"
    st.dataframe(safe_view, use_container_width=True)

    st.markdown("---")
    st.markdown("### 新規アカウント追加")

    with st.form("account_create"):
        new_id = st.text_input("ログインID")
        new_pw = st.text_input("パスワード", type="password")
        new_role = st.selectbox("権限", ["職員", "管理者"])
        new_name = st.text_input("表示名")
        create_ok = st.form_submit_button("追加する")

    if create_ok:
        if not new_id.strip() or not new_pw.strip():
            st.error("ログインIDとパスワードを入力してください。")
        else:
            try:
                execute("""
                    INSERT INTO accounts (login_id, password, role, display_name, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    new_id.strip(),
                    new_pw.strip(),
                    new_role,
                    new_name.strip() if new_name.strip() else new_id.strip(),
                    now_text(),
                    now_text()
                ))
                st.success("アカウントを追加しました。")
                st.rerun()
            except sqlite3.IntegrityError:
                st.error("同じログインIDがすでに存在します。")

    st.markdown("---")
    st.markdown("### パスワード・権限の変更 / 削除")

    accounts = get_accounts()

    if accounts.empty:
        st.info("アカウントがありません。")
    else:
        selected = st.selectbox("変更するアカウントID", accounts["id"].astype(int))
        row = accounts[accounts["id"].astype(int) == int(selected)].iloc[0]

        with st.form("account_edit"):
            st.text_input("ログインID", str(row["ログインID"]), disabled=True)
            edit_pw = st.text_input("新しいパスワード", value=str(row["パスワード"]), type="password")
            edit_role = st.selectbox("権限", ["職員", "管理者"], index=0 if str(row["権限"]) == "職員" else 1)
            edit_name = st.text_input("表示名", str(row["表示名"]))

            st.markdown("#### 削除する場合の確認")
            delete_confirm = st.checkbox("このアカウントを削除することを確認しました。")
            delete_text = st.text_input("削除する場合は DELETE と入力")

            c1, c2 = st.columns(2)
            update_ok = c1.form_submit_button("更新する")
            delete_ok = c2.form_submit_button("削除する")

        if update_ok:
            if not edit_pw.strip():
                st.error("パスワードは空欄にできません。")
                st.stop()

            execute("""
                UPDATE accounts
                SET password = ?, role = ?, display_name = ?, updated_at = ?
                WHERE id = ?
            """, (edit_pw.strip(), edit_role, edit_name.strip(), now_text(), int(selected)))
            st.success("ログイン情報を更新しました。")
            st.rerun()

        if delete_ok:
            if not delete_confirm or delete_text != "DELETE":
                st.error("削除するには確認チェックを入れ、DELETE と入力してください。")
                st.stop()

            admin_count = query_df("SELECT COUNT(*) AS cnt FROM accounts WHERE role = '管理者'").iloc[0]["cnt"]
            target_role = str(row["権限"])

            if str(row["ログインID"]) == st.session_state.get("login_id"):
                st.error("現在ログイン中の自分自身は削除できません。")
            elif target_role == "管理者" and int(admin_count) <= 1:
                st.error("管理者が0人になるため削除できません。")
            else:
                execute("DELETE FROM accounts WHERE id = ?", (int(selected),))
                st.success("アカウントを削除しました。")
                st.rerun()

    st.warning("注意：このVer2.1ではパスワードはSQLiteに平文保存です。施設内の簡易テスト向けです。")


# ============================================================
# バックアップ管理
# ============================================================
elif menu == "バックアップ管理":
    st.subheader("バックアップ管理")
    st.caption("DBの自動バックアップ・手動バックアップ・ダウンロードを行います。")

    if st.button("手動バックアップを作成する"):
        path = backup_db(reason="manual")
        if path:
            st.success(f"バックアップを作成しました：{path.name}")
        else:
            st.error("DBファイルが見つかりません。")

    st.markdown("### バックアップ一覧")
    backups = list_backups()

    if backups.empty:
        st.info("バックアップはまだありません。")
    else:
        st.dataframe(backups.drop(columns=["path"]), use_container_width=True)

        selected_name = st.selectbox("ダウンロードするバックアップ", backups["ファイル名"].tolist())
        selected_path = backups[backups["ファイル名"] == selected_name].iloc[0]["path"]

        with open(selected_path, "rb") as f:
            st.download_button(
                "選択したバックアップDBをダウンロード",
                f.read(),
                file_name=selected_name,
                mime="application/octet-stream"
            )

    st.info("自動バックアップはアプリ起動時に1日1回作成されます。保存先は data/backups/ です。")


# ============================================================
# データ確認
# ============================================================
elif menu == "データ確認":
    st.subheader("データ確認")

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["利用者", "物品", "使用記録", "在庫", "ログイン"])

    with tab1:
        df = get_users()
        st.dataframe(df, use_container_width=True)
        st.download_button("利用者CSV", df.to_csv(index=False).encode("utf-8-sig"), "users.csv", "text/csv")

    with tab2:
        df = get_items()
        st.dataframe(df, use_container_width=True)
        st.download_button("物品CSV", df.to_csv(index=False).encode("utf-8-sig"), "items.csv", "text/csv")

    with tab3:
        df = get_usage_view()
        st.dataframe(df.drop(columns=["user_id", "item_id"], errors="ignore"), use_container_width=True)
        st.download_button("使用記録CSV", df.to_csv(index=False).encode("utf-8-sig"), "usage.csv", "text/csv")

    with tab4:
        df = get_stock_view()
        st.dataframe(df, use_container_width=True)
        st.download_button("在庫CSV", df.to_csv(index=False).encode("utf-8-sig"), "stock.csv", "text/csv")

    with tab5:
        df = get_accounts()
        masked = df.copy()
        masked["パスワード"] = "********"
        st.dataframe(masked, use_container_width=True)
