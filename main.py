"""
DeltaBot Pro - Cloud Backend
Fetches real prices from Delta Exchange server-side (no CORS issues)
Runs the scanner 24/7
API keys saved permanently to config.json
"""
from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS
import requests, threading, time, json, os
from datetime import datetime

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')

DEFAULT_CONFIG = {
    "trigger_pct":  350,
    "tp_pct":       50,
    "sl_pct":       100,
    "capital":      5,
    "leverage":     20,
    "paper_trading":True,
    "api_key":      "",
    "api_secret":   "",
    "exchange":     "india",
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                saved = json.load(f)
            return {**DEFAULT_CONFIG, **saved}
        except:
            pass
    return dict(DEFAULT_CONFIG)

def save_config(cfg):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(cfg, f, indent=2)

config = load_config()
print(f"[CONFIG] Loaded. API key: {'✓ SET' if config.get('api_key') else 'not set'}")

# ── Shared state ─────────────────────────────────────────────
state = {
    "tickers":       {},
    "baselines":     {},
    "active_trades": {},
    "closed_trades": [],
    "signals_today": 0,
    "total_pnl":     0.0,
    "last_scan":     None,
    "connected":     False,
}

def get_delta_urls():
    base = "india" if config.get("exchange","india") == "india" else "global"
    urls = [
        f"https://api.india.delta.exchange/v2/tickers?contract_types=perpetual_futures",
        f"https://api.delta.exchange/v2/tickers?contract_types=perpetual_futures",
    ]
    if base == "global":
        urls = urls[::-1]
    return urls

def fetch_prices():
    """Fetch all perpetual futures prices from Delta Exchange."""
    urls = [
        "https://api.india.delta.exchange/v2/tickers",
        "https://api.delta.exchange/v2/tickers",
        "https://api.india.delta.exchange/v2/tickers?contract_types=perpetual_futures",
        "https://api.delta.exchange/v2/tickers?contract_types=perpetual_futures",
    ]
    browser_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Origin': 'https://www.delta.exchange',
        'Referer': 'https://www.delta.exchange/',
        'Connection': 'keep-alive',
    }
    for url in urls:
        for hdrs in [browser_headers, {"Accept":"application/json","User-Agent":"python-requests/2.31.0"}]:
            try:
                r = requests.get(url, timeout=15, headers=hdrs)
                print(f"[FETCH] {url[:55]} -> {r.status_code}")
                if r.status_code != 200:
                    continue
                data = r.json()
                if not data.get("success"):
                    continue
                results = data.get("result", [])
                tickers = {}
                for t in results:
                    sym = t.get("symbol","")
                    if not sym or not sym.endswith("USDT"):
                        continue
                    # Skip stock tokens (they end in X like GOOGLX, TSLAX)
                    base = sym.replace("USDT","")
                    if base.endswith("X") and len(base) > 4:
                        continue
                    # Skip if contract type is not perpetual
                    contract_type = t.get("contract_type","")
                    if contract_type and contract_type not in ["perpetual_futures","perpetual"]:
                        continue
                    price = float(t.get("close") or t.get("mark_price") or t.get("last_price") or 0)
                    if price <= 0:
                        continue
                    open_price = float(t.get("open") or price)
                    tickers[sym] = {
                        "symbol":    sym,
                        "price":     price,
                        "open":      open_price,
                        "high":      float(t.get("high") or price),
                        "low":       float(t.get("low")  or price),
                        "volume":    float(t.get("volume") or t.get("turnover_usd") or 0),
                        "mark_price":float(t.get("mark_price") or price),
                    }
                if tickers:
                    print(f"[FETCH] ✓ {len(tickers)} symbols loaded")
                    return tickers
            except Exception as e:
                print(f"[FETCH] {url[:40]}: {e}")
    print("[FETCH] ✗ All Delta URLs failed")
    return {}

