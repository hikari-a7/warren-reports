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


def fetch_news():
    """Google NewsからRSSで最新株ニュースをタイトル＋URLで取得"""
    feeds = [
        "https://news.google.com/rss/search?q=日本株+株式市場&hl=ja&gl=JP&ceid=JP:ja",
        "https://news.google.com/rss/search?q=東京株式市場+相場+今日&hl=ja&gl=JP&ceid=JP:ja",
    ]
    news_items = []
    seen = set()
    for url in feeds:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                tree = ET.parse(resp)
                for item in tree.getroot().findall(".//item")[:8]:
                    title_el = item.find("title")
                    link_el = item.find("link")
                    if title_el is not None and title_el.text:
                        title = title_el.text.split(" - ")[0].strip()
                        link = link_el.text.strip() if link_el is not None and link_el.text else ""
                        if title not in seen:
                            seen.add(title)
                            news_items.append({"title": title, "url": link})
        except Exception as e:
            print(f"RSS取得エラー: {e}")
    return news_items[:10]


def fetch_holding_news(holdings):
    """保有銘柄ごとのニュースを取得"""
    holding_news = []
    for h in holdings:
        query = urllib.parse.quote(f"{h['name']} {h['code']} 株価")
        url = f"https://news.google.com/rss/search?q={query}&hl=ja&gl=JP&ceid=JP:ja"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                tree = ET.parse(resp)
                items = tree.getroot().findall(".//item")
                if items:
                    item = items[0]
                    title_el = item.find("title")
                    link_el = item.find("link")
                    if title_el is not None and title_el.text:
                        holding_news.append({
                            "code": h["code"],
                            "name": h["name"],
                            "latest_title": title_el.text.split(" - ")[0].strip(),
                            "latest_url": link_el.text.strip() if link_el is not None and link_el.text else ""
                        })
        except Exception:
            holding_news.append({"code": h["code"], "name": h["name"], "latest_title": "", "latest_url": ""})
    return holding_news


def generate_report(market_news, holding_news, holdings):
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    today = datetime.now().strftime("%Y年%m月%d日")

    holdings_str = "\n".join(f"- {h['code']} {h['name']}" for h in holdings)
    news_str = "\n".join(f"- {n['title']}" for n in market_news[:8])
    holding_news_str = "\n".join(
        f"- {h['code']} {h['name']}：{h['latest_title'] or '最新ニュースなし'}"
        for h in holding_news
    )

    prompt = f"""あなたは株式投資の専門家Warrenです。{today}の朝レポートを作成してください。

## 本日のマーケットニュース
{news_str}

## 保有銘柄の最新ニュース
{holding_news_str}

## 保有銘柄リスト
{holdings_str}

以下のJSON形式のみで出力してください：
{{
  "market_overview": "本日の市場概況を2〜3文で（日経平均の方向感・主要テーマ）",
  "watchlist": [
    {{"name": "銘柄コード 銘柄名", "reason": "注目理由1〜2文"}}
  ],
  "holdings_signals": [
    {{
      "code": "銘柄コード",
      "name": "銘柄名",
      "signal": "買い増し|様子見・保有継続|利確検討",
      "signal_reason": "シグナルの根拠1〜2文",
      "risk": "リスク1文",
      "action": "今日の具体的な注目ポイント1〜2文"
    }}
  ],
  "news_summary": [
    {{"headline": "ニュースタイトル要約", "impact": "株式市場への影響1文"}}
  ]
}}

watchlistは3〜4件、holdings_signalsは全保有銘柄分、news_summaryは3〜5件。JSONのみ出力。"""

    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2500,
        messages=[{"role": "user", "content": prompt}]
    )
    text = resp.content[0].text.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def signal_style(signal):
    if "買い" in signal:
        return ("🟢", "#10b981", "#0d3320")
    elif "利確" in signal or "売り" in signal:
        return ("🔴", "#ef4444", "#3b0d0d")
    else:
        return ("🟡", "#f59e0b", "#3b2a0d")


