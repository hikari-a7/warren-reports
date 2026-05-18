#!/usr/bin/env python3
"""
Warren Daily Report - 朝8時・前場引け12:15・引け後18時の3本立て
"""

import os
import json
import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime
import anthropic

LINE_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_USER_ID = os.environ["LINE_USER_ID"]
PAGES_URL = "https://hikari-a7.github.io/warren-reports"
REPORT_TYPE = os.environ.get("REPORT_TYPE", "morning")


def load_holdings():
    try:
        with open("holdings.json", encoding="utf-8") as f:
            return json.load(f).get("holdings", [])
    except Exception:
        return []


def fetch_rss(url, limit=8):
    items = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8", errors="replace")
            tree = ET.fromstring(content)
            for item in tree.findall(".//item")[:limit]:
                title_el = item.find("title")
                link_el = item.find("link")
                if title_el is not None and title_el.text:
                    items.append({
                        "title": title_el.text.split(" - ")[0].strip(),
                        "url": link_el.text.strip() if link_el is not None and link_el.text else ""
                    })
    except Exception as e:
        print(f"RSS取得エラー: {e}")
    return items


def fetch_all_news():
    feeds = [
        "https://news.google.com/rss/search?q=%E6%97%A5%E6%9C%AC%E6%A0%AA+%E6%A0%AA%E5%BC%8F%E5%B8%82%E5%A0%B4&hl=ja&gl=JP&ceid=JP:ja",
        "https://news.google.com/rss/search?q=%E6%9D%B1%E4%BA%AC%E6%A0%AA%E5%BC%8F%E5%B8%82%E5%A0%B4+%E7%9B%B8%E5%A0%B4&hl=ja&gl=JP&ceid=JP:ja",
        "https://news.google.com/rss/search?q=%E6%97%A5%E7%B5%8C%E5%B9%B3%E5%9D%87+%E6%A0%AA%E4%BE%A1&hl=ja&gl=JP&ceid=JP:ja",
        "https://news.google.com/rss/search?q=%E7%B1%B3%E5%9B%BD%E6%A0%AA+%E3%83%8A%E3%82%B9%E3%83%80%E3%83%83%E3%82%AF+%E7%82%BA%E6%9B%BF&hl=ja&gl=JP&ceid=JP:ja",
    ]
    seen, items = set(), []
    for url in feeds:
        for item in fetch_rss(url, 6):
            if item["title"] not in seen:
                seen.add(item["title"])
                items.append(item)
    return items[:12]


def fetch_holding_news(holdings):
    result = []
    for h in holdings:
        query = urllib.parse.quote(f"{h['name']} 株価 {h['code']}")
        url = f"https://news.google.com/rss/search?q={query}&hl=ja&gl=JP&ceid=JP:ja"
        items = fetch_rss(url, 2)
        result.append({
            "code": h["code"],
            "name": h["name"],
            "news": items[:2]
        })
    return result


def call_claude(prompt):
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}]
    )
    text = resp.content[0].text.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def generate_morning(market_news, holding_news, holdings, today_str):
    holdings_str = "\n".join(f"- {h['code']} {h['name']}" for h in holdings)
    news_str = "\n".join(f"- {n['title']}" for n in market_news[:10])
    h_news_str = "\n".join(
        f"- {h['code']} {h['name']}：{h['news'][0]['title'] if h['news'] else 'なし'}"
        for h in holding_news
    )
    prompt = f"""あなたは株式投資の専門家Warrenです。{today_str}の朝8時レポートを作成してください。

## 本日のマーケットニュース
{news_str}

## 保有銘柄の最新ニュース
{h_news_str}

## 保有銘柄
{holdings_str}

以下のJSON形式のみで出力：
{{
  "market_overview": "本日の市場概況2〜3文（日経平均方向感・主要テーマ・為替）",
  "watchlist": [
    {{"name": "銘柄コード 銘柄名", "reason": "注目理由1〜2文"}}
  ],
  "holdings_signals": [
    {{
      "code": "銘柄コード",
      "name": "銘柄名",
      "signal": "買い増し|様子見・保有継続|利確検討",
      "signal_reason": "シグナル根拠1〜2文",
      "risk": "リスク1文",
      "action": "今日の具体的注目ポイント1〜2文"
    }}
  ],
  "news_summary": [
    {{"headline": "ニュース要約", "impact": "株式市場への影響1文"}}
  ]
}}
watchlist3〜4件、holdings_signals全銘柄分、news_summary4〜5件。JSONのみ。"""
    return call_claude(prompt)


