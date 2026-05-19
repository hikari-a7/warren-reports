#!/usr/bin/env python3
"""
Warren Screener - 宇宙全体をスキャンして買い候補を抽出し投資メモを生成
"""

import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

import anthropic

JST = timezone(timedelta(hours=9))
LINE_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")
PAGES_URL = "https://hikari-a7.github.io/warren-reports"


# ── データ取得 ──────────────────────────────────────────────────────

def load_universe():
    with open("universe.json", encoding="utf-8") as f:
        return json.load(f)


def all_stocks(universe):
    seen, stocks = set(), []
    for theme in universe["themes"]:
        for s in theme["stocks"]:
            if s["code"] not in seen:
                seen.add(s["code"])
                stocks.append({**s, "theme_id": theme["id"], "theme_name": theme["name"]})
    return stocks


def fetch_universe_data(stocks):
    import yfinance as yf
    result = {}
    codes = [s["code"] for s in stocks]
    print(f"  {len(codes)}銘柄を取得中...")

    for code in codes:
        try:
            hist = yf.Ticker(f"{code}.T").history(period="3mo")
            if hist.empty or len(hist) < 10:
                continue
            closes = hist["Close"].dropna()
            volumes = hist["Volume"].dropna()

            latest  = float(closes.iloc[-1])
            prev    = float(closes.iloc[-2])
            week_ago = float(closes.iloc[-6]) if len(closes) >= 6 else prev

            change_pct = (latest - prev) / prev * 100
            week_pct   = (latest - week_ago) / week_ago * 100

            vol_avg   = float(volumes.iloc[-21:-1].mean()) if len(volumes) >= 21 else float(volumes.mean())
            vol_ratio = float(volumes.iloc[-1]) / vol_avg if vol_avg > 0 else 1.0

            ma5  = float(closes.tail(5).mean())  if len(closes) >= 5  else None
            ma25 = float(closes.tail(25).mean()) if len(closes) >= 25 else None
            ma75 = float(closes.tail(75).mean()) if len(closes) >= 75 else None

            delta = closes.diff().dropna()
            gain  = float(delta.clip(lower=0).tail(14).mean())
            loss  = float((-delta.clip(upper=0)).tail(14).mean())
            rsi   = 100 - (100 / (1 + gain / loss)) if loss > 0 else 100.0

            high_52w = float(closes.tail(252).max()) if len(closes) >= 52 else float(closes.max())
            vs_high  = (latest - high_52w) / high_52w * 100

            result[code] = {
                "price":      round(latest, 1),
                "change_pct": round(change_pct, 2),
                "week_pct":   round(week_pct, 2),
                "vol_ratio":  round(vol_ratio, 1),
                "ma5":        round(ma5, 1)  if ma5  else None,
                "ma25":       round(ma25, 1) if ma25 else None,
                "ma75":       round(ma75, 1) if ma75 else None,
                "rsi":        round(rsi, 1),
                "vs_ma25":    round((latest - ma25) / ma25 * 100, 1) if ma25 else None,
                "vs_high_52w":round(vs_high, 1),
            }
        except Exception as e:
            print(f"    {code} エラー: {e}")

    print(f"  取得完了: {len(result)}/{len(codes)}件")
    return result


# ── スコアリング ────────────────────────────────────────────────────

def score_stock(d):
    """スイング向けスコア（高いほど良い）"""
    score = 0

    # RSIスコア: 35-60が最良（売られすぎ回復 or 上昇中）
    rsi = d.get("rsi", 50)
    if 30 <= rsi <= 55:
        score += 30
    elif 55 < rsi <= 65:
        score += 20
    elif rsi < 30:
        score += 25  # 売られすぎ反発狙い

    # 出来高スコア
    vol = d.get("vol_ratio", 1.0)
    if vol >= 3.0:
        score += 25
    elif vol >= 2.0:
        score += 18
    elif vol >= 1.5:
        score += 12

    # MA25トレンド
    vs25 = d.get("vs_ma25")
    if vs25 is not None:
        if 0 < vs25 <= 10:
            score += 20  # MA25より少し上 = 上昇トレンド入り
        elif vs25 > 10:
            score += 10  # 上がりすぎは減点
        elif -5 <= vs25 < 0:
            score += 15  # MA25付近でサポート

    # 週間モメンタム
    week = d.get("week_pct", 0)
    if 2 <= week <= 10:
        score += 15
    elif week > 10:
        score += 8
    elif week < -5:
        score -= 10

    # 52週高値からの距離（下がりすぎは注意、でも余地あり）
    vs_high = d.get("vs_high_52w", -20)
    if -30 <= vs_high <= -5:
        score += 10  # 高値から5〜30%の押し目
    elif vs_high > -5:
        score += 5   # 高値圏、まだ上がる可能性

    return score


