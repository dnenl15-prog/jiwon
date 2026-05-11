import os
import re
import html
import json
import hashlib
import requests
import smtplib
import xml.etree.ElementTree as ET

from urllib.parse import quote_plus
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta, timezone


FROM_EMAIL = os.environ["FROM_EMAIL"]
APP_PASSWORD = os.environ["APP_PASSWORD"]

TO_EMAIL = [
    "jiwon.baek@gsretail.com",
    "icebell2@naver.com",
]

KEYWORDS = ["보험", "신한", "GA"]
MAX_ARTICLES = 50
REQUEST_TIMEOUT = 20
SENT_FILE = "sent_articles.json"


def build_google_news_rss_url() -> str:
    query = "(" + " OR ".join(KEYWORDS) + ") when:1d"
    encoded_query = quote_plus(query)
    return f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"


def strip_html_tags(text: str) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_title(title: str) -> str:
    title = title.lower()
    title = re.sub(r"[^가-힣a-z0-9 ]", "", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title


def article_key(article: dict) -> str:
    title = normalize_title(article.get("title", ""))
    url = article.get("url", "")
    raw = title or url
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def load_sent_keys() -> set:
    if not os.path.exists(SENT_FILE):
        return set()

    try:
        with open(SENT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data.get("sent_keys", []))
    except Exception:
        return set()


def save_sent_keys(sent_keys: set) -> None:
    data = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "sent_keys": list(sent_keys)[-2000:],
    }

    with open(SENT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def contains_keyword(text: str) -> bool:
    if not text:
        return False

    upper_text = text.upper()

    for keyword in KEYWORDS:
        if keyword == "GA":
            if re.search(r"\bGA\b", upper_text):
                return True
        else:
            if keyword in text:
                return True

    return False


def keyword_score(text: str) -> int:
    score = 0
    upper_text = text.upper()

    for keyword in KEYWORDS:
        if keyword == "GA":
            if re.search(r"\bGA\b", upper_text):
                score += 3
        elif keyword in text:
            score += 3

    important_words = [
        "금감원", "금융위", "보험사", "생명보험", "손해보험",
        "신한라이프", "KB라이프", "삼성생명", "한화생명",
        "제도", "규제", "실적", "인수", "합병", "판매", "상품",
        "암보험", "건강보험", "간병보험", "종신보험"
    ]

    for word in important_words:
        if word in text:
            score += 1

    return score


def parse_rss_items(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    channel = root.find("channel")
    if channel is None:
        return []

    items = []

    for item in channel.findall("item"):
        title = item.findtext("title", default="").strip()
        link = item.findtext("link", default="").strip()
        description = item.findtext("description", default="").strip()
        pub_date = item.findtext("pubDate", default="").strip()

        items.append({
            "title": title,
            "url": link,
            "description": strip_html_tags(description),
            "published_at": pub_date,
        })

    return items


def filter_articles(items: list[dict]) -> list[dict]:
    sent_keys = load_sent_keys()

    filtered = []
    seen_urls = set()
    seen_titles = set()

    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(days=1)

    for item in items:
        title = item.get("title", "")
        description = item.get("description", "")
        url = item.get("url", "")
        published_at = item.get("published_at", "")

        if not title or not url:
            continue

        combined_text = f"{title} {description}"

        if not contains_keyword(combined_text):
            continue

        key = article_key(item)
        if key in sent_keys:
            continue

        normalized = normalize_title(title)

        if url in seen_urls:
            continue

        if normalized in seen_titles:
            continue

        if published_at:
            try:
                published_dt = parsedate_to_datetime(published_at)
                if published_dt.tzinfo is None:
                    published_dt = published_dt.replace(tzinfo=timezone.utc)

                if published_dt < cutoff:
                    continue
            except Exception:
                pass

        item["score"] = keyword_score(combined_text)

        seen_urls.add(url)
        seen_titles.add(normalized)
        filtered.append(item)

    filtered.sort(key=lambda x: x.get("score", 0), reverse=True)

    final_articles = filtered[:MAX_ARTICLES]

    for article in final_articles:
        sent_keys.add(article_key(article))

    save_sent_keys(sent_keys)

    return final_articles


def get_news() -> list[dict]:
    url = build_google_news_rss_url()
    response = requests.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    items = parse_rss_items(response.text)
    return filter_articles(items)


def make_body(articles: list[dict]) -> str:
    today = datetime.now().strftime("%Y-%m-%d")

    text = f"[{today}] 관심 키워드 중요 뉴스 50개\n\n"
    text += f"키워드: {', '.join(KEYWORDS)}\n"
    text += f"발송 기사 수: {len(articles)}개\n\n"

    if not articles:
        text += "새로 보낼 관련 기사가 없습니다."
        return text

    for i, article in enumerate(articles, 1):
        title = article.get("title", "제목 없음")
        url = article.get("url", "")
        published_at = article.get("published_at", "")
        score = article.get("score", 0)

        text += f"{i}. {title}\n"
        text += f"중요도 점수: {score}\n"
        if published_at:
            text += f"발행일: {published_at}\n"
        text += f"{url}\n\n"

    return text


def send_mail(body: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = "오늘의 보험/신한/GA 중요 뉴스"
    msg["From"] = FROM_EMAIL
    msg["To"] = ", ".join(TO_EMAIL)
    msg.set_content(body)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(FROM_EMAIL, APP_PASSWORD)
        smtp.send_message(msg)


if __name__ == "__main__":
    articles = get_news()
    body = make_body(articles)
    send_mail(body)
