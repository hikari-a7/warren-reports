#!/usr/bin/env python3
"""
Warren Position Updater - yfinanceで現在株価を取得しpositions.jsonを更新
"""

import json
import sys
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))


def load_positions():
    with open("positions.json", encoding="utf-8") as f:
        return json.load(f)


def save_positions(data):
    with open("positions.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def fetch_prices(codes):
    import yfinance as yf
    result = {}
    for code in codes:
        try:
            hist = yf.Ticker(f"{code}.T").history(period="5d")
            if hist.empty:
                print(f"  {code}: データなし")
                result[code] = None
                continue
            closes = hist["Close"].dropna()
            price = round(float(closes.iloc[-1]), 1)
            result[code] = price
            print(f"  {code}: ¥{price:,.1f}")
        except Exception as e:
            print(f"  {code} エラー: {e}")
            result[code] = None
    return result


def update_position(pos, price):
    if price is None:
        return pos
    shares = pos["shares"]
    entry = pos["entry_price"]
    pos["current_price"] = price
    pos["current_value"] = round(price * shares)
    pos["pnl_per"] = round(price - entry, 1)
    pos["pnl_pct"] = round((price - entry) / entry * 100, 2)
    pos["pnl_total"] = round((price - entry) * shares)
    # ノート自動更新
    target = pos.get("target_price", 0)
    stop = pos.get("stop_price", 0)
    if target and price >= target:
        pos["note"] = f"🎯 目標+{pos['target_pct']}%超過。利確を検討"
    elif stop and price <= stop and pos.get("status") != "watch":
        pos["note"] = f"🔴 損切りライン到達 ¥{stop:,}"
    return pos


def load_watchlist():
    try:
        with open("watchlist.json", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"candidates": []}


def save_watchlist(data):
    with open("watchlist.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def update_watchlist_prices(wl_data, prices):
    for c in wl_data.get("candidates", []):
        code = c["code"]
        price = prices.get(code)
        if price is None:
            continue
        c["current_price"] = price
        lo = c.get("entry_low", 0)
        hi = c.get("entry_high", float("inf"))
        if lo <= price <= hi:
            c["status"] = "ready"
        elif hi > 0 and price <= hi * 1.05:
            c["status"] = "near"
        else:
            c["status"] = "watch"
    return wl_data


def main():
    now = datetime.now(JST)
    print(f"positions.json 更新開始: {now.strftime('%Y-%m-%d %H:%M JST')}")

    data = load_positions()
    wl_data = load_watchlist()

    pos_codes = [p["code"] for p in data["positions"]]
    wl_codes  = [c["code"] for c in wl_data.get("candidates", [])]
    all_codes = list(set(pos_codes + wl_codes))

    print("株価取得中...")
    prices = fetch_prices(all_codes)

    for pos in data["positions"]:
        update_position(pos, prices.get(pos["code"]))

    wl_data = update_watchlist_prices(wl_data, prices)

    data["last_updated"] = now.strftime("%Y-%m-%d %H:%M JST")
    save_positions(data)
    save_watchlist(wl_data)
    print(f"更新完了: {now.strftime('%H:%M')}")


if __name__ == "__main__":
    main()