def generate_midday(market_news, holding_news, holdings, today_str):
    holdings_str = "\n".join(f"- {h['code']} {h['name']}" for h in holdings)
    news_str = "\n".join(f"- {n['title']}" for n in market_news[:8])
    h_news_str = "\n".join(
        f"- {h['code']} {h['name']}：{h['news'][0]['title'] if h['news'] else 'なし'}"
        for h in holding_news
    )
    prompt = f"""あなたは株式投資の専門家Warrenです。{today_str}の前場引けレポート（12:15）を作成してください。

## 前場中のニュース
{news_str}

## 保有銘柄の動き
{h_news_str}

## 保有銘柄
{holdings_str}

以下のJSON形式のみで出力：
{{
  "zenba_summary": "前場の相場まとめ2〜3文（日経平均・セクター・出来高感）",
  "koba_strategy": "後場に向けた全体戦略1〜2文（注意点・方向感）",
  "holdings_koba": [
    {{
      "code": "銘柄コード",
      "name": "銘柄名",
      "signal": "後場買い|後場売り・利確|後場様子見",
      "reason": "後場戦略の根拠1〜2文",
      "price_point": "具体的な価格帯や注目ポイント1文"
    }}
  ],
  "koba_news": [
    {{"headline": "後場に影響するニュース要約", "impact": "後場への影響1文"}}
  ]
}}
holdings_koba全銘柄分、koba_news3〜4件。JSONのみ。"""
    return call_claude(prompt)


def generate_evening(market_news, holding_news, holdings, today_str):
    holdings_str = "\n".join(f"- {h['code']} {h['name']}" for h in holdings)
    news_str = "\n".join(f"- {n['title']}" for n in market_news[:10])
    h_news_str = "\n".join(
        f"- {h['code']} {h['name']}：{h['news'][0]['title'] if h['news'] else 'なし'}"
        for h in holding_news
    )
    prompt = f"""あなたは株式投資の専門家Warrenです。{today_str}の引け後レポート（18:00）を作成してください。

## 本日のニュース・相場
{news_str}

## 保有銘柄の本日動向
{h_news_str}

## 保有銘柄
{holdings_str}

以下のJSON形式のみで出力：
{{
  "today_summary": "本日相場まとめ2〜3文（日経平均終値・主要動向）",
  "holdings_today": [
    {{
      "code": "銘柄コード",
      "name": "銘柄名",
      "today_move": "本日の動き・評価1文",
      "tomorrow_signal": "明日以降買い増し|明日以降利確検討|明日以降様子見",
      "strategy": "明日以降の具体的戦略1〜2文"
    }}
  ],
  "tomorrow_watchlist": [
    {{"name": "銘柄コード 銘柄名", "reason": "明日注目する理由1〜2文"}}
  ],
  "evening_news": [
    {{"headline": "注目ニュース要約", "impact": "明日の株式市場への影響1文"}}
  ]
}}
holdings_today全銘柄分、tomorrow_watchlist3件、evening_news4〜5件。JSONのみ。"""
    return call_claude(prompt)


def signal_style(signal):
    if "買い" in signal:
        return ("🟢", "#10b981", "#0d3320")
    elif "売り" in signal or "利確" in signal:
        return ("🔴", "#ef4444", "#3b0d0d")
    else:
        return ("🟡", "#f59e0b", "#3b2a0d")


