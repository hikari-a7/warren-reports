#!/usr/bin/env python3
"""
Warren Positions Updater
holdings.jsonから現在株価を取得しpositions.jsonを更新、LINEに通知する
"""

import json
import os
import urllib.request
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
LINE_TOKEN   = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")
PAGES_URL    = "https://hikari-a7.github.io/warren-reports"


def update_positions():
    import yfinance as yf

    now = datetime.now(JST)
    print(f"Warren Positions Update 開始: {now.strftime('%Y-%m-%d %H:%M JST')}")

    try:
        with open("holdings.json", encoding="utf-8") as f:
            holdings_data = json.load(f)
    except FileNotFoundError:
        print("holdings.json が見つかりません。終了します。")
        return

    holdings = holdings_data.get("holdings", [])
    if not holdings:
        print("保有銘柄なし。終了します。")
        return

    # 既存positions.jsonから引き継ぐ情報
    existing_notes = {}
    closed_trades  = []
    monthly_target = 1500000
    month = now.strftime("%Y-%m")

    try:
        with open("positions.json", encoding="utf-8") as f:
            existing = json.load(f)
        closed_trades  = existing.get("closed_trades", [])
        monthly_target = existing.get("monthly_target", monthly_target)
        month          = existing.get("month", month)
        for p in existing.get("positions", []):
            existing_notes[p["code"]] = p.get("note", "")
    except Exception:
        pass

    # yfinanceで現在株価を取得
    codes   = [h["code"] for h in holdings]
    tickers = [f"{c}.T" for c in codes]
    prices  = {}

    print("株価取得中...")
    try:
        raw = yf.download(
            tickers, period="5d", group_by="ticker",
            auto_adjust=True, progress=False, threads=True
        )
        for code, ticker in zip(codes, tickers):
            try:
                closes = raw[ticker]["Close"].dropna() if len(tickers) > 1 else raw["Close"].dropna()
                if len(closes) > 0:
                    prices[code] = float(closes.iloc[-1])
                    print(f"  {code}: ¥{prices[code]:,.0f}")
            except Exception as e:
                print(f"  {code} 取得失敗: {e}")
    except Exception as e:
        print(f"株価取得エラー: {e}")

    # positions生成
    now_str   = now.strftime("%Y-%m-%d %H:%M JST")
    positions = []

    for h in holdings:
        code      = h["code"]
        cost      = h["cost"]
        shares    = h["shares"]
        target    = h.get("target")
        stop_loss = h.get("stop_loss")
        note      = h.get("note", existing_notes.get(code, ""))

        current_price = prices.get(code)
        if current_price is None:
            print(f"⚠ {code} 株価取得できず。スキップ。")
            continue

        current_value = round(current_price * shares)
        pnl_per   = round(current_price - cost, 1)
        pnl_pct   = round((current_price - cost) / cost * 100, 2)
        pnl_total = round(pnl_per * shares)
        target_pct = round((target    - cost) / cost * 100, 1) if target    else 20
        stop_pct   = round((stop_loss - cost) / cost * 100, 1) if stop_loss else -8

        positions.append({
            "code":          code,
            "name":          h["name"],
            "shares":        shares,
            "entry_price":   cost,
            "current_price": round(current_price, 1),
            "current_value": current_value,
            "pnl_per":       pnl_per,
            "pnl_pct":       pnl_pct,
            "pnl_total":     pnl_total,
            "target_pct":    target_pct,
            "target_price":  target,
            "stop_pct":      stop_pct,
            "stop_price":    stop_loss,
            "status":        "holding",
            "note":          note,
        })

    result = {
        "month":          month,
        "monthly_target": monthly_target,
        "last_updated":   now_str,
        "positions":      positions,
        "closed_trades":  closed_trades,
        "watchlist":      [],
    }

    with open("positions.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"positions.json 更新完了: {len(positions)}銘柄")
    send_line_update(positions, now_str)


def send_line_update(positions, now_str):
    if not LINE_TOKEN or not LINE_USER_ID:
        return

    total_pnl = sum(p["pnl_total"] for p in positions)
    total_val = sum(p["current_value"] for p in positions)

    lines = [f"📊 Warren 大引け更新 {now_str}", "─" * 22]
    for p in positions:
        arrow = "📈" if p["pnl_pct"] >= 0 else "📉"
        pnl_sign = "+" if p["pnl_total"] >= 0 else ""
        lines.append(f"{arrow} {p['name']}")
        lines.append(f"   ¥{p['current_price']:,.0f}  {p['pnl_pct']:+.1f}%  ({pnl_sign}¥{p['pnl_total']:,})")

    lines.append("─" * 22)
    total_sign = "+" if total_pnl >= 0 else ""
    lines.append(f"含み損益合計: {total_sign}¥{total_pnl:,}")
    lines.append(f"評価額合計:   ¥{total_val:,}")
    lines.append(f"\n詳細 → {PAGES_URL}/dashboard.html")

    msg = "\n".join(lines)
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
    try:
        with urllib.request.urlopen(req) as r:
            print(f"LINE通知送信: {r.status}")
    except Exception as e:
        print(f"LINE通知エラー: {e}")


if __name__ == "__main__":
    update_positions()