def scan_loop():
    print("[BOT] Scanner started")
    baseline_set = False
    last_snapshot_day = None
    while True:
        try:
            tickers = fetch_prices()
            if not tickers:
                time.sleep(30)
                continue

            state["tickers"]   = tickers
            state["last_scan"] = datetime.now().strftime("%H:%M:%S")
            state["connected"] = True

            now = datetime.now()

            # Record daily snapshot for backtest history
            today = now.strftime("%Y-%m-%d")
            if last_snapshot_day != today:
                record_daily_snapshot()
                last_snapshot_day = today

            if not baseline_set or (now.hour == 0 and now.minute == 0):
                for sym, t in tickers.items():
                    state["baselines"][sym] = t["open"]
                baseline_set = True
                print(f"[BOT] Baselines set for {len(state['baselines'])} symbols")

            trigger  = config["trigger_pct"]
            tp_pct   = config["tp_pct"]
            sl_pct   = config["sl_pct"]
            capital  = config["capital"]
            leverage = config["leverage"]

            for sym, t in tickers.items():
                price = t["price"]
                base  = state["baselines"].get(sym, 0)
                if base <= 0 or price <= 0: continue

                if sym in state["active_trades"]:
                    trade = state["active_trades"][sym]
                    sig_p = trade["signal_price"]
                    tp_p  = sig_p * (1 - tp_pct/100)
                    sl_p  = sig_p * (1 + sl_pct/100)
                    entry = trade["entry_price"]
                    qty   = trade["qty"]
                    if price <= tp_p:
                        pnl = (tp_p - entry) * qty
                        trade.update({"status":"TP","exit_price":tp_p,"pnl":round(pnl,2),"closed_at":datetime.now().strftime("%H:%M:%S")})
                        state["closed_trades"].insert(0, dict(trade))
                        state["total_pnl"] += pnl
                        del state["active_trades"][sym]
                        print(f"[TP] {sym} +${pnl:.2f}")
                    elif price >= sl_p:
                        pnl = -capital
                        trade.update({"status":"SL","exit_price":sl_p,"pnl":pnl,"closed_at":datetime.now().strftime("%H:%M:%S")})
                        state["closed_trades"].insert(0, dict(trade))
                        state["total_pnl"] += pnl
                        del state["active_trades"][sym]
                        print(f"[SL] {sym} -${capital}")
                else:
                    sig_price = base * (1 + trigger/100)
                    if price >= sig_price:
                        pos  = capital * leverage
                        qty  = pos / price
                        trade = {
                            "symbol":       sym,
                            "entry_price":  price,
                            "signal_price": sig_price,
                            "tp_price":     sig_price * (1 - tp_pct/100),
                            "sl_price":     sig_price * (1 + sl_pct/100),
                            "qty":          round(qty,6),
                            "capital":      capital,
                            "position_size":pos,
                            "status":       "OPEN",
                            "entered_at":   datetime.now().strftime("%H:%M:%S"),
                            "pnl":          0,
                        }
                        state["active_trades"][sym] = trade
                        state["signals_today"] += 1
                        print(f"[SIGNAL] {sym} @ ${price:.4f}")

        except Exception as e:
            print(f"[ERROR] {e}")
        time.sleep(60)

# ── API Routes ────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory('.', 'index.html')

@app.route("/api/debug")
def api_debug():
    syms = list(state["tickers"].keys())
    return jsonify({
        "total": len(syms),
        "symbols": sorted(syms),
        "last_scan": state["last_scan"],
        "sample": {s: state["tickers"][s]["price"] for s in syms[:5]} if syms else {}
    })
def api_prices():
    out = []
    for sym, t in state["tickers"].items():
        base = state["baselines"].get(sym, t["open"])
        chg  = ((t["price"] - base) / base * 100) if base > 0 else 0
        sig  = base * (1 + config["trigger_pct"]/100) if base > 0 else 0
        out.append({
            "symbol":       sym,
            "price":        t["price"],
            "open":         t["open"],
            "high":         t["high"],
            "low":          t["low"],
            "volume":       t["volume"],
            "change_pct":   round(chg,2),
            "signal_price": round(sig,6),
            "in_trade":     sym in state["active_trades"],
        })
    out.sort(key=lambda x: x["volume"]*x["price"], reverse=True)
    return jsonify({"success":True, "result":out, "count":len(out)})

@app.route("/api/status")
def api_status():
    return jsonify({
        "connected":     state["connected"],
        "last_scan":     state["last_scan"],
        "coins_watched": len(state["tickers"]),
        "signals_today": state["signals_today"],
        "total_pnl":     round(state["total_pnl"],2),
        "open_trades":   len(state["active_trades"]),
        "paper_trading": config["paper_trading"],
        "api_key_set":   bool(config.get("api_key")),
        "exchange":      config.get("exchange","india"),
    })

@app.route("/api/trades")
def api_trades():
    return jsonify({"open":list(state["active_trades"].values()), "closed":state["closed_trades"][:50]})

@app.route("/api/config", methods=["GET"])
def api_config_get():
    safe = {k:v for k,v in config.items() if k != "api_secret"}
    if safe.get("api_key"):
        safe["api_key"] = safe["api_key"][:6] + "••••••••"   # mask it
    return jsonify(safe)

@app.route("/api/config", methods=["POST"])
def api_config_post():
    data = request.json or {}
    for k in ["trigger_pct","tp_pct","sl_pct","capital","leverage"]:
        if k in data:
            config[k] = float(data[k])
    for k in ["api_key","api_secret","exchange","paper_trading"]:
        if k in data:
            config[k] = data[k]
    save_config(config)   # ← SAVES TO DISK PERMANENTLY
    print(f"[CONFIG] Saved. API key: {'set' if config.get('api_key') else 'not set'}")
    return jsonify({"success":True, "message":"Saved permanently ✓"})

HISTORY_FILE = os.path.join(BASE_DIR, 'price_history.json')

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE) as f:
                return json.load(f)
        except:
            pass
    return {}

def save_history(hist):
    with open(HISTORY_FILE, 'w') as f:
        json.dump(hist, f)