CSS = """
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, 'Hiragino Sans', sans-serif; background: #0b0e1a; color: #e2e8f0; padding: 16px; max-width: 680px; margin: 0 auto; }
  header { text-align: center; padding: 24px 0 20px; border-bottom: 1px solid #1e2535; margin-bottom: 20px; }
  header h1 { font-size: 18px; font-weight: 700; color: #fff; letter-spacing: 0.05em; }
  header p { font-size: 12px; color: #64748b; margin-top: 6px; }
  .section { margin-bottom: 20px; }
  .section-title { font-size: 12px; font-weight: 600; letter-spacing: 0.1em; color: #64748b; text-transform: uppercase; margin-bottom: 10px; padding-bottom: 6px; border-bottom: 1px solid #1e2535; }
  .summary-box { background: #111827; border-radius: 10px; padding: 14px 16px; font-size: 14px; line-height: 1.7; color: #cbd5e1; }
  .watchlist-item { padding: 10px 0; border-bottom: 1px solid #1e2535; }
  .watchlist-item:last-child { border-bottom: none; }
  .wl-name { font-size: 14px; font-weight: 600; color: #3b82f6; }
  .wl-reason { font-size: 13px; color: #94a3b8; margin-top: 4px; line-height: 1.5; }
  .signal-card { background: #111827; border-radius: 10px; padding: 14px 16px; margin-bottom: 12px; border-left: 3px solid; }
  .signal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; flex-wrap: wrap; gap: 6px; }
  .signal-code { font-size: 14px; font-weight: 700; color: #f1f5f9; }
  .signal-badge { font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 20px; }
  .signal-text { font-size: 13px; color: #94a3b8; line-height: 1.6; margin-bottom: 8px; }
  .signal-detail { font-size: 12px; color: #64748b; line-height: 1.6; }
  .signal-detail div { margin-bottom: 4px; }
  .label { color: #475569; font-weight: 600; margin-right: 6px; }
  .news-link { display: block; margin-top: 10px; font-size: 12px; color: #3b82f6; text-decoration: none; padding: 6px 10px; background: #0f172a; border-radius: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .news-item { display: block; padding: 12px 0; border-bottom: 1px solid #1e2535; text-decoration: none; }
  .news-item:last-child { border-bottom: none; }
  .news-headline { display: block; font-size: 14px; color: #3b82f6; line-height: 1.5; margin-bottom: 4px; }
  .news-item:hover .news-headline { text-decoration: underline; }
  .news-impact { display: block; font-size: 12px; color: #64748b; line-height: 1.4; }
  footer { text-align: center; font-size: 11px; color: #334155; margin-top: 24px; padding-top: 16px; border-top: 1px solid #1e2535; }
"""


def build_signal_cards(signals, holding_news_map):
    html = ""
    for s in signals:
        emoji, color, bg = signal_style(s.get("signal", ""))
        hn = holding_news_map.get(s["code"], {})
        news_links = ""
        for n in hn.get("news", [])[:1]:
            if n.get("url"):
                news_links += f'<a href="{n["url"]}" target="_blank" class="news-link">📰 {n["title"]}</a>'
        detail = ""
        if s.get("risk"):
            detail += f'<div><span class="label">リスク</span>{s["risk"]}</div>'
        if s.get("action"):
            detail += f'<div><span class="label">注目</span>{s["action"]}</div>'
        if s.get("price_point"):
            detail += f'<div><span class="label">価格帯</span>{s["price_point"]}</div>'
        if s.get("strategy"):
            detail += f'<div><span class="label">戦略</span>{s["strategy"]}</div>'
        reason = s.get("signal_reason") or s.get("reason") or s.get("today_move", "")
        html += f"""
        <div class="signal-card" style="border-color:{color}">
          <div class="signal-header">
            <span class="signal-code">{s['code']} {s['name']}</span>
            <span class="signal-badge" style="background:{bg};color:{color}">{emoji} {s.get('signal') or s.get('tomorrow_signal','')}</span>
          </div>
          <p class="signal-text">{reason}</p>
          <div class="signal-detail">{detail}</div>
          {news_links}
        </div>"""
    return html


def build_news_section(news_items, market_news):
    html = ""
    for i, item in enumerate(news_items):
        url = market_news[i]["url"] if i < len(market_news) else ""
        link_attr = f'href="{url}" target="_blank"' if url else 'href="#"'
        html += f"""
        <a {link_attr} class="news-item">
          <span class="news-headline">{item.get('headline','')}</span>
          <span class="news-impact">{item.get('impact','')}</span>
        </a>"""
    return html


def generate_html_morning(data, market_news, holding_news, today_str, date_id):
    hn_map = {h["code"]: h for h in holding_news}
    watchlist_html = "".join(
        f'<div class="watchlist-item"><span class="wl-name">{w["name"]}</span><p class="wl-reason">{w["reason"]}</p></div>'
        for w in data.get("watchlist", [])
    )
    signals_html = build_signal_cards(data.get("holdings_signals", []), hn_map)
    news_html = build_news_section(data.get("news_summary", []), market_news)

    return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Warren 朝レポート {today_str}</title><style>{CSS}</style></head><body>
