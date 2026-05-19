#!/usr/bin/env python3
"""
Warren Daily Report - 朝8時・前場引け・引け後・週次の4本立て + チャート付き
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


def fetch_stock_data(holdings):
    """Returns (stats_dict, histories_dict)"""
    try:
        import yfinance as yf
    except ImportError:
        print("yfinanceが未インストール")
        return {}, {}

    result, histories = {}, {}
    for h in holdings:
        code = h["code"]
        try:
            hist = yf.Ticker(f"{code}.T").history(period="3mo")
            if hist.empty or len(hist) < 2:
                result[code] = None
                continue

            histories[code] = hist
            closes = hist["Close"].dropna()
            volumes = hist["Volume"].dropna()

            latest = float(closes.iloc[-1])
            prev = float(closes.iloc[-2])
            change_pct = (latest - prev) / prev * 100

            vol_avg = float(volumes.iloc[-21:-1].mean()) if len(volumes) >= 21 else float(volumes.mean())
            vol_ratio = float(volumes.iloc[-1]) / vol_avg if vol_avg > 0 else 1.0

            ma5 = float(closes.tail(5).mean()) if len(closes) >= 5 else None
            ma25 = float(closes.tail(25).mean()) if len(closes) >= 25 else None
            ma75 = float(closes.tail(75).mean()) if len(closes) >= 75 else None

            delta = closes.diff().dropna()
            gain = float(delta.clip(lower=0).tail(14).mean())
            loss = float((-delta.clip(upper=0)).tail(14).mean())
            rsi = 100 - (100 / (1 + gain / loss)) if loss > 0 else 100.0

            week_data = closes.tail(6)
            week_start = float(week_data.iloc[0]) if len(week_data) >= 2 else None
            week_change = (latest - week_start) / week_start * 100 if week_start else None

            cost = h.get("cost")
            shares = h.get("shares", 0)
            pnl_per = round(latest - cost, 1) if cost else None
            pnl_pct = round((latest - cost) / cost * 100, 2) if cost else None
            pnl_total = round(pnl_per * shares) if pnl_per is not None else None

            result[code] = {
                "price": round(latest, 1),
                "change_pct": round(change_pct, 2),
                "week_change": round(week_change, 2) if week_change is not None else None,
                "volume_ratio": round(vol_ratio, 1),
                "ma5": round(ma5, 1) if ma5 else None,
                "ma25": round(ma25, 1) if ma25 else None,
                "ma75": round(ma75, 1) if ma75 else None,
                "rsi": round(rsi, 1),
                "vs_ma5": round((latest - ma5) / ma5 * 100, 1) if ma5 else None,
                "vs_ma25": round((latest - ma25) / ma25 * 100, 1) if ma25 else None,
                "vs_ma75": round((latest - ma75) / ma75 * 100, 1) if ma75 else None,
                "cost": cost,
                "shares": shares,
                "pnl_per": pnl_per,
                "pnl_pct": pnl_pct,
                "pnl_total": pnl_total,
            }
            d = result[code]
            pnl_str = f" 含み{'+' if (d['pnl_pct'] or 0) >= 0 else ''}{d['pnl_pct']}%" if d['pnl_pct'] is not None else ""
            print(f"株価取得: {code} ¥{d['price']} {d['change_pct']:+.2f}% RSI={d['rsi']}{pnl_str}")
        except Exception as e:
            print(f"株価取得エラー {code}: {e}")
            result[code] = None

    return result, histories


def generate_chart_b64(code, hist, cost=None):
    try:
        import mplfinance as mpf
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import pandas as pd
        import io, base64

        ohlcv = hist.tail(60)[["Open", "High", "Low", "Close", "Volume"]].copy()
        closes = ohlcv["Close"]

        delta = closes.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rsi = (100 - (100 / (1 + gain / loss))).fillna(50)

        apds = [
            mpf.make_addplot(closes.rolling(5).mean(), color="#1a4a8a", width=0.9),
            mpf.make_addplot(closes.rolling(25).mean(), color="#c47a00", width=1.1),
            mpf.make_addplot(rsi, panel=1, color="#7b2d8b", width=1.0, ylim=(0, 100)),
        ]
        if cost:
            cost_line = pd.Series([float(cost)] * len(ohlcv), index=ohlcv.index)
            apds.append(mpf.make_addplot(cost_line, color="#c0392b",
                                          linestyle="--", width=0.8))

        mc = mpf.make_marketcolors(up="#1a6b3a", down="#c0392b",
                                    edge="inherit", wick="inherit")
        s = mpf.make_mpf_style(marketcolors=mc, gridstyle=":",
                                gridcolor="#e8e8e8", facecolor="white",
                                edgecolor="#cccccc", figcolor="white")

        fig, axes = mpf.plot(
            ohlcv, type="candle", style=s, addplot=apds,
            returnfig=True, figsize=(5.5, 3.2), panel_ratios=(3, 1),
            volume=False, tight_layout=True
        )

        if len(axes) > 1:
            axes[1].axhline(y=70, color="#c0392b", linestyle="--", linewidth=0.5, alpha=0.6)
            axes[1].axhline(y=30, color="#1a6b3a", linestyle="--", linewidth=0.5, alpha=0.6)
            axes[1].set_ylabel("RSI", fontsize=7)

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=90, bbox_inches="tight",
                    facecolor="white", edgecolor="none")
        plt.close(fig)
        buf.seek(0)
        return base64.b64encode(buf.read()).decode("utf-8")
    except Exception as e:
        print(f"チャート生成エラー {code}: {e}")
        return None


def build_charts_section(holdings, histories, stock_data):
    html = ""
    for h in holdings:
        code = h["code"]
        hist = histories.get(code)
        if hist is None:
            continue
        d = stock_data.get(code) or {}
        b64 = generate_chart_b64(code, hist, h.get("cost"))
        if not b64:
            continue

        pnl_pct = d.get("pnl_pct")
        week_change = d.get("week_change")
        pnl_color = "#1a6b3a" if (pnl_pct or 0) >= 0 else "#c0392b"
        week_color = "#1a6b3a" if (week_change or 0) >= 0 else "#c0392b"

        week_str = f'今週 <span style="color:{week_color};font-weight:700">{("+" if (week_change or 0) >= 0 else "")}{week_change}%</span>' \
                   if week_change is not None else ""
        pnl_str = f'含み <span style="color:{pnl_color};font-weight:700">{("+" if (pnl_pct or 0) >= 0 else "")}{pnl_pct}%</span>' \
                  if pnl_pct is not None else ""

        html += f"""<div style="margin-bottom:14px;border:1px solid #ddd;border-radius:4px;padding:10px;background:#fff;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;">
    <strong style="font-size:13px">{code} {h['name']}</strong>
    <span style="font-size:12px;color:#666">{week_str}&ensp;{pnl_str}</span>
  </div>
  <img src="data:image/png;base64,{b64}" style="width:100%;height:auto;display:block;" alt="{code}">
  <p style="font-size:10px;color:#aaa;margin-top:4px;">青=MA5　橙=MA25　赤破線=取得単価　下段=RSI（赤70・緑30）</p>
