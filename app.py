from flask import Flask, render_template, request, send_file
import feedparser
import pandas as pd
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from io import BytesIO

app = Flask(__name__)

KEYWORD_GROUPS = {
    "AI": ["AI", "인공지능", "생성형 AI", "AX", "AI 에이전트", "LLM", "오픈AI", "OpenAI", "구글 AI", "마이크로소프트 AI", "AI 보안"],
    "ERP": ["ERP", "전사적자원관리", "더존비즈온", "영림원", "영림원소프트랩", "SAP", "오라클 ERP", "이카운트", "아이퀘스트"],
    "클라우드": ["클라우드", "SaaS", "AWS", "Azure", "애저", "구글 클라우드", "세일즈포스", "워크데이"],
    "정책/세무": ["과학기술정보통신부", "디지털 전환", "연말정산", "법인세", "부가세", "전자세금계산서", "DX", "중소기업 디지털"]
}

RSS_FEEDS = [
    "https://www.yna.co.kr/rss/all.xml",
    "https://rss.etnews.com/Section901.xml",
    "https://rss.etnews.com/Section902.xml",
    "https://www.itworld.co.kr/rss/feed",
    "https://www.ciokorea.com/rss/feed",
    "https://zdnet.co.kr/news/news_xml.asp",
]


def parse_date(entry):
    for key in ["published", "updated", "created"]:
        if key in entry:
            try:
                return parsedate_to_datetime(entry[key]).replace(tzinfo=None)
            except Exception:
                pass
    return datetime.now()


def classify_title(title):
    matched_groups = []
    matched_keywords = []
    lower_title = title.lower()
    for group, keywords in KEYWORD_GROUPS.items():
        for keyword in keywords:
            if keyword.lower() in lower_title:
                matched_groups.append(group)
                matched_keywords.append(keyword)
    return sorted(set(matched_groups)), sorted(set(matched_keywords))


def collect_news(days=1):
    today = datetime.now().date()
    start_date = today - timedelta(days=max(days, 1) - 1)
    articles = []
    seen = set()

    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            source = feed.feed.get("title", "Unknown")
            for entry in feed.entries:
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                if not title or not link:
                    continue
                published_at = parse_date(entry)
                if published_at.date() < start_date or published_at.date() > today:
                    continue
                groups, keywords = classify_title(title)
                if not groups:
                    continue
                key = (title, link)
                if key in seen:
                    continue
                seen.add(key)
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


def category_counts(articles):
    counts = {key: 0 for key in KEYWORD_GROUPS.keys()}
    for article in articles:
        for category in article["category"].split(", "):
            if category in counts:
                counts[category] += 1
    return counts


@app.route("/")
def index():
    days = int(request.args.get("days", 1))
    articles = collect_news(days=days)
    counts = category_counts(articles)
    return render_template("index.html", articles=articles, counts=counts, total=len(articles), days=days, keywords=KEYWORD_GROUPS)


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
    app.run(host="0.0.0.0", port=8000)
