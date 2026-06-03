import requests
from flask import Flask, render_template, request, send_file, redirect, url_for
import feedparser
import pandas as pd
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from io import BytesIO
import json
import os
from urllib.parse import urlparse
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "AhZRpvAwa4Hcm3fa38Id")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "PsxFLPct3g")

app = Flask(__name__)

DATA_DIR = "/app/user_data"
KEYWORDS_FILE = os.path.join(DATA_DIR, "keywords.json")

DEFAULT_KEYWORD_GROUPS = {
    "AI": ["AI", "인공지능", "생성형 AI", "AX", "AI 에이전트", "에이전틱 AI", "LLM", "sLLM", "RAG", "오픈AI", "OpenAI", "구글 AI", "마이크로소프트 AI", "AI 보안", "AI 거버넌스", "AI 기본법", "온디바이스 AI"],
    "ERP": ["ERP", "전사적자원관리", "더존비즈온", "영림원", "영림원소프트랩", "K-System", "SystemEver", "시스템에버", "SAP", "오라클 ERP", "클라우드 ERP", "이카운트", "아이퀘스트"],
    "클라우드": ["클라우드", "SaaS", "PaaS", "IaaS", "AWS", "Azure", "애저", "구글 클라우드", "네이버클라우드", "NHN클라우드", "세일즈포스", "워크데이"],
    "정책/세무": ["과학기술정보통신부", "과기정통부", "중소벤처기업부", "디지털 전환", "DX", "개인정보보호위원회", "개인정보보호법", "연말정산", "법인세", "부가세", "전자세금계산서", "중소기업 디지털"]
}

DOMAIN_SOURCE_MAP = {
    "yna.co.kr": "연합뉴스",
    "etnews.com": "전자신문",
    "zdnet.co.kr": "ZDNet Korea",
    "itworld.co.kr": "ITWorld Korea",
    "ciokorea.com": "CIO Korea",
}

RSS_FEEDS = [
    "https://www.yna.co.kr/rss/all.xml",
    "https://rss.etnews.com/Section901.xml",
    "https://rss.etnews.com/Section902.xml",
    "https://www.itworld.co.kr/rss/feed",
    "https://www.ciokorea.com/rss/feed",
    "https://zdnet.co.kr/news/news_xml.asp",
]


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def load_keywords():
    ensure_data_dir()
    if not os.path.exists(KEYWORDS_FILE):
        save_keywords(DEFAULT_KEYWORD_GROUPS)
        return {k: v[:] for k, v in DEFAULT_KEYWORD_GROUPS.items()}
    try:
        with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {k: v[:] for k, v in DEFAULT_KEYWORD_GROUPS.items()}
        return data
    except Exception:
        return {k: v[:] for k, v in DEFAULT_KEYWORD_GROUPS.items()}


def save_keywords(keyword_groups):
    ensure_data_dir()
    with open(KEYWORDS_FILE, "w", encoding="utf-8") as f:
        json.dump(keyword_groups, f, ensure_ascii=False, indent=2)


def parse_date(entry):
    for key in ["published", "updated", "created"]:
        if key in entry:
            try:
                return parsedate_to_datetime(entry[key]).replace(tzinfo=None)
            except Exception:
                pass
    return datetime.now()


def get_source_name(entry, feed, link):

    try:
        domain = urlparse(link).netloc.lower().replace("www.", "")

        for key, name in DOMAIN_SOURCE_MAP.items():
            if key in domain:
                return name

        return domain

    except Exception:
        return "Unknown"
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