</div>"""

    return html or '<p style="color:#999;font-size:13px">チャートデータ取得不可</p>'


def stock_data_str(holdings, stock_data):
    lines = []
    for h in holdings:
        d = stock_data.get(h["code"])
        if d:
            sign = "+" if d["change_pct"] >= 0 else ""
            vs25 = f"MA25比{'+' if (d.get('vs_ma25') or 0) >= 0 else ''}{d.get('vs_ma25', 'N/A')}%" \
                   if d.get("vs_ma25") is not None else "MA25:N/A"
            pnl_str = ""
            if d.get("pnl_pct") is not None:
                pnl_str = f" | 含み{'+' if d['pnl_pct'] >= 0 else ''}{d['pnl_pct']}%({'+' if (d['pnl_total'] or 0) >= 0 else ''}{d['pnl_total']:,}円)"
            lines.append(
                f"- {h['code']} {h['name']}: ¥{d['price']} ({sign}{d['change_pct']}%) "
                f"| RSI={d['rsi']} | {vs25} | 出来高比{d['volume_ratio']}x{pnl_str}"
            )
        else:
            lines.append(f"- {h['code']} {h['name']}: データ取得不可")
    return "\n".join(lines)


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


def save_portfolio_snapshot(holdings, stock_data, date_id):
    history_file = "portfolio_history.json"
    try:
        with open(history_file, encoding="utf-8") as f:
            history = json.load(f)
    except Exception:
        history = {"snapshots": []}

    if any(s["date"] == date_id for s in history["snapshots"]):
        print(f"スナップショット（{date_id}）は記録済みのためスキップ")
        return

    total_cost = total_value = total_pnl = 0
    holdings_data = {}
    for h in holdings:
        d = stock_data.get(h["code"])
        if d and d.get("cost") and d.get("shares"):
            total_cost += d["cost"] * d["shares"]
            total_value += d["price"] * d["shares"]
            total_pnl += (d["pnl_total"] or 0)
            holdings_data[h["code"]] = {
                "price": d["price"],
                "pnl_pct": d["pnl_pct"],
                "pnl_total": d["pnl_total"],
            }

    history["snapshots"].append({
        "date": date_id,
        "total_cost": round(total_cost),
        "total_value": round(total_value),
        "total_pnl": round(total_pnl),
        "holdings": holdings_data,
    })
    history["snapshots"] = sorted(history["snapshots"], key=lambda x: x["date"])[-90:]

    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    print(f"ポートフォリオスナップショット保存: {date_id}")


def build_portfolio_trend_chart():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from datetime import datetime as dt
        import io, base64

        with open("portfolio_history.json", encoding="utf-8") as f:
            history = json.load(f)

        snapshots = history.get("snapshots", [])
        if len(snapshots) < 2:
            return None

        dates = [dt.strptime(s["date"], "%Y-%m-%d") for s in snapshots]
        values = [s["total_value"] for s in snapshots]
        costs = [s["total_cost"] for s in snapshots]
        pnls = [s["total_pnl"] for s in snapshots]
        base_cost = costs[0] if costs else 0

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(6, 4),
                                         gridspec_kw={"height_ratios": [3, 1]})
        fig.patch.set_facecolor("white")

        ax1.plot(dates, values, color="#1a4a8a", linewidth=1.5)
        ax1.axhline(y=base_cost, color="#888", linestyle="--", linewidth=0.8)
        ax1.fill_between(dates, base_cost, values,
                         where=[v >= base_cost for v in values],
                         alpha=0.12, color="#1a6b3a")
        ax1.fill_between(dates, base_cost, values,
                         where=[v < base_cost for v in values],
                         alpha=0.12, color="#c0392b")
        ax1.set_ylabel("Portfolio (JPY)", fontsize=8)
        ax1.yaxis.set_major_formatter(
            plt.FuncFormatter(lambda x, _: f"{x/1e6:.2f}M"))
        ax1.grid(True, linestyle=":", alpha=0.4)
        ax1.set_facecolor("white")
        ax1.tick_params(labelsize=7)
        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))

        bar_colors = ["#1a6b3a" if p >= 0 else "#c0392b" for p in pnls]
        ax2.bar(dates, pnls, color=bar_colors, width=0.6)
        ax2.axhline(y=0, color="#333", linewidth=0.5)
        ax2.set_ylabel("P&L (JPY)", fontsize=8)
        ax2.yaxis.set_major_formatter(
            plt.FuncFormatter(lambda x, _: f"{x/1e4:.0f}万"))
        ax2.set_facecolor("white")
        ax2.tick_params(labelsize=7)
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))

        plt.tight_layout(pad=0.5)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=90, bbox_inches="tight",
                    facecolor="white", edgecolor="none")
        plt.close(fig)
        buf.seek(0)
        return base64.b64encode(buf.read()).decode("utf-8")
    except Exception as e:
        print(f"トレンドチャート生成エラー: {e}")
        return None


def call_claude(prompt):
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}]
    )
    text = resp.content[0].text.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def generate_morning(market_news, holding_news, holdings, today_str, stock_data):
    holdings_str = "\n".join(f"- {h['code']} {h['name']}" for h in holdings)
    news_str = "\n".join(f"- {n['title']}" for n in market_news[:10])
    h_news_str = "\n".join(
        f"- {h['code']} {h['name']}：{h['news'][0]['title'] if h['news'] else 'なし'}"
        for h in holding_news
    )
    tech_str = stock_data_str(holdings, stock_data)
    prompt = f"""あなたは株式投資の専門家Warrenです。{today_str}の朝8時レポートを作成してください。

