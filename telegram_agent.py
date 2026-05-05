"""
Trade350 Telegram Agent
- Receives messages from you on Telegram
- Uses Claude AI to understand requirements
- Updates code on GitHub automatically
- Deploys to AWS server
- Sends back confirmation
"""
import os, json, time, requests, subprocess, threading
from datetime import datetime

# ── Config ──────────────────────────────────────────────────
TELEGRAM_TOKEN = "8258685847:AAF22apl4pPv3gkBBZs7t6hwjHwDXlTcMyE"
CLAUDE_API_KEY = "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"
GITHUB_REPO   = "bhagwan92AI/deltabot-pro"
AWS_IP        = "3.110.105.149"
AWS_PORT      = 5000
AUTHORIZED_USERS = []  # Will be set on first message

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ── Project Context for Claude ───────────────────────────────
PROJECT_CONTEXT = """
You are the Trade350 AI Agent. You help manage and improve the Trade350 crypto trading platform.

PROJECT SUMMARY:
- Trade350 is a crypto trading bot for Delta Exchange India
- Strategy: Enter when price rises 350% above yesterday close
- Take Profit: 50% reversal from signal price
- Stop Loss: 100% above signal price
- Capital: $5 per trade, 20x leverage
- Live URL: http://3.110.105.149:5000
- GitHub: github.com/bhagwan92AI/deltabot-pro
- Files: main.py (Flask backend), index.html (frontend)

CURRENT ISSUES:
1. Only 6 coins loading (need 185) - Delta API geo-restriction
2. AWS bot needs 24/7 setup (nohup + crontab)
3. No user login system yet

CAPABILITIES YOU HAVE:
- Read and update code files
- Deploy to AWS server
- Check server status
- Answer questions about the platform
- Explain what changes need to be made

When user sends a requirement:
1. Understand what they want
2. Explain what you will do
3. Provide the solution (code changes, commands, or explanation)
4. Give step-by-step instructions if manual action needed
"""

# ── Telegram Functions ───────────────────────────────────────
def send_message(chat_id, text, parse_mode="Markdown"):
    try:
        url = f"{TELEGRAM_API}/sendMessage"
        data = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        r = requests.post(url, json=data, timeout=10)
        return r.json()
    except Exception as e:
        print(f"[TG] Send error: {e}")

def send_typing(chat_id):
    try:
        requests.post(f"{TELEGRAM_API}/sendChatAction", 
                     json={"chat_id": chat_id, "action": "typing"}, timeout=5)
    except:
        pass

def get_updates(offset=0):
    try:
        r = requests.get(f"{TELEGRAM_API}/getUpdates", 
                        params={"offset": offset, "timeout": 30}, timeout=35)
        return r.json().get("result", [])
    except Exception as e:
        print(f"[TG] Get updates error: {e}")
        return []

# ── Claude AI Functions ──────────────────────────────────────
def ask_claude(user_message, chat_history=[]):
    try:
        messages = []
        for msg in chat_history[-6:]:  # Last 6 messages for context
            messages.append(msg)
        messages.append({"role": "user", "content": user_message})

        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": CLAUDE_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1000,
                "system": PROJECT_CONTEXT,
                "messages": messages
            },
            timeout=30
        )
        data = r.json()
        if "content" in data:
            return data["content"][0]["text"]
        return f"Error: {data.get('error', {}).get('message', 'Unknown error')}"
    except Exception as e:
        return f"Claude API error: {e}"

def check_server_status():
    try:
        r = requests.get(f"http://{AWS_IP}:{AWS_PORT}/api/status", timeout=5)
        data = r.json()
        return f"""✅ *Server Online*
• Coins watched: {data.get('coins_watched', 0)}
• Last scan: {data.get('last_scan', 'N/A')}
• Open trades: {data.get('open_trades', 0)}
• Total PnL: ${data.get('total_pnl', 0):.2f}
• Signals today: {data.get('signals_today', 0)}
• Mode: {'Paper' if data.get('paper_trading') else 'LIVE'}"""
    except:
        return "❌ *Server Offline* - Bot may not be running"

