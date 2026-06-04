import csv
import io
import json
import os
import sqlite3
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from functools import wraps
from html import unescape
from urllib.parse import urlparse

import feedparser
import pandas as pd
import requests
from flask import Flask, Response, flash, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")

DATA_DIR = "/app/user_data"
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "business_management.sqlite3")
KEYWORDS_FILE = os.path.join(DATA_DIR, "keywords.json")

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin1234")

DEFAULT_KEYWORD_GROUPS = {
    "AI": ["AI", "인공지능", "생성형 AI", "AX", "AI 에이전트", "LLM", "RAG", "오픈AI", "OpenAI", "AI 보안", "AI 거버넌스", "AI 기본법"],
    "ERP": ["ERP", "전사적자원관리", "더존비즈온", "영림원", "K-System", "SystemEver", "SAP", "오라클 ERP", "클라우드 ERP", "이카운트"],
    "클라우드": ["클라우드", "SaaS", "PaaS", "IaaS", "AWS", "Azure", "구글 클라우드", "네이버클라우드", "NHN클라우드"],
    "정책/세무": ["과학기술정보통신부", "중소벤처기업부", "디지털 전환", "개인정보보호위원회", "개인정보보호법", "연말정산", "법인세", "부가세"]
}

DOMAIN_SOURCE_MAP = {
    "yna.co.kr": "연합뉴스",
    "etnews.com": "전자신문",
    "zdnet.co.kr": "ZDNet Korea",
    "itworld.co.kr": "ITWorld Korea",
    "ciokorea.com": "CIO Korea",
    "mk.co.kr": "매일경제",
    "hankyung.com": "한국경제",
    "fnnews.com": "파이낸셜뉴스",
    "dt.co.kr": "디지털타임스",
    "edaily.co.kr": "이데일리",
    "bloter.net": "블로터",
}

RSS_FEEDS = [
    "https://www.yna.co.kr/rss/all.xml",
    "https://rss.etnews.com/Section901.xml",
    "https://rss.etnews.com/Section902.xml",
    "https://www.itworld.co.kr/rss/feed",
    "https://www.ciokorea.com/rss/feed",
    "https://zdnet.co.kr/news/news_xml.asp",
]


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def execute(sql, params=()):
    with db() as conn:
        conn.execute(sql, params)
        conn.commit()


def fetch_all(sql, params=()):
    with db() as conn:
        return conn.execute(sql, params).fetchall()


def fetch_one(sql, params=()):
    with db() as conn:
        return conn.execute(sql, params).fetchone()