## 保有銘柄のテクニカルデータ（実データ）
{tech_str}

## 本日のマーケットニュース
{news_str}

## 保有銘柄の最新ニュース
{h_news_str}

## 保有銘柄
{holdings_str}

テクニカルデータを必ず参照してシグナルを判断してください。RSI<30は売られすぎ（買い検討）、RSI>70は買われすぎ（利確検討）、MA25比プラスは上昇トレンド、出来高比1.5x超は注目シグナル。

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
      "move": "直近動向1文（株価・RSI等の数値を含めること）",
      "reason": "判断根拠1〜2文（RSI・移動平均・出来高の数値根拠を必ず含める）",
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


def generate_midday(market_news, holding_news, holdings, today_str, stock_data):
    holdings_str = "\n".join(f"- {h['code']} {h['name']}" for h in holdings)
    news_str = "\n".join(f"- {n['title']}" for n in market_news[:8])
    h_news_str = "\n".join(
        f"- {h['code']} {h['name']}：{h['news'][0]['title'] if h['news'] else 'なし'}"
        for h in holding_news
    )
    tech_str = stock_data_str(holdings, stock_data)
    prompt = f"""あなたは株式投資の専門家Warrenです。{today_str}の前場引けレポート（12:15）を作成してください。

## 保有銘柄のテクニカルデータ（実データ）
{tech_str}

## 前場中のニュース
{news_str}

## 保有銘柄の動き
{h_news_str}

## 保有銘柄
{holdings_str}

テクニカルデータを必ず参照してください。前場の動きとRSI・移動平均を組み合わせて後場戦略を立案してください。

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
      "reason": "後場戦略根拠1〜2文（RSI・価格帯の数値を含める）",
      "price_point": "具体的な価格帯・注目ライン1文"
    }}
  ],
  "koba_news": [
    {{"headline": "後場に影響するニュース", "impact": "後場への影響1文"}}
  ]
}}
holdings_koba全銘柄分、koba_news3〜4件。JSONのみ。"""
    return call_claude(prompt)