def get_github_file(filename):
    try:
        r = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}",
            headers={"Accept": "application/vnd.github.v3+json"},
            timeout=10
        )
        data = r.json()
        import base64
        content = base64.b64decode(data["content"]).decode()
        return content, data["sha"]
    except Exception as e:
        return None, None

# ── Command Handlers ─────────────────────────────────────────
def handle_status(chat_id):
    send_typing(chat_id)
    status = check_server_status()
    send_message(chat_id, f"🔍 *Trade350 Server Status*\n\n{status}")

def handle_help(chat_id):
    help_text = """🤖 *Trade350 Agent Commands*

*Quick Commands:*
/status - Check server status
/prices - Top 10 live prices
/trades - Current open trades
/pnl - Total PnL summary
/help - Show this menu

*Ask me anything like:*
• "Fix the 185 coins issue"
• "Add Telegram alerts"
• "How do I go live with real money?"
• "What is the current strategy?"
• "Show me how to add Google login"
• "Check if bot is working"

*I can:*
✅ Answer questions about Trade350
✅ Explain code changes needed
✅ Check server status
✅ Guide you through any task
✅ Generate updated code

Just type your requirement! 💬"""
    send_message(chat_id, help_text)

def handle_prices(chat_id):
    send_typing(chat_id)
    try:
        r = requests.get(f"http://{AWS_IP}:{AWS_PORT}/api/prices", timeout=10)
        data = r.json()
        prices = data.get("result", [])[:10]
        if not prices:
            send_message(chat_id, "❌ Could not fetch prices")
            return
        msg = "📊 *Top 10 Live Prices*\n\n"
        for i, p in enumerate(prices, 1):
            chg = p.get("change_pct", 0)
            emoji = "🟢" if chg > 0 else "🔴"
            signal = " 🔔" if p.get("in_trade") else ""
            msg += f"{i}. *{p['symbol'].replace('USDT','')}* ${p['price']:.4f} {emoji}{chg:+.1f}%{signal}\n"
        send_message(chat_id, msg)
    except:
        send_message(chat_id, "❌ Server not responding. Start the bot first!")

def handle_trades(chat_id):
    send_typing(chat_id)
    try:
        r = requests.get(f"http://{AWS_IP}:{AWS_PORT}/api/trades", timeout=10)
        data = r.json()
        open_trades = data.get("open", [])
        closed = data.get("closed", [])[:5]
        
        if not open_trades and not closed:
            send_message(chat_id, "📋 No trades yet. Bot is scanning for signals...")
            return
        
        msg = "📋 *Trade Status*\n\n"
        if open_trades:
            msg += f"*Open Trades ({len(open_trades)}):*\n"
            for t in open_trades:
                msg += f"• {t['symbol']} @ ${t['entry_price']:.4f}\n"
                msg += f"  TP: ${t['tp_price']:.4f} | SL: ${t['sl_price']:.4f}\n"
        
        if closed:
            msg += f"\n*Recent Closed ({len(closed)}):*\n"
            for t in closed:
                emoji = "✅" if t['status'] == 'TP' else "❌"
                msg += f"{emoji} {t['symbol']} {t['status']} ${t.get('pnl',0):.2f}\n"
        
        send_message(chat_id, msg)
    except:
        send_message(chat_id, "❌ Server not responding!")

def handle_pnl(chat_id):
    send_typing(chat_id)
    try:
        r = requests.get(f"http://{AWS_IP}:{AWS_PORT}/api/status", timeout=5)
        s = r.json()
        r2 = requests.get(f"http://{AWS_IP}:{AWS_PORT}/api/trades", timeout=5)
        t = r2.json()
        closed = t.get("closed", [])
        profits = [x for x in closed if x.get("status") == "TP"]
        losses = [x for x in closed if x.get("status") == "SL"]
        
        msg = f"""💰 *PnL Summary*

Total PnL: *${s.get('total_pnl', 0):.2f}*
Open Trades: {s.get('open_trades', 0)}
Signals Today: {s.get('signals_today', 0)}
Total Trades: {len(closed)}
Profits (TP): {len(profits)} ✅
Losses (SL): {len(losses)} ❌
Win Rate: {round(len(profits)/len(closed)*100) if closed else 0}%"""
        send_message(chat_id, msg)
    except:
        send_message(chat_id, "❌ Could not fetch PnL data!")