def search_naver_news(query, display=10):
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        return []

    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    params = {
        "query": query,
        "display": display,
        "sort": "date",
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        return response.json().get("items", [])
    except Exception as e:
        print(f"네이버 뉴스 검색 오류: {query} - {e}")
        return []

def collect_news(days=1):
    keyword_groups = load_keywords()
    today = datetime.now().date()
    start_date = today - timedelta(days=max(days, 1) - 1)
    articles = []
    seen_links = set()
    seen_titles = set()

    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                if not title or not link:
                    continue
                published_at = parse_date(entry)
                if published_at.date() < start_date or published_at.date() > today:
                    continue
                groups, keywords = classify_title(title, keyword_groups)
                if not groups:
                    continue
                if link in seen_links or title in seen_titles:
                    continue
                seen_links.add(link)
                seen_titles.add(title)
                source = get_source_name(entry, feed, link)
                articles.append({
                    "category": ", ".join(groups),
                    "title": title,
                    "source": source,
                    "published_at": published_at.strftime("%Y-%m-%d %H:%M"),
                    "matched_keywords": ", ".join(keywords),
                    "summary": f"{', '.join(groups)} 관련 기사입니다. 주요 키워드: {', '.join(keywords)}",
                    "link": link,
                })
        except Exception as e:
            print(f"RSS 수집 오류: {feed_url} - {e}")

    articles.sort(key=lambda x: x["published_at"], reverse=True)
    return articles

    # 네이버 뉴스 검색 API 수집
    max_per_keyword = 10

    all_keywords = [15]
    for group, keywords in keyword_groups.items():
        for keyword in keywords:
            if keyword not in all_keywords:
                all_keywords.append(keyword)

    for keyword in all_keywords:
        try:
            naver_items = search_naver_news(keyword, display=max_per_keyword)

            for item in naver_items:
                title = clean_html(item.get("title", "")).strip()
                link = item.get("originallink") or item.get("link", "")
                description = clean_html(item.get("description", "")).strip()
                published_at = parse_naver_date(item.get("pubDate", ""))

                if not title or not link:
                    continue

                if published_at.date() < start_date or published_at.date() > today:
                    continue

                groups, matched_keywords = classify_title(title, keyword_groups)

                if not groups:
                    groups = []
                    for group_name, group_keywords in keyword_groups.items():
                        if keyword in group_keywords:
                            groups.append(group_name)
                            break

                if not matched_keywords:
                    matched_keywords = [keyword]

                if link in seen_links or title in seen_titles:
                    continue

                seen_links.add(link)
                seen_titles.add(title)

                source = get_source_name({}, {}, link)

                articles.append({
                    "category": ", ".join(groups),
                    "title": title,
                    "source": source,
                    "published_at": published_at.strftime("%Y-%m-%d %H:%M"),
                    "matched_keywords": ", ".join(matched_keywords),
                    "summary": description if description else f"{', '.join(groups)} 관련 기사입니다. 주요 키워드: {', '.join(matched_keywords)}",
                    "link": link,
                })

        except Exception as e:
            print(f"네이버 뉴스 처리 오류: {keyword} - {e}")

def category_counts(articles, keyword_groups):
    counts = {key: 0 for key in keyword_groups.keys()}
    for article in articles:
        for category in article["category"].split(", "):
            if category in counts:
                counts[category] += 1
    return counts


@app.route("/")
def index():
    days = int(request.args.get("days", 1))
    keyword_groups = load_keywords()
    articles = collect_news(days=days)
    counts = category_counts(articles, keyword_groups)
    return render_template("index.html", articles=articles, counts=counts, total=len(articles), days=days, keywords=keyword_groups)


@app.post("/keywords/add")
def add_keyword():
    group = request.form.get("group", "").strip()
    keyword = request.form.get("keyword", "").strip()
    days = request.form.get("days", 1)
    keyword_groups = load_keywords()
    if group and keyword:
        keyword_groups.setdefault(group, [])
        if keyword not in keyword_groups[group]:
            keyword_groups[group].append(keyword)
            keyword_groups[group] = sorted(keyword_groups[group])
            save_keywords(keyword_groups)
    return redirect(url_for("index", days=days))


@app.post("/keywords/delete")
def delete_keyword():
    group = request.form.get("group", "").strip()
    keyword = request.form.get("keyword", "").strip()
    days = request.form.get("days", 1)
    keyword_groups = load_keywords()
    if group in keyword_groups and keyword in keyword_groups[group]:
        keyword_groups[group].remove(keyword)
        save_keywords(keyword_groups)
    return redirect(url_for("index", days=days))


@app.post("/categories/add")
def add_category():
    group = request.form.get("group", "").strip()
    days = request.form.get("days", 1)
    keyword_groups = load_keywords()
    if group and group not in keyword_groups:
        keyword_groups[group] = []
        save_keywords(keyword_groups)
    return redirect(url_for("index", days=days))


@app.route("/download")
def download():
    days = int(request.args.get("days", 1))
    articles = collect_news(days=days)
    df = pd.DataFrame(articles)
    columns = {
        "category": "카테고리",
        "title": "기사제목",
        "source": "언론사",
        "published_at": "날짜",
        "matched_keywords": "매칭 키워드",
        "summary": "실무용 요약",
        "link": "링크",
    }
    if df.empty:
        df = pd.DataFrame(columns=list(columns.values()))
    else:
        df = df.rename(columns=columns)[list(columns.values())]

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="뉴스모니터링")
        ws = writer.sheets["뉴스모니터링"]
        for col, width in {"A": 15, "B": 55, "C": 25, "D": 20, "E": 30, "F": 70, "G": 90}.items():
            ws.column_dimensions[col].width = width
    output.seek(0)
    filename = f"news_monitoring_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return send_file(output, as_attachment=True, download_name=filename, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/health")
def health():
    return {"status": "ok", "service": "news-monitoring"}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