def generate_evening(market_news, holding_news, holdings, today_str, stock_data):
    holdings_str = "\n".join(f"- {h['code']} {h['name']}" for h in holdings)
    news_str = "\n".join(f"- {n['title']}" for n in market_news[:10])
    h_news_str = "\n".join(
        f"- {h['code']} {h['name']}：{h['news'][0]['title'] if h['news'] else 'なし'}"
        for h in holding_news
    )
    tech_str = stock_data_str(holdings, stock_data)
    prompt = f"""あなたは株式投資の専門家Warrenです。{today_str}の引け後レポート（18:00）を作成してください。

## 保有銘柄のテクニカルデータ（実データ）
{tech_str}

## 本日のニュース・相場
{news_str}

## 保有銘柄の本日動向
{h_news_str}

## 保有銘柄
{holdings_str}

テクニカルデータを必ず参照してください。本日の終値・RSI・出来高比をもとに、明日以降の戦略を立案してください。

以下のJSON形式のみで出力：
{{
  "today_bullets": ["本日相場まとめ箇条書き（3〜4項目：終値・主要動向・セクター）"],
  "holdings_today": [
    {{
      "code": "銘柄コード",
      "name": "銘柄名",
      "today_move": "本日の動き1文（終値・前日比の数値を含める）",
      "signal": "◎|○|△",
      "signal_label": "明日買い増し|明日様子見|明日利確検討",
      "strategy": "明日以降の戦略1〜2文（具体的な価格帯・RSIライン等を含める）"
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


def generate_weekly(market_news, holding_news, holdings, today_str, stock_data):
    holdings_str = "\n".join(f"- {h['code']} {h['name']}" for h in holdings)
    news_str = "\n".join(f"- {n['title']}" for n in market_news[:10])

    perf_lines = []
    for h in holdings:
        d = stock_data.get(h["code"])
        if d:
            week_str = f"週間{'+' if (d.get('week_change') or 0) >= 0 else ''}{d.get('week_change', 'N/A')}%" \
                       if d.get("week_change") is not None else "週間:N/A"
            pnl_str = f"含み{'+' if (d.get('pnl_pct') or 0) >= 0 else ''}{d['pnl_pct']}%({d['pnl_total']:,}円)" \
                      if d.get("pnl_pct") is not None else ""
            perf_lines.append(
                f"- {h['code']} {h['name']}: ¥{d['price']} | {week_str} | RSI={d['rsi']} | {pnl_str}"
            )
        else:
            perf_lines.append(f"- {h['code']} {h['name']}: データなし")

    prompt = f"""あなたは株式投資の専門家Warrenです。{today_str}の週次レポートを作成してください。

## 保有銘柄の週間パフォーマンス（実データ）
{chr(10).join(perf_lines)}

## 今週の主要ニュース
{news_str}

## 保有銘柄
{holdings_str}

今週の実績を踏まえ、来週の戦略を具体的に立案してください。

以下のJSON形式のみで出力：
{{
  "week_summary": "今週の相場全体サマリー（2〜3文）",
  "best_performer": {{"code": "コード", "name": "銘柄名", "comment": "今週の活躍内容と理由"}},
  "worst_performer": {{"code": "コード", "name": "銘柄名", "comment": "今週の動き・背景・対応策"}},
  "holdings_weekly": [
    {{
      "code": "銘柄コード",
      "name": "銘柄名",
      "week_review": "今週の動き1文（数値を含める）",
      "signal": "◎|○|△",
      "signal_label": "来週買い増し|来週様子見|来週利確検討",
      "next_week_strategy": "来週の戦略1〜2文（具体的な価格帯・RSIライン等を含める）"
    }}
  ],
  "market_outlook": "来週の市場見通し2〜3文",
  "key_strategies": ["来週の重要戦略ポイント（3つ）"]
}}
holdings_weekly全銘柄分。JSONのみ。"""
    return call_claude(prompt)


def signal_badge(signal, label):
    colors = {"◎": ("#1a6b3a", "#d4edda"), "○": ("#1a4a8a", "#d0e4f7"), "△": ("#8a5a00", "#fff3cd")}
    if signal in colors:
        fg, bg = colors[signal]
        return f'<span style="display:inline-block;padding:2px 10px;border-radius:4px;font-size:12px;font-weight:700;background:{bg};color:{fg};border:1px solid {fg}">{signal} {label}</span>'
    return f'<span style="display:inline-block;padding:2px 10px;border-radius:4px;font-size:12px;font-weight:700;background:#f0f0f0;color:#555">{signal} {label}</span>'


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
.tech-note { font-size: 11px; color: #999; margin-top: 4px; }
.highlight-box { background: #f0f7f0; border: 1px solid #b8ddb8; border-radius: 4px; padding: 12px 16px; margin-bottom: 12px; }
.highlight-box.red { background: #fdf0f0; border-color: #ddb8b8; }
footer { font-size: 11px; color: #999; text-align: center; margin-top: 24px; padding-top: 12px; border-top: 1px solid #eee; }
"""