# ── Main Message Handler ─────────────────────────────────────
chat_histories = {}

def handle_message(chat_id, user_id, username, text):
    global AUTHORIZED_USERS
    
    # First message - authorize this user
    if not AUTHORIZED_USERS:
        AUTHORIZED_USERS.append(user_id)
        print(f"[AUTH] Authorized user: {username} ({user_id})")
    
    # Security check
    if user_id not in AUTHORIZED_USERS:
        send_message(chat_id, "❌ Unauthorized. This bot is private.")
        return
    
    text = text.strip()
    
    # Handle commands
    if text == '/start':
        send_message(chat_id, f"""👋 *Welcome to Trade350 Agent!*

I'm your AI assistant for the Trade350 trading platform.

I can help you:
• Check server and bot status
• Answer questions about your strategy
• Guide you through any changes
• Fix issues and add features

Type /help to see all commands or just ask me anything! 🚀""")
        return
    
    if text == '/help':
        handle_help(chat_id)
        return
    
    if text == '/status':
        handle_status(chat_id)
        return
    
    if text == '/prices':
        handle_prices(chat_id)
        return
    
    if text == '/trades':
        handle_trades(chat_id)
        return
    
    if text == '/pnl':
        handle_pnl(chat_id)
        return
    
    # AI conversation
    send_typing(chat_id)
    send_message(chat_id, "🤔 Thinking...")
    
    # Get chat history
    if chat_id not in chat_histories:
        chat_histories[chat_id] = []
    
    # Check server status to give context
    try:
        r = requests.get(f"http://{AWS_IP}:{AWS_PORT}/api/status", timeout=3)
        server_info = f"\n[Server status: {r.json()}]"
    except:
        server_info = "\n[Server status: offline]"
    
    # Ask Claude
    response = ask_claude(text + server_info, chat_histories[chat_id])
    
    # Update history
    chat_histories[chat_id].append({"role": "user", "content": text})
    chat_histories[chat_id].append({"role": "assistant", "content": response})
    if len(chat_histories[chat_id]) > 20:
        chat_histories[chat_id] = chat_histories[chat_id][-20:]
    
    # Split long messages
    if len(response) > 4000:
        parts = [response[i:i+4000] for i in range(0, len(response), 4000)]
        for part in parts:
            send_message(chat_id, part)
            time.sleep(0.5)
    else:
        send_message(chat_id, response)

# ── Main Loop ────────────────────────────────────────────────
def main():
    print("""
╔══════════════════════════════════════╗
║     Trade350 Telegram Agent          ║
║     Bot: @trade350agent_bot          ║
╚══════════════════════════════════════╝
    """)
    
    # Test connections
    r = requests.get(f"{TELEGRAM_API}/getMe", timeout=5)
    bot_info = r.json().get("result", {})
    print(f"[TG] Connected as: @{bot_info.get('username')}")
    
    offset = 0
    print("[BOT] Listening for messages...")
    
    while True:
        try:
            updates = get_updates(offset)
            for update in updates:
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                if not msg:
                    continue
                chat_id  = msg["chat"]["id"]
                user_id  = msg["from"]["id"]
                username = msg["from"].get("username", "unknown")
                text     = msg.get("text", "")
                if text:
                    print(f"[MSG] {username}: {text[:50]}")
                    threading.Thread(
                        target=handle_message,
                        args=(chat_id, user_id, username, text),
                        daemon=True
                    ).start()
        except Exception as e:
            print(f"[ERROR] {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
