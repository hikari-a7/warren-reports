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
        result.append({"code": h["code"], "name": h["name"], "news": items[:2]})
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
  "market_bullets": ["市場概況の箇条書き（3〜4項目、日経平均・テーマ・為替・注意点）"],
  "watchlist": [
    {{"code": "コード", "name": "銘柄名", "reason": "注目理由1〜2文"}}
  ],
  "holdings_signals": [
    {{
      "code": "銘柄コード",
      "name": "銘柄名",
      "signal": "◎|○|△",
      "signal_label": "買い増し|保有継続|利確検討",
      "move": "直近動向1文",
      "reason": "判断根拠1〜2文",
      "risk": "リスク1文",
      "action": "今日の注目ポイント1〜2文"
    }}
  ],
  "news_summary": [
    {{"headline": "ニュース要約", "impact": "市場への影響1文"}}
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
  "zenba_bullets": ["前場まとめ箇条書き（3〜4項目：日経平均・出来高・セクター動向）"],
  "koba_strategy": "後場全体戦略1〜2文",
  "holdings_koba": [
    {{
      "code": "銘柄コード",
      "name": "銘柄名",
      "signal": "◎|○|△",
      "signal_label": "後場買い|後場様子見|後場利確",
      "reason": "後場戦略根拠1〜2文",
      "price_point": "具体的な価格帯・注目ライン1文"
    }}
  ],
  "koba_news": [
    {{"headline": "後場に影響するニュース", "impact": "後場への影響1文"}}
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
  "today_bullets": ["本日相場まとめ箇条書き（3〜4項目：終値・主要動向・セクター）"],
  "holdings_today": [
    {{
      "code": "銘柄コード",
      "name": "銘柄名",
      "today_move": "本日の動き1文",
      "signal": "◎|○|△",
      "signal_label": "明日買い増し|明日様子見|明日利確検討",
      "strategy": "明日以降の戦略1〜2文"
    }}
  ],
  "tomorrow_watchlist": [
    {{"code": "コード", "name": "銘柄名", "reason": "明日注目理由1〜2文"}}
  ],
  "evening_news": [
    {{"headline": "注目ニュース", "impact": "明日の市場への影響1文"}}
  ]
}}
holdings_today全銘柄分、tomorrow_watchlist3件、evening_news4〜5件。JSONのみ。"""
    return call_claude(prompt)


def signal_badge(signal, label):
    colors = {"◎": ("#1a6b3a", "#d4edda", "◎"), "○": ("#1a4a8a", "#d0e4f7", "○"), "△": ("#8a5a00", "#fff3cd", "△")}
    bg, fg, mark = "#f0f0f0", "#555", signal
    if signal in colors:
        bg_c, fg_c, mark = colors[signal]
        fg, bg = fg_c, bg_c
    return f'<span style="display:inline-block;padding:2px 10px;border-radius:4px;font-size:12px;font-weight:700;background:{bg};color:{fg};border:1px solid {fg}">{mark} {label}</span>'


CSS = """
body { font-family: -apple-system, 'Hiragino Sans', 'Yu Gothic', sans-serif; background: #f5f5f5; color: #222; margin: 0; padding: 16px; }
.container { max-width: 720px; margin: 0 auto; background: #fff; border: 1px solid #ddd; padding: 24px 28px; }
h1 { font-size: 20px; font-weight: 700; color: #111; border-bottom: 2px solid #222; padding-bottom: 10px; margin-bottom: 6px; }
.meta { font-size: 12px; color: #666; margin-bottom: 20px; line-height: 1.8; }
h2 { font-size: 15px; font-weight: 700; color: #111; border-left: 4px solid #1a6b3a; padding-left: 10px; margin: 24px 0 10px; }
ul.bullets { list-style: disc; padding-left: 20px; margin: 0 0 8px; }
ul.bullets li { font-size: 14px; line-height: 1.8; color: #333; }
table { width: 100%; border-collapse: collapse; font-size: 13px; margin-bottom: 8px; }
th { background: #f0f0f0; border: 1px solid #ccc; padding: 7px 10px; text-align: left; font-weight: 600; color: #444; }
td { border: 1px solid #ddd; padding: 7px 10px; vertical-align: top; line-height: 1.5; }
tr:nth-child(even) td { background: #fafafa; }
.watchlist-item { padding: 10px 0; border-bottom: 1px solid #eee; }
.watchlist-item:last-child { border-bottom: none; }
.wl-code { font-size: 13px; font-weight: 700; color: #1a4a8a; }
.wl-reason { font-size: 13px; color: #555; margin-top: 3px; }
.news-link { display: block; padding: 8px 0; border-bottom: 1px solid #eee; text-decoration: none; }
.news-link:last-child { border-bottom: none; }
.news-headline { font-size: 14px; color: #1a4a8a; }
.news-link:hover .news-headline { text-decoration: underline; }
.news-impact { font-size: 12px; color: #777; margin-top: 2px; }
.holding-news { font-size: 11px; margin-top: 4px; }
.holding-news a { color: #1a4a8a; text-decoration: none; }
footer { font-size: 11px; color: #999; text-align: center; margin-top: 24px; padding-top: 12px; border-top: 1px solid #eee; }
"""


def build_holdings_table_morning(signals, hn_map):
    rows = ""
    for s in signals:
        hn = hn_map.get(s["code"], {})
        news_html = ""
        for n in hn.get("news", [])[:1]:
            if n.get("url"):
                news_html = f'<div class="holding-news"><a href="{n["url"]}" target="_blank">📰 {n["title"][:40]}...</a></div>'
        rows += f"""<tr>
          <td><strong>{s['code']}</strong><br>{s['name']}</td>
          <td>{signal_badge(s['signal'], s['signal_label'])}</td>
          <td>{s.get('move','')}</td>
          <td>{s.get('reason','')}<br><small style="color:#888">リスク：{s.get('risk','')}</small></td>
          <td>{s.get('action','')}{news_html}</td>
        </tr>"""
    return f"""<table><thead><tr>
      <th>銘柄</th><th>判断</th><th>直近動向</th><th>根拠・リスク</th><th>注目ポイント</th>
    </tr></thead><tbody>{rows}</tbody></table>"""


def build_holdings_table_midday(signals, hn_map):
    rows = ""
    for s in signals:
        hn = hn_map.get(s["code"], {})
        news_html = ""
        for n in hn.get("news", [])[:1]:
            if n.get("url"):
                news_html = f'<div class="holding-news"><a href="{n["url"]}" target="_blank">📰 {n["title"][:40]}...</a></div>'
        rows += f"""<tr>
          <td><strong>{s['code']}</strong><br>{s['name']}</td>
          <td>{signal_badge(s['signal'], s['signal_label'])}</td>
          <td>{s.get('reason','')}</td>
          <td>{s.get('price_point','')}{news_html}</td>
        </tr>"""
    return f"""<table><thead><tr>
      <th>銘柄</th><th>後場判断</th><th>根拠</th><th>価格帯・注目ライン</th>
    </tr></thead><tbody>{rows}</tbody></table>"""


def build_holdings_table_evening(signals, hn_map):
    rows = ""
    for s in signals:
        hn = hn_map.get(s["code"], {})
        news_html = ""
        for n in hn.get("news", [])[:1]:
            if n.get("url"):
                news_html = f'<div class="holding-news"><a href="{n["url"]}" target="_blank">📰 {n["title"][:40]}...</a></div>'
        rows += f"""<tr>
          <td><strong>{s['code']}</strong><br>{s['name']}</td>
          <td>{s.get('today_move','')}</td>
          <td>{signal_badge(s['signal'], s['signal_label'])}</td>
          <td>{s.get('strategy','')}{news_html}</td>
        </tr>"""
    return f"""<table><thead><tr>
      <th>銘柄</th><th>本日動向</th><th>明日判断</th><th>明日以降の戦略</th>
    </tr></thead><tbody>{rows}</tbody></table>"""


def build_news_links(news_items, market_news):
    html = ""
    for i, item in enumerate(news_items):
        url = market_news[i]["url"] if i < len(market_news) else ""
        link = f'href="{url}" target="_blank"' if url else 'href="#"'
        html += f"""<a {link} class="news-link">
          <div class="news-headline">▶ {item.get('headline','')}</div>
          <div class="news-impact">{item.get('impact','')}</div>
        </a>"""
    return html


def build_watchlist(items):
    html = ""
    for w in items:
        html += f"""<div class="watchlist-item">
          <span class="wl-code">{w.get('code','')} {w['name']}</span>
          <div class="wl-reason">{w['reason']}</div>
        </div>"""
    return html


def wrap_html(title, subtitle, date_id, body):
    return f"""<!DOCTYPE html><html lang="ja"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{title}</title><style>{CSS}</style></head><body>
<div class="container">
<h1>{title}</h1>
<div class="meta">対象：保有{5}銘柄　|　基準日：{subtitle}　|　作成：Warren<br>
本レポートは投資助言ではありません。売買は必ず自己責任で行ってください。</div>
{body}
<footer>Warren (Claude) · {date_id} · Powered by Anthropic</footer>
</div></body></html>"""


def generate_html_morning(data, market_news, holding_news, today_str, date_id):
    hn_map = {h["code"]: h for h in holding_news}
    bullets = "".join(f"<li>{b}</li>" for b in data.get("market_bullets", []))
    body = f"""
<h2>市場環境（朝の概況）</h2>
<ul class="bullets">{bullets}</ul>

<h2>注目銘柄</h2>
{build_watchlist(data.get('watchlist', []))}

<h2>保有銘柄一覧（売買シグナル）</h2>
{build_holdings_table_morning(data.get('holdings_signals', []), hn_map)}

<h2>最新マーケットニュース</h2>
{build_news_links(data.get('news_summary', []), market_news)}"""
    return wrap_html(f"モーニングレポート（{today_str}）", f"{today_str}（月）朝8時", date_id, body)


def generate_html_midday(data, market_news, holding_news, today_str, date_id):
    hn_map = {h["code"]: h for h in holding_news}
    bullets = "".join(f"<li>{b}</li>" for b in data.get("zenba_bullets", []))
    body = f"""
<h2>前場まとめ</h2>
<ul class="bullets">{bullets}</ul>

<h2>後場戦略</h2>
<p style="font-size:14px;padding:10px;background:#f9f9f9;border-left:3px solid #1a6b3a;">{data.get('koba_strategy','')}</p>

<h2>保有銘柄（後場シグナル）</h2>
{build_holdings_table_midday(data.get('holdings_koba', []), hn_map)}

<h2>後場に影響するニュース</h2>
{build_news_links(data.get('koba_news', []), market_news)}"""
    return wrap_html(f"前場引けレポート（{today_str}）", f"{today_str} 12:15", date_id, body)


def generate_html_evening(data, market_news, holding_news, today_str, date_id):
    hn_map = {h["code"]: h for h in holding_news}
    bullets = "".join(f"<li>{b}</li>" for b in data.get("today_bullets", []))
    body = f"""
<h2>本日の相場まとめ</h2>
<ul class="bullets">{bullets}</ul>

<h2>保有銘柄　本日動向・明日戦略</h2>
{build_holdings_table_evening(data.get('holdings_today', []), hn_map)}

<h2>明日の注目銘柄</h2>
{build_watchlist(data.get('tomorrow_watchlist', []))}

<h2>注目ニュース</h2>
{build_news_links(data.get('evening_news', []), market_news)}"""
    return wrap_html(f"引けレポート（{today_str}）", f"{today_str} 18:00", date_id, body)


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