def build_portfolio_summary(holdings, stock_data):
    total_cost = total_val = total_pnl = 0
    has_data = False
    for h in holdings:
        d = stock_data.get(h["code"])
        if d and d.get("cost") and d.get("shares"):
            total_cost += d["cost"] * d["shares"]
            total_val += d["price"] * d["shares"]
            total_pnl += (d["pnl_total"] or 0)
            has_data = True
    if not has_data:
        return ""
    pnl_color = "#1a6b3a" if total_pnl >= 0 else "#c0392b"
    pnl_sign = "+" if total_pnl >= 0 else ""
    pnl_pct = round(total_pnl / total_cost * 100, 2) if total_cost else 0
    return f"""<div style="background:#f9f9f9;border:1px solid #ddd;border-radius:4px;padding:12px 16px;margin-bottom:16px;display:flex;gap:24px;flex-wrap:wrap;">
  <div><span style="font-size:11px;color:#888">評価額合計 <span style="color:#bbb">※参考値</span></span><br><strong style="font-size:16px">¥{total_val:,.0f}</strong></div>
  <div><span style="font-size:11px;color:#888">取得金額合計</span><br><strong style="font-size:16px">¥{total_cost:,.0f}</strong></div>
  <div><span style="font-size:11px;color:#888">含み損益</span><br><strong style="font-size:16px;color:{pnl_color}">{pnl_sign}¥{total_pnl:,} ({pnl_sign}{pnl_pct}%)</strong></div>
</div>
<p style="font-size:11px;color:#aaa;margin:-10px 0 14px">※ 評価額はyfinance取得値（最大15分遅延）。SBI証券のリアルタイム価格とは差が出る場合があります。</p>"""


def build_price_table(holdings, stock_data):
    cards = ""
    for h in holdings:
        d = stock_data.get(h["code"])
        if not d:
            cards += f'<div style="border:1px solid #ddd;border-radius:4px;padding:10px 12px;background:#fff;"><strong style="font-size:13px;color:#1a4a8a">{h["code"]}</strong> <span style="font-size:11px;color:#888">{h["name"]}</span><div style="font-size:12px;color:#999;margin-top:6px">データ取得不可</div></div>'
            continue

        price = d["price"]
        chg = d["change_pct"]
        chg_color = "#1a6b3a" if chg >= 0 else "#c0392b"
        rsi = d["rsi"]
        rsi_color = "#c0392b" if rsi > 70 else ("#1a4a8a" if rsi < 30 else "#555")
        rsi_note = "⚠" if rsi > 70 else ("★" if rsi < 30 else "")
        vs25 = d.get("vs_ma25")
        ma25_str = f"{'+' if (vs25 or 0) >= 0 else ''}{vs25}%" if vs25 is not None else "—"
        ma25_color = "#1a6b3a" if (vs25 or 0) >= 0 else "#c0392b"
        vol = d["volume_ratio"]
        vol_color = "#c47a00" if vol >= 1.5 else "#555"
        pnl_pct = d.get("pnl_pct")
        pnl_total = d.get("pnl_total")
        cost = d.get("cost")

        if pnl_pct is not None:
            pc = "#1a6b3a" if pnl_pct >= 0 else "#c0392b"
            ps = "+" if pnl_pct >= 0 else ""
            pnl_html = f'<span style="color:{pc};font-weight:700">{ps}{pnl_pct}%</span> <span style="color:{pc};font-size:11px">({ps}¥{pnl_total:,})</span>'
        else:
            pnl_html = '<span style="color:#999">—</span>'

        target = h.get("target")
        stop = h.get("stop_loss")
        ts_parts = []
        if target:
            t_dist = round((target - price) / price * 100, 1)
            t_col = "#1a6b3a" if t_dist >= 0 else "#888"
            ts_parts.append(f'<span style="color:{t_col}">↑{target:,}({t_dist:+.1f}%)</span>')
        if stop:
            s_dist = round((stop - price) / price * 100, 1)
            s_col = "#c0392b" if s_dist < 0 else "#888"
            ts_parts.append(f'<span style="color:{s_col}">↓{stop:,}({s_dist:+.1f}%)</span>')
        ts_html = '<span style="font-size:11px;color:#666">' + "　".join(ts_parts) + "</span>" if ts_parts else ""

        cards += f'''<div style="border:1px solid #ddd;border-radius:4px;padding:10px 12px;background:#fff;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;">
    <strong style="font-size:13px;color:#1a4a8a">{h['code']}</strong>
    <span style="font-size:11px;color:#777;text-align:right;max-width:55%">{h['name']}</span>
  </div>
  <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:4px;">
    <span style="font-size:17px;font-weight:700">¥{price:,.0f}</span>
    <span style="font-size:13px;font-weight:700;color:{chg_color}">{'+' if chg >= 0 else ''}{chg}%</span>
  </div>
  <div style="font-size:12px;margin-bottom:4px;">{pnl_html}</div>
  {f'<div style="margin-bottom:5px;">{ts_html}</div>' if ts_html else ""}
  <div style="display:flex;gap:10px;font-size:11px;color:#555;border-top:1px solid #f0f0f0;padding-top:5px;">
    <span>RSI <strong style="color:{rsi_color}">{rsi}{rsi_note}</strong></span>
    <span>MA25 <strong style="color:{ma25_color}">{ma25_str}</strong></span>
    <span>出来高 <strong style="color:{vol_color}">{vol}x</strong></span>
  </div>
</div>'''

    return f'''<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px;">{cards}</div>
<p class="tech-note">RSI★=売られすぎ(30以下)　RSI⚠=買われすぎ(70以上)　↑目標/↓損切は現在値からの距離</p>'''


