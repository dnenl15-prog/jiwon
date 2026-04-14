import os
import re
import html
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

REQUEST_TIMEOUT = 20


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

        clean_description = strip_html_tags(description)

        items.append({
            "title": title,
            "url": link,
            "description": clean_description,
            "published_at": pub_date,
        })

    return items


def contains_keyword(text: str) -> bool:
    if not text:
        return False

    upper_text = text.upper()

    for keyword in KEYWORDS:
        if keyword == "GA":
            if "GA" in upper_text:
                return True
        else:
            if keyword in text:
                return True

    return False


def normalize_title(title: str) -> str:
    title = title.lower()
    title = re.sub(r"[^가-힣a-z0-9 ]", "", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title


def filter_articles(items: list[dict]) -> list[dict]:
    filtered = []
    seen_urls = set()
    seen_titles = set()

    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(days=2)

    for item in items:
        title = item.get("title", "")
        description = item.get("description", "")
        url = item.get("url", "")
        published_at = item.get("published_at", "")

        if not url:
            continue

        if url in seen_urls:
            continue

        combined_text = f"{title} {description}"

        if not contains_keyword(combined_text):
            continue

        normalized = normalize_title(title)
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

        seen_urls.add(url)
        seen_titles.add(normalized)
        filtered.append(item)

    return filtered


def get_news() -> list[dict]:
    url = build_google_news_rss_url()

    response = requests.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    items = parse_rss_items(response.text)
    return filter_articles(items)


def make_body(articles: list[dict]) -> str:
    today = datetime.now().strftime("%Y-%m-%d")

    text = f"[{today}] 관심 키워드 뉴스\n\n"
    text += f"키워드: {', '.join(KEYWORDS)}\n\n"

    if not articles:
        text += "오늘은 관련 기사가 없습니다."
        return text

    for i, article in enumerate(articles, 1):
        title = article.get("title", "제목 없음")
        url = article.get("url", "")
        published_at = article.get("published_at", "")

        text += f"{i}. {title}\n"
        if published_at:
            text += f"발행일: {published_at}\n"
        text += f"{url}\n\n"

    return text


def send_mail(body: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = "오늘의 보험/신한/GA 뉴스"
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