def record_daily_snapshot():
    """Called once per day — saves today's prices as a new candle."""
    hist = load_history()
    today = datetime.now().strftime("%Y-%m-%d")
    tickers = fetch_prices()
    if not tickers:
        return
    snap = {}
    for sym, t in tickers.items():
        snap[sym] = {
            "date":  today,
            "open":  t["open"],
            "high":  t["high"],
            "low":   t["low"],
            "close": t["price"],
            "vol":   t["volume"],
        }
    hist[today] = snap
    # Keep only last 365 days
    keys = sorted(hist.keys())
    if len(keys) > 365:
        for old in keys[:-365]:
            del hist[old]
    save_history(hist)
    print(f"[HISTORY] Recorded snapshot for {today} ({len(snap)} symbols)")

@app.route("/api/backtest")
def api_backtest():
    symbol  = request.args.get("symbol", "RAVEUSDT")
    months  = int(request.args.get("months", 6))
    trigger = float(request.args.get("trigger", config["trigger_pct"]))
    tp_pct  = float(request.args.get("tp_pct",  config["tp_pct"]))
    sl_pct  = float(request.args.get("sl_pct",  config["sl_pct"]))
    capital = float(request.args.get("capital", config["capital"]))
    leverage= float(request.args.get("leverage",config["leverage"]))

    hist = load_history()
    cutoff = datetime.now().strftime("%Y-%m-%d")
    # Filter last N months
    import datetime as dt
    cutoff_date = (dt.date.today() - dt.timedelta(days=months*30)).strftime("%Y-%m-%d")

    candles = []
    for date_key in sorted(hist.keys()):
        if date_key < cutoff_date:
            continue
        day_data = hist[date_key]
        if symbol not in day_data:
            continue
        c = day_data[symbol]
        candles.append({
            "date":  c["date"],
            "open":  float(c["open"]),
            "high":  float(c["high"]),
            "low":   float(c["low"]),
            "close": float(c["close"]),
        })

    # If we have less than 7 days of recorded history, explain clearly
    if len(candles) < 7:
        days_recorded = len(hist)
        return jsonify({
            "success": False,
            "error": f"Not enough history yet. The bot has recorded {days_recorded} day(s) of real price data so far. Backtest needs at least 7 days. Come back in {max(1, 7-days_recorded)} more days!",
            "days_recorded": days_recorded,
            "tip": "The bot records prices every day automatically. The longer it runs, the better your backtest data."
        }), 400

    # Run strategy on candles
    trades = []
    i = 0
    while i < len(candles):
        entry_candle = candles[i]
        entry_price  = entry_candle["close"]
        entry_date   = entry_candle["date"]
        if entry_price <= 0:
            i += 1
            continue

        sig_price = entry_price * (1 + trigger / 100)
        tp_price  = sig_price  * (1 - tp_pct  / 100)
        sl_price  = sig_price  * (1 + sl_pct  / 100)
        armed = False

        for j in range(i, len(candles)):
            c = candles[j]
            if not armed:
                if c["high"] >= sig_price:
                    armed = True
            if armed:
                if c["low"] <= tp_price:
                    pos = capital * leverage
                    qty = pos / entry_price
                    pnl = round((tp_price - entry_price) * qty, 2)
                    trades.append({
                        "date":       c["date"],
                        "entry_date": entry_date,
                        "symbol":     symbol.replace("USDT",""),
                        "entry":      round(entry_price, 6),
                        "signal":     round(sig_price, 6),
                        "exit":       round(tp_price, 6),
                        "result":     "TP HIT",
                        "pnl":        pnl,
                    })
                    i = j + 1
                    break
                elif c["high"] >= sl_price:
                    trades.append({
                        "date":       c["date"],
                        "entry_date": entry_date,
                        "symbol":     symbol.replace("USDT",""),
                        "entry":      round(entry_price, 6),
                        "signal":     round(sig_price, 6),
                        "exit":       round(sl_price, 6),
                        "result":     "SL HIT",
                        "pnl":        round(-capital, 2),
                    })
                    i = j + 1
                    break
        else:
            break

    profits   = [t for t in trades if t["result"] == "TP HIT"]
    losses    = [t for t in trades if t["result"] == "SL HIT"]
    total_pnl = round(sum(t["pnl"] for t in trades), 2)
    best      = round(max((t["pnl"] for t in trades), default=0), 2)
    worst     = round(min((t["pnl"] for t in trades), default=0), 2)
    winrate   = round(len(profits) / len(trades) * 100, 1) if trades else 0

    return jsonify({
        "success":      True,
        "symbol":       symbol,
        "months":       months,
        "candles_used": len(candles),
        "days_recorded":len(hist),
        "total_trades": len(trades),
        "profits":      len(profits),
        "losses":       len(losses),
        "win_rate":     winrate,
        "total_pnl":    total_pnl,
        "best_trade":   best,
        "worst_trade":  worst,
        "trades":       trades,
    })

if __name__ == "__main__":
    t = threading.Thread(target=scan_loop, daemon=True)
    t.start()
    port = int(os.environ.get("PORT", 5000))
    print(f"[SERVER] Running at http://localhost:{port}")
    app.run(host="0.0.0.0", port=port)
else:
    # Running via gunicorn on Railway - start scanner
    
    t = threading.Thread(target=scan_loop, daemon=True)
    t.start()
    print("[SERVER] Scanner started via gunicorn")