def build_holdings_table_morning(signals, hn_map):
    html = ""
    for s in signals:
        hn = hn_map.get(s["code"], {})
        news_html = ""
        for n in hn.get("news", [])[:1]:
            if n.get("url"):
                news_html = f'<div class="holding-news" style="margin-top:5px"><a href="{n["url"]}" target="_blank">📰 {n["title"][:45]}...</a></div>'
        html += f'''<div style="border:1px solid #ddd;border-radius:4px;padding:10px 12px;background:#fff;margin-bottom:8px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:7px;">
    <strong style="font-size:13px">{s['code']} {s['name']}</strong>
    {signal_badge(s['signal'], s['signal_label'])}
  </div>
  <div style="font-size:12px;color:#444;margin-bottom:3px;line-height:1.6"><span style="font-weight:600;color:#888">動向</span>　{s.get('move','')}</div>
  <div style="font-size:12px;color:#444;margin-bottom:3px;line-height:1.6"><span style="font-weight:600;color:#888">根拠</span>　{s.get('reason','')}</div>
  <div style="font-size:11px;color:#999;margin-bottom:4px"><span style="font-weight:600">リスク</span>　{s.get('risk','')}</div>
  <div style="font-size:12px;color:#1a4a8a;border-top:1px solid #f0f0f0;padding-top:6px">{s.get('action','')}{news_html}</div>
</div>'''
    return html


def build_holdings_table_midday(signals, hn_map):
    html = ""
    for s in signals:
        hn = hn_map.get(s["code"], {})
        news_html = ""
        for n in hn.get("news", [])[:1]:
            if n.get("url"):
                news_html = f'<div class="holding-news" style="margin-top:5px"><a href="{n["url"]}" target="_blank">📰 {n["title"][:45]}...</a></div>'
        html += f'''<div style="border:1px solid #ddd;border-radius:4px;padding:10px 12px;background:#fff;margin-bottom:8px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:7px;">
    <strong style="font-size:13px">{s['code']} {s['name']}</strong>
    {signal_badge(s['signal'], s['signal_label'])}
  </div>
  <div style="font-size:12px;color:#444;margin-bottom:4px;line-height:1.6"><span style="font-weight:600;color:#888">根拠</span>　{s.get('reason','')}</div>
  <div style="font-size:12px;color:#1a4a8a;border-top:1px solid #f0f0f0;padding-top:6px">{s.get('price_point','')}{news_html}</div>
</div>'''
    return html


def build_holdings_table_evening(signals, hn_map):
    html = ""
    for s in signals:
        hn = hn_map.get(s["code"], {})
        news_html = ""
        for n in hn.get("news", [])[:1]:
            if n.get("url"):
                news_html = f'<div class="holding-news" style="margin-top:5px"><a href="{n["url"]}" target="_blank">📰 {n["title"][:45]}...</a></div>'
        html += f'''<div style="border:1px solid #ddd;border-radius:4px;padding:10px 12px;background:#fff;margin-bottom:8px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:7px;">
    <strong style="font-size:13px">{s['code']} {s['name']}</strong>
    {signal_badge(s['signal'], s['signal_label'])}
  </div>
  <div style="font-size:12px;color:#444;margin-bottom:4px;line-height:1.6"><span style="font-weight:600;color:#888">本日</span>　{s.get('today_move','')}</div>
  <div style="font-size:12px;color:#1a4a8a;border-top:1px solid #f0f0f0;padding-top:6px">{s.get('strategy','')}{news_html}</div>
</div>'''
    return html