def init_db():
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS news_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            source TEXT,
            url TEXT,
            category TEXT,
            importance TEXT DEFAULT '보통',
            business_summary TEXT,
            impact_note TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS exam_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            school TEXT NOT NULL,
            exam_name TEXT NOT NULL,
            module TEXT NOT NULL,
            total INTEGER DEFAULT 0,
            passed INTEGER DEFAULT 0,
            exam_date TEXT,
            memo TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS privacy_docs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            source TEXT,
            doc_date TEXT,
            url TEXT,
            summary TEXT,
            action_note TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS consultations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            school TEXT NOT NULL,
            contact_name TEXT,
            contact_phone TEXT,
            topic TEXT NOT NULL,
            consult_date TEXT,
            next_action TEXT,
            due_date TEXT,
            status TEXT DEFAULT '진행중',
            memo TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS support_programs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            agency TEXT,
            deadline TEXT,
            owner TEXT,
            status TEXT DEFAULT '검토중',
            url TEXT,
            memo TEXT,
            created_at TEXT NOT NULL
        );
        """)
        existing = conn.execute("SELECT id FROM users WHERE username=?", (ADMIN_USERNAME,)).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,?,?)",
                (ADMIN_USERNAME, generate_password_hash(ADMIN_PASSWORD), "admin", now())
            )
        conn.commit()


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today():
    return datetime.now().strftime("%Y-%m-%d")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def load_keywords():
    if not os.path.exists(KEYWORDS_FILE):
        save_keywords(DEFAULT_KEYWORD_GROUPS)
        return {k: v[:] for k, v in DEFAULT_KEYWORD_GROUPS.items()}
    try:
        with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {k: v[:] for k, v in DEFAULT_KEYWORD_GROUPS.items()}
    except Exception:
        return {k: v[:] for k, v in DEFAULT_KEYWORD_GROUPS.items()}


def save_keywords(keyword_groups):
    with open(KEYWORDS_FILE, "w", encoding="utf-8") as f:
        json.dump(keyword_groups, f, ensure_ascii=False, indent=2)


def clean_html(text):
    return unescape(str(text).replace("<b>", "").replace("</b>", "").replace("&quot;", '"'))


def parse_date(entry):
    for key in ["published", "updated", "created"]:
        if key in entry:
            try:
                return parsedate_to_datetime(entry[key]).replace(tzinfo=None)
            except Exception:
                pass
    return datetime.now()


def get_source_name(link):
    try:
        domain = urlparse(link).netloc.lower().replace("www.", "")
        for key, name in DOMAIN_SOURCE_MAP.items():
            if key in domain:
                return name
        return domain or "Unknown"
    except Exception:
        return "Unknown"


def classify_title(title, keyword_groups):
    matched_groups = []
    matched_keywords = []
    lower_title = title.lower()
    for group, keywords in keyword_groups.items():
        for keyword in keywords:
            if str(keyword).lower() in lower_title:
                matched_groups.append(group)
                matched_keywords.append(keyword)
    return sorted(set(matched_groups)), sorted(set(matched_keywords))


def collect_news(days=1):
    keyword_groups = load_keywords()
    today_date = datetime.now().date()
    start_date = today_date - timedelta(days=max(days, 1) - 1)
    articles = []
    seen_links = set()
    seen_titles = set()

    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                title = clean_html(entry.get("title", "")).strip()
                link = entry.get("link", "").strip()
                if not title or not link:
                    continue
                published_at = parse_date(entry)
                if published_at.date() < start_date or published_at.date() > today_date:
                    continue
                groups, keywords = classify_title(title, keyword_groups)
                if not groups or link in seen_links or title in seen_titles:
                    continue
                seen_links.add(link)
                seen_titles.add(title)
                articles.append({
                    "category": ", ".join(groups),
                    "title": title,
                    "source": get_source_name(link),
                    "published_at": published_at.strftime("%Y-%m-%d %H:%M"),
                    "matched_keywords": ", ".join(keywords),
                    "summary": f"{', '.join(groups)} 관련 기사입니다. 주요 키워드: {', '.join(keywords)}",
                    "link": link,
                })
        except Exception as e:
            print(f"RSS 수집 오류: {feed_url} - {e}")

    articles.sort(key=lambda x: x["published_at"], reverse=True)
    return articles


def category_counts(articles, keyword_groups):
    counts = {key: 0 for key in keyword_groups.keys()}
    for article in articles:
        for category in article["category"].split(", "):
            if category in counts:
                counts[category] += 1
    return counts


def pass_rate(row):
    total = int(row["total"] or 0)
    passed = int(row["passed"] or 0)
    return round((passed / total) * 100, 1) if total else 0


@app.context_processor
def inject_globals():
    return {"active_user": session.get("username"), "today": today()}


@app.route("/login", methods=["GET", "POST"])
def login():
    init_db()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = fetch_one("SELECT * FROM users WHERE username=?", (username,))
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            return redirect(url_for("dashboard"))
        flash("아이디 또는 비밀번호가 올바르지 않습니다.")
    return render_template("index.html", page="login")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    init_db()
    days = int(request.args.get("days", 1))
    articles = collect_news(days=days)
    keyword_groups = load_keywords()
    counts = category_counts(articles, keyword_groups)
    metrics = {
        "news": len(articles),
        "exams": fetch_one("SELECT COUNT(*) c FROM exam_results")["c"],
        "privacy": fetch_one("SELECT COUNT(*) c FROM privacy_docs")["c"],
        "consulting": fetch_one("SELECT COUNT(*) c FROM consultations WHERE status!='완료'")["c"],
        "support": fetch_one("SELECT COUNT(*) c FROM support_programs WHERE status!='완료'")["c"],
    }
    upcoming = fetch_all("SELECT * FROM support_programs WHERE deadline IS NOT NULL AND deadline!='' ORDER BY deadline ASC LIMIT 5")
    consultations = fetch_all("SELECT * FROM consultations ORDER BY COALESCE(due_date, consult_date) DESC LIMIT 5")
    return render_template("index.html", page="dashboard", articles=articles[:10], counts=counts, total=len(articles), days=days, keywords=keyword_groups, metrics=metrics, upcoming=upcoming, consultations=consultations)


@app.route("/news")
@login_required
def news():
    days = int(request.args.get("days", 1))
    keyword_groups = load_keywords()
    articles = collect_news(days=days)
    counts = category_counts(articles, keyword_groups)
    notes = fetch_all("SELECT * FROM news_notes ORDER BY id DESC LIMIT 50")
    return render_template("index.html", page="news", articles=articles, counts=counts, total=len(articles), days=days, keywords=keyword_groups, notes=notes)


@app.post("/news/save")
@login_required
def save_news():
    execute("""INSERT INTO news_notes(title,source,url,category,importance,business_summary,impact_note,created_at)
               VALUES(?,?,?,?,?,?,?,?)""", (
        request.form.get("title"), request.form.get("source"), request.form.get("url"), request.form.get("category"),
        request.form.get("importance", "보통"), request.form.get("business_summary"), request.form.get("impact_note"), now()
    ))
    return redirect(url_for("news", days=request.form.get("days", 1)))


@app.route("/exams", methods=["GET", "POST"])
@login_required
def exams():
    if request.method == "POST":
        execute("""INSERT INTO exam_results(school,exam_name,module,total,passed,exam_date,memo,created_at)
                   VALUES(?,?,?,?,?,?,?,?)""", (
            request.form.get("school"), request.form.get("exam_name"), request.form.get("module"), int(request.form.get("total") or 0),
            int(request.form.get("passed") or 0), request.form.get("exam_date"), request.form.get("memo"), now()
        ))
        return redirect(url_for("exams"))
    rows = fetch_all("SELECT * FROM exam_results ORDER BY exam_date DESC, id DESC")
    chart = [{"module": r["module"], "school": r["school"], "rate": pass_rate(r), "total": r["total"]} for r in rows]
    return render_template("index.html", page="exams", rows=rows, chart=json.dumps(chart, ensure_ascii=False))


@app.post("/exams/upload")
@login_required
def exams_upload():
    file = request.files.get("file")
    if not file:
        flash("엑셀 파일을 선택해 주세요.")
        return redirect(url_for("exams"))
    try:
        df = pd.read_excel(file)
        required = ["학교", "시험명", "모듈", "응시자", "합격자"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            flash("필수 컬럼이 없습니다: " + ", ".join(missing))
            return redirect(url_for("exams"))
        for _, row in df.iterrows():
            execute("""INSERT INTO exam_results(school,exam_name,module,total,passed,exam_date,memo,created_at)
                       VALUES(?,?,?,?,?,?,?,?)""", (
                str(row.get("학교", "")), str(row.get("시험명", "")), str(row.get("모듈", "")), int(row.get("응시자", 0) or 0),
                int(row.get("합격자", 0) or 0), str(row.get("시험일", "")), str(row.get("메모", "")), now()
            ))
        flash("엑셀 데이터를 등록했습니다.")
    except Exception as e:
        flash(f"업로드 실패: {e}")
    return redirect(url_for("exams"))


@app.route("/privacy", methods=["GET", "POST"])
@login_required
def privacy():
    if request.method == "POST":
        execute("""INSERT INTO privacy_docs(title,source,doc_date,url,summary,action_note,created_at)
                   VALUES(?,?,?,?,?,?,?)""", (
            request.form.get("title"), request.form.get("source"), request.form.get("doc_date"), request.form.get("url"),
            request.form.get("summary"), request.form.get("action_note"), now()
        ))
        return redirect(url_for("privacy"))
    rows = fetch_all("SELECT * FROM privacy_docs ORDER BY doc_date DESC, id DESC")
    return render_template("index.html", page="privacy", rows=rows)


@app.route("/consultations", methods=["GET", "POST"])
@login_required
def consultations():
    if request.method == "POST":
        execute("""INSERT INTO consultations(school,contact_name,contact_phone,topic,consult_date,next_action,due_date,status,memo,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""", (
            request.form.get("school"), request.form.get("contact_name"), request.form.get("contact_phone"), request.form.get("topic"),
            request.form.get("consult_date"), request.form.get("next_action"), request.form.get("due_date"), request.form.get("status"), request.form.get("memo"), now()
        ))
        return redirect(url_for("consultations"))
    rows = fetch_all("SELECT * FROM consultations ORDER BY COALESCE(due_date, consult_date) DESC, id DESC")
    return render_template("index.html", page="consultations", rows=rows)


@app.route("/support", methods=["GET", "POST"])
@login_required
def support():
    if request.method == "POST":
        execute("""INSERT INTO support_programs(title,agency,deadline,owner,status,url,memo,created_at)
                   VALUES(?,?,?,?,?,?,?,?)""", (
            request.form.get("title"), request.form.get("agency"), request.form.get("deadline"), request.form.get("owner"),
            request.form.get("status"), request.form.get("url"), request.form.get("memo"), now()
        ))
        return redirect(url_for("support"))
    rows = fetch_all("SELECT * FROM support_programs ORDER BY deadline ASC, id DESC")
    return render_template("index.html", page="support", rows=rows)


@app.post("/keywords/add")
@login_required
def add_keyword():
    group = request.form.get("group", "").strip()
    keyword = request.form.get("keyword", "").strip()
    keyword_groups = load_keywords()
    if group and keyword:
        keyword_groups.setdefault(group, [])
        if keyword not in keyword_groups[group]:
            keyword_groups[group].append(keyword)
            keyword_groups[group] = sorted(keyword_groups[group])
            save_keywords(keyword_groups)
    return redirect(url_for("news", days=request.form.get("days", 1)))


@app.post("/keywords/delete")
@login_required
def delete_keyword():
    group = request.form.get("group", "").strip()
    keyword = request.form.get("keyword", "").strip()
    keyword_groups = load_keywords()
    if group in keyword_groups and keyword in keyword_groups[group]:
        keyword_groups[group].remove(keyword)
        save_keywords(keyword_groups)
    return redirect(url_for("news", days=request.form.get("days", 1)))


@app.post("/categories/add")
@login_required
def add_category():
    group = request.form.get("group", "").strip()
    keyword_groups = load_keywords()
    if group and group not in keyword_groups:
        keyword_groups[group] = []
        save_keywords(keyword_groups)
    return redirect(url_for("news", days=request.form.get("days", 1)))


@app.route("/download/news")
@login_required
def download_news():
    articles = collect_news(days=int(request.args.get("days", 1)))
    df = pd.DataFrame(articles)
    columns = {"category": "카테고리", "title": "기사제목", "source": "언론사", "published_at": "날짜", "matched_keywords": "매칭 키워드", "summary": "실무용 요약", "link": "링크"}
    df = pd.DataFrame(columns=list(columns.values())) if df.empty else df.rename(columns=columns)[list(columns.values())]
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="뉴스모니터링")
    output.seek(0)
    return send_file(output, as_attachment=True, download_name=f"news_monitoring_{datetime.now().strftime('%Y%m%d')}.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/export/<kind>")
@login_required
def export_csv(kind):
    table_map = {
        "exams": "exam_results", "privacy": "privacy_docs", "consultations": "consultations", "support": "support_programs", "news_notes": "news_notes"
    }
    table = table_map.get(kind)
    if not table:
        return "Not found", 404
    rows = fetch_all(f"SELECT * FROM {table} ORDER BY id DESC")
    output = io.StringIO()
    if rows:
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))
    return Response(output.getvalue(), mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": f"attachment; filename={kind}.csv"})


@app.route("/health")
def health():
    return {"status": "ok", "service": "integrated-business-management"}


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
