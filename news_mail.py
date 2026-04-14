import os
import requests
import smtplib
from email.message import EmailMessage
from datetime import datetime

NEWS_API_KEY = os.environ["NEWS_API_KEY"]

KEYWORDS = ["보험", "신한", "GA"]

FROM_EMAIL = os.environ["FROM_EMAIL"]
APP_PASSWORD = os.environ["APP_PASSWORD"]
TO_EMAIL = [
    "jiwon.baek@gsretail.com",
    "icebell2@naver.com",
]


def get_news():
    query = " OR ".join(KEYWORDS)
    url = "https://newsapi.org/v2/everything"

    params = {
        "q": query,
        "language": "ko",
        "sortBy": "publishedAt",
        "pageSize": 10,
        "apiKey": NEWS_API_KEY,
    }

    response = requests.get(url, params=params, timeout=20)
    response.raise_for_status()
    data = response.json()

    return data.get("articles", [])


def make_body(articles):
    today = datetime.now().strftime("%Y-%m-%d")
    text = f"[{today}] 관심 키워드 뉴스\n\n"
    text += f"키워드: {', '.join(KEYWORDS)}\n\n"

    if not articles:
        text += "오늘은 관련 기사가 없습니다."
        return text

    for i, article in enumerate(articles, 1):
        title = article.get("title", "제목 없음")
        url = article.get("url", "")
        published_at = article.get("publishedAt", "")

        text += f"{i}. {title}\n"
        if published_at:
            text += f"발행일: {published_at}\n"
        text += f"{url}\n\n"

    return text


def send_mail(body):
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