def build_holdings_table_weekly(signals, hn_map):
    html = ""
    for s in signals:
        hn = hn_map.get(s["code"], {})
        news_html = ""
        for n in hn.get("news", [])[:1]:
            if n.get("url"):
                news_html = f'<div class="holding-news" style="margin-top:5px"><a href="{n["url"]}" target="_blank">📰 {n["title"][:45]}...</a></div>'
        html += f'''<div style="border:1px solid #ddd;border-radius:4px;padding:10px 12px;background:#fff;margin-bottom:8px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:7px;">
    <strong style="font-size:13px">{s['code']} {s['name']}</strong>
    {signal_badge(s['signal'], s['signal_label'])}
  </div>
  <div style="font-size:12px;color:#444;margin-bottom:4px;line-height:1.6"><span style="font-weight:600;color:#888">今週</span>　{s.get('week_review','')}</div>
  <div style="font-size:12px;color:#1a4a8a;border-top:1px solid #f0f0f0;padding-top:6px">{s.get('next_week_strategy','')}{news_html}</div>
</div>'''
    return html


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
<div class="meta">対象：保有{len([])+5}銘柄　|　基準日：{subtitle}　|　作成：Warren<br>
本レポートは投資助言ではありません。売買は必ず自己責任で行ってください。</div>
{body}
<footer>Warren (Claude) · {date_id} · Powered by Anthropic</footer>
</div></body></html>"""


def generate_html_morning(data, market_news, holding_news, today_str, date_id, holdings, stock_data, histories):
    hn_map = {h["code"]: h for h in holding_news}
    bullets = "".join(f"<li>{b}</li>" for b in data.get("market_bullets", []))
    body = f"""
{build_portfolio_summary(holdings, stock_data)}
<h2>保有銘柄　株価・損益・テクニカル</h2>
{build_price_table(holdings, stock_data)}

<h2>チャート（60日・MA5/MA25・RSI）</h2>
{build_charts_section(holdings, histories, stock_data)}

<h2>市場環境（朝の概況）</h2>
<ul class="bullets">{bullets}</ul>

<h2>注目銘柄</h2>
{build_watchlist(data.get('watchlist', []))}

<h2>保有銘柄一覧（売買シグナル）</h2>
{build_holdings_table_morning(data.get('holdings_signals', []), hn_map)}

<h2>最新マーケットニュース</h2>
{build_news_links(data.get('news_summary', []), market_news)}"""
    return wrap_html(f"モーニングレポート（{today_str}）", f"{today_str} 朝8時", date_id, body)


def generate_html_midday(data, market_news, holding_news, today_str, date_id, holdings, stock_data, histories):
    hn_map = {h["code"]: h for h in holding_news}
    bullets = "".join(f"<li>{b}</li>" for b in data.get("zenba_bullets", []))
    body = f"""
{build_portfolio_summary(holdings, stock_data)}
<h2>保有銘柄　株価・損益・テクニカル（前場終了時点）</h2>
{build_price_table(holdings, stock_data)}

<h2>チャート（60日・MA5/MA25・RSI）</h2>
{build_charts_section(holdings, histories, stock_data)}

<h2>前場まとめ</h2>
<ul class="bullets">{bullets}</ul>

<h2>後場戦略</h2>
<p style="font-size:14px;padding:10px;background:#f9f9f9;border-left:3px solid #1a6b3a;">{data.get('koba_strategy','')}</p>

<h2>保有銘柄（後場シグナル）</h2>
{build_holdings_table_midday(data.get('holdings_koba', []), hn_map)}

<h2>後場に影響するニュース</h2>
{build_news_links(data.get('koba_news', []), market_news)}"""
    return wrap_html(f"前場引けレポート（{today_str}）", f"{today_str} 12:15", date_id, body)


def generate_html_evening(data, market_news, holding_news, today_str, date_id, holdings, stock_data, histories):
    hn_map = {h["code"]: h for h in holding_news}
    bullets = "".join(f"<li>{b}</li>" for b in data.get("today_bullets", []))
    body = f"""
{build_portfolio_summary(holdings, stock_data)}
<h2>保有銘柄　株価・損益・テクニカル（引け後）</h2>
{build_price_table(holdings, stock_data)}

<h2>チャート（60日・MA5/MA25・RSI）</h2>
{build_charts_section(holdings, histories, stock_data)}

<h2>本日の相場まとめ</h2>
<ul class="bullets">{bullets}</ul>

<h2>保有銘柄　本日動向・明日戦略</h2>
{build_holdings_table_evening(data.get('holdings_today', []), hn_map)}

<h2>明日の注目銘柄</h2>
{build_watchlist(data.get('tomorrow_watchlist', []))}

