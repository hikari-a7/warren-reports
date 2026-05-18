#!/usr/bin/env python3
"""
Warren Price Alert - 取引時間中15分ごとに条件チェックしてLINE通知
"""

import os
import json
import urllib.request
from datetime import datetime, timezone, timedelta

LINE_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_USER_ID = os.environ["LINE_USER_ID"]
JST = timezone(timedelta(hours=9))
TODAY = datetime.now(JST).strftime("%Y-%m-%d")
ALERT_LOG = "alert_log.json"


def load_holdings():
    with open("holdings.json", encoding="utf-8") as f:
        return json.load(f).get("holdings", [])


def load_alert_log():
    try:
        with open(ALERT_LOG, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_alert_log(log):
    with open(ALERT_LOG, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def fetch_stock_data(holdings):
    import yfinance as yf
    result = {}
    for h in holdings:
        code = h["code"]
        try:
            hist = yf.Ticker(f"{code}.T").history(period="3mo")
            if hist.empty or len(hist) < 2:
                result[code] = None
                continue
            closes = hist["Close"].dropna()
            volumes = hist["Volume"].dropna()
            latest = float(closes.iloc[-1])
            prev = float(closes.iloc[-2])
            change_pct = (latest - prev) / prev * 100
            vol_avg = float(volumes.iloc[-21:-1].mean()) if len(volumes) >= 21 else float(volumes.mean())
            vol_ratio = float(volumes.iloc[-1]) / vol_avg if vol_avg > 0 else 1.0
            delta = closes.diff().dropna()
            gain = float(delta.clip(lower=0).tail(14).mean())
            loss = float((-delta.clip(upper=0)).tail(14).mean())
            rsi = 100 - (100 / (1 + gain / loss)) if loss > 0 else 100.0
            cost = h.get("cost")
            shares = h.get("shares", 0)
            pnl_pct = round((latest - cost) / cost * 100, 2) if cost else None
            pnl_total = round((latest - cost) * shares) if cost else None
            result[code] = {
                "price": round(latest, 1),
                "change_pct": round(change_pct, 2),
                "volume_ratio": round(vol_ratio, 1),
                "rsi": round(rsi, 1),
                "pnl_pct": pnl_pct,
                "pnl_total": pnl_total,
            }
            print(f"  {code}: ¥{result[code]['price']} {result[code]['change_pct']:+.2f}% RSI={result[code]['rsi']}")
        except Exception as e:
            print(f"  {code} 取得エラー: {e}")
            result[code] = None
    return result


def check_earnings_alerts(holdings, log):
    try:
        import yfinance as yf
        from datetime import date
        alerts = []
        today = date.today()
        for h in holdings:
            code = h["code"]
            try:
                cal = yf.Ticker(f"{code}.T").calendar
                if cal is None:
                    continue
                ed = None
                if hasattr(cal, "loc") and "Earnings Date" in cal.index:
                    ed = cal.loc["Earnings Date"].iloc[0]
                elif hasattr(cal, "columns") and "Earnings Date" in cal.columns:
                    ed = cal["Earnings Date"].iloc[0]
                if ed is None:
                    continue
                if hasattr(ed, "date"):
                    ed = ed.date()
                elif hasattr(ed, "to_pydatetime"):
                    ed = ed.to_pydatetime().date()
                days = (ed - today).days
                if 0 <= days <= 7:
                    key = f"earnings_{code}_{ed}"
                    if log.get(key) != TODAY:
                        label = "本日" if days == 0 else f"あと{days}日"
                        alerts.append(
                            f"📅 決算アラート\n"
                            f"{code} {h['name']}\n"
                            f"決算発表：{ed.strftime('%m/%d')}（{label}）\n"
                            f"決算前後は価格変動に注意"
                        )
                        log[key] = TODAY
            except Exception as e:
                print(f"  決算情報エラー {code}: {e}")
    except Exception as e:
        print(f"決算チェックエラー: {e}")
        alerts = []
    return alerts


def check_alerts(holdings, stock_data, log):
    alerts = []
    now_str = datetime.now(JST).strftime("%m/%d %H:%M")

    for h in holdings:
        code = h["code"]
        d = stock_data.get(code)
        if not d:
            continue

        def alerted(key):
            return log.get(f"{code}_{key}") == TODAY

        def mark(key):
            log[f"{code}_{key}"] = TODAY

        chg = d["change_pct"]
        rsi = d["rsi"]
        vol = d["volume_ratio"]
        price = d["price"]
        pnl_pct = d.get("pnl_pct")
        pnl_total = d.get("pnl_total")

        if chg <= -5 and not alerted("drop5"):
            alerts.append(
                f"📉 急落アラート\n"
                f"{code} {h['name']}\n"
                f"前日比 {chg:+.2f}%\n"
                f"現在値 ¥{price:,.1f}"
            )
            mark("drop5")

        if chg >= 7 and not alerted("surge7"):
            alerts.append(
                f"🚀 急騰アラート\n"
                f"{code} {h['name']}\n"
                f"前日比 +{chg:.2f}%\n"
                f"現在値 ¥{price:,.1f}\n"
                f"利確ラインの確認を"
            )
            mark("surge7")

        if vol >= 3.0 and not alerted("vol3x"):
            alerts.append(
                f"📊 出来高急増アラート\n"
                f"{code} {h['name']}\n"
                f"出来高が通常の {vol:.1f}倍\n"
                f"何か動きがある可能性あり"
            )
            mark("vol3x")

        if rsi <= 28 and not alerted("rsi_low"):
            alerts.append(
                f"⭐ RSI売られすぎアラート\n"
                f"{code} {h['name']}\n"
                f"RSI = {rsi}（売られすぎ圏）\n"
                f"短期反発の可能性、買い増し検討を"
            )
            mark("rsi_low")

        if rsi >= 72 and not alerted("rsi_high"):
            alerts.append(
                f"⚠️ RSI買われすぎアラート\n"
                f"{code} {h['name']}\n"
                f"RSI = {rsi}（買われすぎ圏）\n"
                f"利確・一部売り検討を"
            )
            mark("rsi_high")

        if pnl_pct is not None and pnl_pct <= -15 and not alerted("loss15"):
            alerts.append(
                f"🔴 損切りラインアラート\n"
                f"{code} {h['name']}\n"
                f"含み損 {pnl_pct:.1f}%（¥{pnl_total:,}）\n"
                f"損切りラインを超えています"
            )
            mark("loss15")

        # 目標株価到達
        target = h.get("target")
        if target and price >= target and not alerted("target"):
            dist = round((price - target) / target * 100, 1)
            alerts.append(
                f"🎯 目標株価到達！\n"
                f"{code} {h['name']}\n"
                f"現在値 ¥{price:,.1f}（目標 ¥{target:,}、+{dist}%超過）\n"
                f"利確を検討してください"
            )
            mark("target")

        # 損切り株価ライン
        stop = h.get("stop_loss")
        if stop and price <= stop and not alerted("stop_price"):
            dist = round((price - stop) / stop * 100, 1)
            alerts.append(
                f"🔴 損切り株価ライン到達\n"
                f"{code} {h['name']}\n"
                f"現在値 ¥{price:,.1f}（損切ライン ¥{stop:,}）\n"
                f"損切りの実行を検討してください"
            )
            mark("stop_price")

    return alerts


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
    now_str = datetime.now(JST).strftime("%m/%d %H:%M")
    print(f"アラートチェック開始: {now_str}")

    holdings = load_holdings()
    print("株価取得中...")
    stock_data = fetch_stock_data(holdings)

    log = load_alert_log()
    alerts = check_alerts(holdings, stock_data, log)

    print("決算スケジュール確認中...")
    alerts += check_earnings_alerts(holdings, log)

    save_alert_log(log)

    if alerts:
        header = f"⚡ Warren アラート\n{now_str}\n" + "─" * 20
        message = header + "\n\n" + "\n\n".join(alerts)
        send_line(message)
        print(f"{len(alerts)}件のアラートを送信しました")
    else:
        print("アラート条件なし")