def generate_html(data, market_news, holding_news, today_str):
    date_id = datetime.now().strftime("%Y-%m-%d")

    # 注目銘柄HTML
    watchlist_html = ""
    for w in data.get("watchlist", []):
        watchlist_html += f"""
        <div class="watchlist-item">
          <span class="wl-name">{w['name']}</span>
          <p class="wl-reason">{w['reason']}</p>
        </div>"""

    # 保有銘柄シグナルHTML
    signals_html = ""
    holding_news_map = {h["code"]: h for h in holding_news}
    for s in data.get("holdings_signals", []):
        emoji, color, bg = signal_style(s["signal"])
        hn = holding_news_map.get(s["code"], {})
        news_link = ""
        if hn.get("latest_title") and hn.get("latest_url"):
            news_link = f'<a href="{hn["latest_url"]}" target="_blank" class="news-link">📰 {hn["latest_title"]}</a>'
        signals_html += f"""
        <div class="signal-card" style="border-color:{color}">
          <div class="signal-header">
            <span class="signal-code">{s['code']} {s['name']}</span>
            <span class="signal-badge" style="background:{bg};color:{color}">{emoji} {s['signal']}</span>
          </div>
          <p class="signal-reason">{s['signal_reason']}</p>
          <div class="signal-detail">
            <div><span class="label">リスク</span>{s['risk']}</div>
            <div><span class="label">注目ポイント</span>{s['action']}</div>
          </div>
          {news_link}
        </div>"""

    # ニュースHTML
    news_html = ""
    news_summaries = data.get("news_summary", [])
    for i, item in enumerate(news_summaries):
        url = market_news[i]["url"] if i < len(market_news) else ""
        link_attr = f'href="{url}" target="_blank"' if url else 'href="#"'
        news_html += f"""
        <a {link_attr} class="news-item">
          <span class="news-headline">{item['headline']}</span>
          <span class="news-impact">{item['impact']}</span>
        </a>"""

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Warren レポート {today_str}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, 'Hiragino Sans', sans-serif; background: #0b0e1a; color: #e2e8f0; padding: 16px; max-width: 680px; margin: 0 auto; }}

  header {{ text-align: center; padding: 24px 0 20px; border-bottom: 1px solid #1e2535; margin-bottom: 20px; }}
  header h1 {{ font-size: 18px; font-weight: 700; color: #fff; letter-spacing: 0.05em; }}
  header p {{ font-size: 12px; color: #64748b; margin-top: 6px; }}

  .section {{ margin-bottom: 20px; }}
  .section-title {{ font-size: 12px; font-weight: 600; letter-spacing: 0.1em; color: #64748b; text-transform: uppercase; margin-bottom: 10px; padding-bottom: 6px; border-bottom: 1px solid #1e2535; }}

  .market-box {{ background: #111827; border-radius: 10px; padding: 14px 16px; font-size: 14px; line-height: 1.7; color: #cbd5e1; }}

  .watchlist-item {{ padding: 10px 0; border-bottom: 1px solid #1e2535; }}
  .watchlist-item:last-child {{ border-bottom: none; }}
  .wl-name {{ font-size: 14px; font-weight: 600; color: #3b82f6; }}
  .wl-reason {{ font-size: 13px; color: #94a3b8; margin-top: 4px; line-height: 1.5; }}

  .signal-card {{ background: #111827; border-radius: 10px; padding: 14px 16px; margin-bottom: 12px; border-left: 3px solid; }}
  .signal-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; flex-wrap: wrap; gap: 6px; }}
  .signal-code {{ font-size: 14px; font-weight: 700; color: #f1f5f9; }}
  .signal-badge {{ font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 20px; }}
  .signal-reason {{ font-size: 13px; color: #94a3b8; line-height: 1.6; margin-bottom: 10px; }}
  .signal-detail {{ font-size: 12px; color: #64748b; line-height: 1.6; }}
  .signal-detail div {{ margin-bottom: 4px; }}
  .label {{ color: #475569; font-weight: 600; margin-right: 6px; }}
  .news-link {{ display: block; margin-top: 10px; font-size: 12px; color: #3b82f6; text-decoration: none; padding: 6px 10px; background: #0f172a; border-radius: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}

  .news-item {{ display: block; padding: 12px 0; border-bottom: 1px solid #1e2535; text-decoration: none; }}
  .news-item:last-child {{ border-bottom: none; }}
  .news-headline {{ display: block; font-size: 14px; color: #3b82f6; line-height: 1.5; margin-bottom: 4px; }}
  .news-item:hover .news-headline {{ text-decoration: underline; }}
  .news-impact {{ display: block; font-size: 12px; color: #64748b; line-height: 1.4; }}

  footer {{ text-align: center; font-size: 11px; color: #334155; margin-top: 24px; padding-top: 16px; border-top: 1px solid #1e2535; }}
</style>
</head>
<body>

<header>
  <h1>📊 Warren モーニングレポート</h1>
  <p>{today_str}　|　投資判断は自己責任でお願いします</p>
</header>

<div class="section">
  <div class="section-title">市場概況</div>
  <div class="market-box">{data.get('market_overview', '')}</div>
</div>

<div class="section">
  <div class="section-title">注目銘柄</div>
  {watchlist_html}
</div>

<div class="section">
  <div class="section-title">保有銘柄 売買シグナル</div>
  {signals_html}
</div>

<div class="section">
  <div class="section-title">最新マーケットニュース</div>
  {news_html}
</div>

<footer>Warren (Claude) · {date_id} · Powered by Anthropic</footer>
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
    import urllib.parse

    today_str = datetime.now().strftime("%Y年%m月%d日")
    date_id = datetime.now().strftime("%Y-%m-%d")

    holdings = load_holdings()
    print(f"保有銘柄: {[h['name'] for h in holdings]}")

    print("マーケットニュース取得中...")
    market_news = fetch_news()
    print(f"{len(market_news)}件取得")

    print("保有銘柄ニュース取得中...")
    holding_news = fetch_holding_news(holdings)

    print("Claude APIでレポート生成中...")
    data = generate_report(market_news, holding_news, holdings)

    html = generate_html(data, market_news, holding_news, today_str)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    with open(f"report-{date_id}.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("HTMLファイル保存完了")

    message = f"📊 Warren モーニングレポート {today_str}\n\n本日のレポートはこちら👇\n{PAGES_URL}"
    send_line(message)
    print(f"完了: {PAGES_URL}")