<h2>注目ニュース</h2>
{build_news_links(data.get('evening_news', []), market_news)}"""
    return wrap_html(f"引けレポート（{today_str}）", f"{today_str} 18:00", date_id, body)


def generate_html_weekly(data, market_news, holding_news, today_str, date_id, holdings, stock_data, histories):
    hn_map = {h["code"]: h for h in holding_news}
    best = data.get("best_performer", {})
    worst = data.get("worst_performer", {})
    strategies = "".join(f"<li>{s}</li>" for s in data.get("key_strategies", []))

    best_box = f"""<div class="highlight-box">
      <strong>🏆 今週のベスト：{best.get('code','')} {best.get('name','')}</strong>
      <div style="font-size:13px;margin-top:4px;color:#333">{best.get('comment','')}</div>
    </div>""" if best else ""

    worst_box = f"""<div class="highlight-box red">
      <strong>📉 今週のワースト：{worst.get('code','')} {worst.get('name','')}</strong>
      <div style="font-size:13px;margin-top:4px;color:#333">{worst.get('comment','')}</div>
    </div>""" if worst else ""

    trend_b64 = build_portfolio_trend_chart()
    trend_html = f'<img src="data:image/png;base64,{trend_b64}" style="width:100%;height:auto;display:block;" alt="portfolio trend">' \
                 if trend_b64 else '<p style="color:#999;font-size:13px">データ蓄積中（来週以降に表示）</p>'

    body = f"""
{build_portfolio_summary(holdings, stock_data)}

<h2>ポートフォリオ推移</h2>
<div style="border:1px solid #ddd;border-radius:4px;padding:10px;background:#fff;margin-bottom:8px;">
{trend_html}
<p class="tech-note">青線=評価額　灰破線=取得金額　下段=日次損益</p>
</div>

<h2>週間パフォーマンス　株価・損益</h2>
{build_price_table(holdings, stock_data)}

<h2>チャート（60日・MA5/MA25・RSI）</h2>
{build_charts_section(holdings, histories, stock_data)}

<h2>今週のサマリー</h2>
<p style="font-size:14px;padding:10px;background:#f9f9f9;border-left:3px solid #1a6b3a;">{data.get('week_summary','')}</p>
{best_box}{worst_box}

<h2>保有銘柄　今週の動き・来週戦略</h2>
{build_holdings_table_weekly(data.get('holdings_weekly', []), hn_map)}

<h2>来週の市場見通し</h2>
<p style="font-size:14px;padding:10px;background:#f9f9f9;border-left:3px solid #1a4a8a;">{data.get('market_outlook','')}</p>

<h2>来週の重要戦略ポイント</h2>
<ul class="bullets">{strategies}</ul>

<h2>今週の注目ニュース</h2>
{build_news_links(data.get('evening_news', []) if data.get('evening_news') else [{"headline": n["title"], "impact": ""} for n in market_news[:5]], market_news)}"""
    return wrap_html(f"週次レポート（{today_str}）", f"週次 {today_str}", date_id, body)


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

    print("株価データ取得中...")
    stock_data, histories = fetch_stock_data(holdings)

    print("チャート生成中...")
    # チャートはgenerate_html_*内で生成されるため、historiesを渡すだけでOK

    print("ニュース取得中...")
    market_news = fetch_all_news()
    print(f"マーケットニュース: {len(market_news)}件")
    holding_news = fetch_holding_news(holdings)

    print("Claude APIでレポート生成中...")
    if REPORT_TYPE == "morning":
        data = generate_morning(market_news, holding_news, holdings, today_str, stock_data)
        html = generate_html_morning(data, market_news, holding_news, today_str, date_id, holdings, stock_data, histories)
        filename = f"report-{date_id}-morning.html"
        label = "モーニングレポート"
    elif REPORT_TYPE == "midday":
        data = generate_midday(market_news, holding_news, holdings, today_str, stock_data)
        html = generate_html_midday(data, market_news, holding_news, today_str, date_id, holdings, stock_data, histories)
        filename = f"report-{date_id}-midday.html"
        label = "前場引けレポート"
    elif REPORT_TYPE == "weekly":
        data = generate_weekly(market_news, holding_news, holdings, today_str, stock_data)
        html = generate_html_weekly(data, market_news, holding_news, today_str, date_id, holdings, stock_data, histories)
        filename = f"report-{date_id}-weekly.html"
        label = "週次レポート"
    else:
        data = generate_evening(market_news, holding_news, holdings, today_str, stock_data)
        html = generate_html_evening(data, market_news, holding_news, today_str, date_id, holdings, stock_data, histories)
        filename = f"report-{date_id}-evening.html"
        label = "引けレポート"

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML保存: {filename}")

    save_portfolio_snapshot(holdings, stock_data, date_id)

    report_url = f"{PAGES_URL}/{filename}"
    message = f"📊 Warren {label} {today_str}\n\nレポートはこちら👇\n{report_url}"
    send_line(message)
    print(f"完了: {report_url}")