<header><h1>📊 Warren モーニングレポート</h1><p>{today_str}　|　投資判断は自己責任で</p></header>
<div class="section"><div class="section-title">市場概況</div><div class="summary-box">{data.get('market_overview','')}</div></div>
<div class="section"><div class="section-title">注目銘柄</div>{watchlist_html}</div>
<div class="section"><div class="section-title">保有銘柄 売買シグナル</div>{signals_html}</div>
<div class="section"><div class="section-title">最新マーケットニュース</div>{news_html}</div>
<footer>Warren (Claude) · {date_id} · Powered by Anthropic</footer></body></html>"""


def generate_html_midday(data, market_news, holding_news, today_str, date_id):
    hn_map = {h["code"]: h for h in holding_news}
    signals_html = build_signal_cards(data.get("holdings_koba", []), hn_map)
    news_html = build_news_section(data.get("koba_news", []), market_news)

    return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Warren 前場引けレポート {today_str}</title><style>{CSS}</style></head><body>
<header><h1>📊 Warren 前場引けレポート</h1><p>{today_str} 12:15　|　投資判断は自己責任で</p></header>
<div class="section"><div class="section-title">前場まとめ</div><div class="summary-box">{data.get('zenba_summary','')}</div></div>
<div class="section"><div class="section-title">後場戦略</div><div class="summary-box">{data.get('koba_strategy','')}</div></div>
<div class="section"><div class="section-title">保有銘柄 後場シグナル</div>{signals_html}</div>
<div class="section"><div class="section-title">後場に影響するニュース</div>{news_html}</div>
<footer>Warren (Claude) · {date_id} · Powered by Anthropic</footer></body></html>"""


def generate_html_evening(data, market_news, holding_news, today_str, date_id):
    hn_map = {h["code"]: h for h in holding_news}
    # 引けレポートのシグナルはtomorrow_signalフィールドを使う
    signals_html = build_signal_cards(data.get("holdings_today", []), hn_map)
    watchlist_html = "".join(
        f'<div class="watchlist-item"><span class="wl-name">{w["name"]}</span><p class="wl-reason">{w["reason"]}</p></div>'
        for w in data.get("tomorrow_watchlist", [])
    )
    news_html = build_news_section(data.get("evening_news", []), market_news)

    return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Warren 引けレポート {today_str}</title><style>{CSS}</style></head><body>
<header><h1>📊 Warren 引けレポート</h1><p>{today_str} 18:00　|　投資判断は自己責任で</p></header>
<div class="section"><div class="section-title">本日の相場まとめ</div><div class="summary-box">{data.get('today_summary','')}</div></div>
<div class="section"><div class="section-title">保有銘柄 本日動向・明日戦略</div>{signals_html}</div>
<div class="section"><div class="section-title">明日の注目銘柄</div>{watchlist_html}</div>
<div class="section"><div class="section-title">注目ニュース</div>{news_html}</div>
<footer>Warren (Claude) · {date_id} · Powered by Anthropic</footer></body></html>"""


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
    time_str = datetime.now().strftime("%H%M")

    holdings = load_holdings()
    print(f"保有銘柄: {[h['name'] for h in holdings]}")
    print(f"レポートタイプ: {REPORT_TYPE}")

    print("ニュース取得中...")
    market_news = fetch_all_news()
    print(f"マーケットニュース: {len(market_news)}件")

    holding_news = fetch_holding_news(holdings)

    print("Claude APIでレポート生成中...")
    if REPORT_TYPE == "morning":
        data = generate_morning(market_news, holding_news, holdings, today_str)
        html = generate_html_morning(data, market_news, holding_news, today_str, date_id)
        filename = f"report-{date_id}-morning.html"
        label = "モーニングレポート"
    elif REPORT_TYPE == "midday":
        data = generate_midday(market_news, holding_news, holdings, today_str)
        html = generate_html_midday(data, market_news, holding_news, today_str, date_id)
        filename = f"report-{date_id}-midday.html"
        label = "前場引けレポート"
    else:
        data = generate_evening(market_news, holding_news, holdings, today_str)
        html = generate_html_evening(data, market_news, holding_news, today_str, date_id)
        filename = f"report-{date_id}-evening.html"
        label = "引けレポート"

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML保存: {filename}")

    report_url = f"{PAGES_URL}/{filename}"
    message = f"📊 Warren {label} {today_str}\n\nレポートはこちら👇\n{report_url}"
    send_line(message)
    print(f"完了: {report_url}")
