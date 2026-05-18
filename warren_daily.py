#!/usr/bin/env python3
"""
Warren Daily Report - GitHub Actionsで実行されるメインスクリプト
"""

import os
import json
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime
import anthropic

LINE_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_USER_ID = os.environ["LINE_USER_ID"]
PAGES_URL = "https://hikari-a7.github.io/warren-reports"


def load_holdings():
    try:
        with open("holdings.json", encoding="utf-8") as f:
            return json.load(f).get("holdings", [])
    except Exception:
        return []


def fetch_news_headlines():
    feeds = [
        "https://news.google.com/rss/search?q=日本株+株式市場&hl=ja&gl=JP&ceid=JP:ja",
        "https://news.google.com/rss/search?q=東京株式市場+相場&hl=ja&gl=JP&ceid=JP:ja",
    ]
    headlines = []
    for url in feeds:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                tree = ET.parse(resp)
                for item in tree.getroot().findall(".//item")[:6]:
                    title = item.find("title")
                    if title is not None and title.text:
                        headlines.append(title.text.split(" - ")[0])
        except Exception:
            pass
    return list(dict.fromkeys(headlines))[:10]


def generate_report(headlines, holdings):
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    today = datetime.now().strftime("%Y年%m月%d日")
    holdings_str = "、".join(holdings) if holdings else "未設定"
    headlines_str = "\n".join(f"- {h}" for h in headlines) if headlines else "（取得できませんでした）"

    prompt = f"""あなたは株式投資の専門家Warrenです。{today}の朝レポートを作成してください。

## 今日のニュースヘッドライン
{headlines_str}

## 保有銘柄
{holdings_str}

以下のJSON形式のみで出力してください（各項目は簡潔に1〜2文）：
{{
  "watchlist": ["銘柄コード 銘柄名：注目理由（3〜5件）"],
  "holdings": ["保有銘柄のニュース・動向（未設定ならセクター動向）"],
  "news": ["重要ニュースと株式市場への影響（3〜5件）"]
}}"""

    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )
    text = resp.content[0].text.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def generate_html(data, today_str):
    watchlist = data.get("watchlist", [])
    holdings = data.get("holdings", [])
    news = data.get("news", [])
    date_id = datetime.now().strftime("%Y-%m-%d")

    def items_html(items):
        return "\n".join(f"<li>{item}</li>" for item in items)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Warren レポート {today_str}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, sans-serif; background: #0f1117; color: #e8e8e8; padding: 16px; }}
  header {{ text-align: center; padding: 20px 0 24px; }}
  header h1 {{ font-size: 20px; font-weight: 700; color: #fff; }}
  header p {{ font-size: 13px; color: #888; margin-top: 4px; }}
  .card {{ background: #1a1d27; border-radius: 12px; padding: 16px 18px; margin-bottom: 14px; border-left: 4px solid; }}
  .card.watch {{ border-color: #3b82f6; }}
  .card.holdings {{ border-color: #10b981; }}
  .card.news {{ border-color: #f59e0b; }}
  .card h2 {{ font-size: 13px; font-weight: 600; letter-spacing: 0.05em; margin-bottom: 10px; }}
  .card.watch h2 {{ color: #3b82f6; }}
  .card.holdings h2 {{ color: #10b981; }}
  .card.news h2 {{ color: #f59e0b; }}
  ul {{ list-style: none; }}
  li {{ font-size: 14px; line-height: 1.6; padding: 6px 0; border-bottom: 1px solid #2a2d3a; }}
  li:last-child {{ border-bottom: none; }}
  footer {{ text-align: center; font-size: 11px; color: #555; margin-top: 20px; }}
</style>
</head>
<body>
<header>
  <h1>📊 Warren モーニングレポート</h1>
  <p>{today_str}</p>
</header>
<div class="card watch">
  <h2>🔍 注目銘柄</h2>
  <ul>{items_html(watchlist)}</ul>
</div>
<div class="card holdings">
  <h2>📁 保有銘柄ニュース</h2>
  <ul>{items_html(holdings)}</ul>
</div>
<div class="card news">
  <h2>📰 最新注目ニュース</h2>
  <ul>{items_html(news)}</ul>
</div>
<footer>Warren (Claude) · {date_id} · 投資判断は自己責任でお願いします</footer>
</body>
</html>"""


def send_line(message):
    payload = json.dumps({
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": message}]
    }).encode()
    req = urllib.request.Request(
        "https://api.line.me/v2/bot/message/push",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"},
        method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        print(f"LINE送信: {resp.status}")


if __name__ == "__main__":
    today_str = datetime.now().strftime("%Y年%m月%d日")
    date_id = datetime.now().strftime("%Y-%m-%d")

    print("ニュース取得中...")
    headlines = fetch_news_headlines()
    print(f"{len(headlines)}件取得")

    holdings = load_holdings()
    print(f"保有銘柄: {holdings or '未設定'}")

    print("Claude APIでレポート生成中...")
    data = generate_report(headlines, holdings)

    html = generate_html(data, today_str)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    with open(f"report-{date_id}.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("HTMLファイル保存完了")

    message = f"📊 Warren モーニングレポート {today_str}\n\n本日のレポートはこちら👇\n{PAGES_URL}"
    send_line(message)
    print(f"完了: {PAGES_URL}")
