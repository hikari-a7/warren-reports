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


def main():
    now = datetime.now(JST)
    print(f"positions.json 更新開始: {now.strftime('%Y-%m-%d %H:%M JST')}")

    data = load_positions()
    codes = [p["code"] for p in data["positions"]]

    print("株価取得中...")
    prices = fetch_prices(codes)

    for pos in data["positions"]:
        code = pos["code"]
        price = prices.get(code)
        update_position(pos, price)

    data["last_updated"] = now.strftime("%Y-%m-%d %H:%M JST")
    save_positions(data)
    print(f"更新完了: {now.strftime('%H:%M')}")


if __name__ == "__main__":
    main()