# ── テーマレーダー ──────────────────────────────────────────────────

def build_theme_radar(universe, stock_data):
    themes = []
    for theme in universe["themes"]:
        week_changes = []
        day_changes  = []
        for s in theme["stocks"]:
            d = stock_data.get(s["code"])
            if d:
                week_changes.append(d["week_pct"])
                day_changes.append(d["change_pct"])

        if not week_changes:
            continue

        avg_week = round(sum(week_changes) / len(week_changes), 2)
        avg_day  = round(sum(day_changes)  / len(day_changes),  2)

        # モメンタム判定
        if avg_week >= 5:
            momentum = "hot"
        elif avg_week >= 1:
            momentum = "rising"
        elif avg_week >= -2:
            momentum = "neutral"
        elif avg_week >= -5:
            momentum = "cooling"
        else:
            momentum = "cold"

        themes.append({
            "id":        theme["id"],
            "name":      theme["name"],
            "icon":      theme["icon"],
            "avg_week":  avg_week,
            "avg_day":   avg_day,
            "momentum":  momentum,
            "stock_count": len(week_changes),
        })

    themes.sort(key=lambda x: x["avg_week"], reverse=True)
    return themes


# ── 候補抽出 ────────────────────────────────────────────────────────

def pick_candidates(stocks, stock_data, top_n=5):
    scored = []
    for s in stocks:
        d = stock_data.get(s["code"])
        if not d:
            continue
        sc = score_stock(d)
        scored.append({**s, **d, "score": sc})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_n]


# ── 投資メモ生成 ────────────────────────────────────────────────────

def fetch_news(code, name):
    query = urllib.parse.quote(f"{name} {code} 株価")
    url = f"https://news.google.com/rss/search?q={query}&hl=ja&gl=JP&ceid=JP:ja"
    items = []
    try:
        import xml.etree.ElementTree as ET
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            tree = ET.fromstring(resp.read().decode("utf-8", errors="replace"))
            for item in tree.findall(".//item")[:3]:
                t = item.find("title")
                if t is not None and t.text:
                    items.append(t.text.split(" - ")[0].strip())
    except Exception:
        pass
    return items


def generate_investment_memo(candidate, today_str):
    news = fetch_news(candidate["code"], candidate["name"])
    news_str = "\n".join(f"- {n}" for n in news) if news else "- ニュースなし"

    prompt = f"""あなたは株式投資の専門家Warrenです。以下のデータをもとに、スイング投資（数週間〜数ヶ月）向けの投資メモを作成してください。

## 銘柄情報
- コード: {candidate['code']}
- 銘柄名: {candidate['name']}
- セクター: {candidate.get('theme_name', '')}
- 現在株価: ¥{candidate['price']}
- 前日比: {candidate['change_pct']:+.2f}%
- 週間騰落: {candidate['week_pct']:+.2f}%
- RSI: {candidate['rsi']}
- 出来高比: {candidate['vol_ratio']}x
- MA25比: {candidate.get('vs_ma25', 'N/A')}%
- 52週高値比: {candidate.get('vs_high_52w', 'N/A')}%
- スクリーナースコア: {candidate['score']}点

## 最新ニュース
{news_str}

## 作成日
{today_str}

以下のJSON形式のみで出力（説明文なし）：
{{
  "reason": "なぜ今この銘柄に注目するか（テーマ・テクニカル・需給を組み合わせて）2文以内",
  "catalyst": "上昇のカタリスト（決算・テーマ・需給）1文",
  "risk": "主なリスク・懸念点1文",
  "entry_low": エントリー下限株価（数値のみ、現在値の0〜5%下）,
  "entry_high": エントリー上限株価（数値のみ、現在値の0〜3%上）,
  "target_price": 目標株価（数値のみ、エントリーから+20〜40%が目安）,
  "target_pct": 目標上昇率（数値のみ）,
  "stop_price": 損切株価（数値のみ、エントリーから-8%が目安）,
  "stop_pct": 損切率（数値のみ、例：-8）,
  "hold_period": "想定保有期間（例：2〜4週間）"
}}
JSONのみ。"""

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    text = resp.content[0].text.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


# ── watchlist保存 ───────────────────────────────────────────────────

def save_results(candidates_with_memos, theme_radar, date_id):
    # watchlist.json
    watchlist = {
        "updated": date_id,
        "candidates": candidates_with_memos,
    }
    with open("watchlist.json", "w", encoding="utf-8") as f:
        json.dump(watchlist, f, ensure_ascii=False, indent=2)
    print(f"watchlist.json 保存: {len(candidates_with_memos)}件")

    # theme_radar.json
    radar = {"updated": date_id, "themes": theme_radar}
    with open("theme_radar.json", "w", encoding="utf-8") as f:
        json.dump(radar, f, ensure_ascii=False, indent=2)
    print(f"theme_radar.json 保存: {len(theme_radar)}テーマ")


# ── LINE通知 ────────────────────────────────────────────────────────

def send_line_summary(candidates, theme_radar, date_id):
    if not LINE_TOKEN or not LINE_USER_ID:
        return

    # テーマトップ3
    hot = [t for t in theme_radar if t["momentum"] in ("hot", "rising")][:3]
    theme_str = "\n".join(f"  {t['icon']} {t['name']} 週間{t['avg_week']:+.1f}%" for t in hot)

    # 候補トップ3
    cand_str = ""
    for c in candidates[:3]:
        status = "🟢今すぐ" if c.get("status") == "ready" else "⏳待機"
        cand_str += f"\n  {status} {c['code']} {c['name']} ¥{c['price']:,}\n"
        cand_str += f"    目標¥{c.get('target_price','—'):,} / 損切¥{c.get('stop_price','—'):,}\n"

    msg = (
        f"🔍 Warren スクリーニング結果 {date_id}\n"
        f"{'─'*22}\n\n"
        f"🔥 熱いテーマ\n{theme_str}\n\n"
        f"📋 買い候補 TOP3{cand_str}\n"
        f"詳細 → {PAGES_URL}/watchlist.html"
    )

    payload = json.dumps({
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": msg}]
    }).encode()
    req = urllib.request.Request(
        "https://api.line.me/v2/bot/message/push",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"},
        method="POST"
    )
    with urllib.request.urlopen(req) as r:
        print(f"LINE通知送信: {r.status}")


# ── メイン ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    now = datetime.now(JST)
    today_str = now.strftime("%Y-%m-%d")
    print(f"Warren Screener 開始: {now.strftime('%Y-%m-%d %H:%M JST')}")

    universe = load_universe()
    stocks   = all_stocks(universe)
    print(f"ユニバース: {len(stocks)}銘柄")

    print("株価データ取得中...")
    stock_data = fetch_universe_data(stocks)

    print("テーマレーダー計算中...")
    theme_radar = build_theme_radar(universe, stock_data)
    for t in theme_radar:
        print(f"  {t['icon']} {t['name']}: 週間{t['avg_week']:+.1f}% [{t['momentum']}]")

    print("候補抽出中...")
    top_candidates = pick_candidates(stocks, stock_data, top_n=5)
    print(f"  上位{len(top_candidates)}件抽出")
    for c in top_candidates:
        print(f"  [{c['score']}点] {c['code']} {c['name']} RSI={c['rsi']} vol={c['vol_ratio']}x")

    print("投資メモ生成中 (Claude)...")
    candidates_with_memos = []
    for c in top_candidates:
        try:
            memo = generate_investment_memo(c, today_str)
            merged = {
                "code":        c["code"],
                "name":        c["name"],
                "theme_id":    c.get("theme_id", ""),
                "theme_name":  c.get("theme_name", ""),
                "price":       c["price"],
                "change_pct":  c["change_pct"],
                "week_pct":    c["week_pct"],
                "rsi":         c["rsi"],
                "vol_ratio":   c["vol_ratio"],
                "vs_ma25":     c.get("vs_ma25"),
                "score":       c["score"],
                "status":      "watch",
                "added_date":  today_str,
                **memo,
            }
            # ステータス判定
            lo = merged.get("entry_low", 0)
            hi = merged.get("entry_high", 0)
            pr = merged["price"]
            if lo and hi and lo <= pr <= hi:
                merged["status"] = "ready"
            elif hi and pr <= hi * 1.05:
                merged["status"] = "near"

            candidates_with_memos.append(merged)
            print(f"  ✓ {c['code']} {c['name']} メモ生成完了")
        except Exception as e:
            print(f"  ✗ {c['code']} メモ生成エラー: {e}")

    save_results(candidates_with_memos, theme_radar, today_str)
    send_line_summary(candidates_with_memos, theme_radar, today_str)
    print("完了")
