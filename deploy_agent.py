"""
Trade350 Deployment Agent
- Watches GitHub for new tasks every 2 minutes
- Executes tasks automatically on AWS server
- Reports results to Telegram
- No manual work needed!
"""
import os, json, time, requests, subprocess
from datetime import datetime

# ── Config ──────────────────────────────────────────────────
TELEGRAM_TOKEN  = "8258685847:AAF22apl4pPv3gkBBZs7t6hwjHwDXlTcMyE"
GITHUB_REPO     = "bhagwan92AI/deltabot-pro"
GITHUB_TOKEN    = ""  # Will be set via environment or config
BOT_DIR         = "/home/ec2-user/deltabot-pro"
TASKS_FILE      = "tasks.json"
DONE_FILE       = "/home/ec2-user/done_tasks.json"
CHECK_INTERVAL  = 120  # Check every 2 minutes
TELEGRAM_API    = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
OWNER_CHAT_ID   = "1280361723"  # Ajeet's Telegram ID

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")

def send_telegram(msg):
    try:
        requests.post(f"{TELEGRAM_API}/sendMessage", json={
            "chat_id": OWNER_CHAT_ID,
            "text": msg,
            "parse_mode": "Markdown"
        }, timeout=10)
    except Exception as e:
        log(f"Telegram error: {e}")

def load_done_tasks():
    if os.path.exists(DONE_FILE):
        try:
            with open(DONE_FILE) as f:
                return json.load(f)
        except:
            pass
    return []

def save_done_tasks(done):
    with open(DONE_FILE, 'w') as f:
        json.dump(done, f)

def fetch_tasks():
    """Fetch tasks.json from GitHub."""
    try:
        headers = {"Accept": "application/vnd.github.v3.raw"}
        if GITHUB_TOKEN:
            headers["Authorization"] = f"token {GITHUB_TOKEN}"
        r = requests.get(
            f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{TASKS_FILE}",
            headers=headers, timeout=10
        )
        if r.status_code == 200:
            return r.json()
        elif r.status_code == 404:
            return []
        else:
            log(f"GitHub fetch error: {r.status_code}")
            return []
    except Exception as e:
        log(f"Fetch tasks error: {e}")
        return []

def run_command(cmd, cwd=BOT_DIR):
    """Run a shell command and return output."""
    try:
        result = subprocess.run(
            cmd, shell=True, cwd=cwd,
            capture_output=True, text=True, timeout=120
        )
        return result.stdout + result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return "Command timed out!", 1
    except Exception as e:
        return str(e), 1

def execute_task(task):
    """Execute a task and return result."""
    task_type = task.get("type", "")
    task_id   = task.get("id", "unknown")
    desc      = task.get("description", "No description")

    log(f"Executing task: {task_id} - {desc}")
    send_telegram(f"⚙️ *Executing task:* {desc}")

    if task_type == "git_pull":
        out, code = run_command("git pull")
        if code == 0:
            return True, f"✅ Git pull successful:\n`{out[:200]}`"
        return False, f"❌ Git pull failed:\n`{out[:200]}`"

    elif task_type == "restart_bot":
        run_command("pkill -f main.py")
        time.sleep(2)
        out, code = run_command(f"nohup python3 main.py > bot.log 2>&1 &")
        time.sleep(3)
        # Verify it started
        verify, _ = run_command("curl -s http://localhost:5000/api/status")
        if "connected" in verify:
            return True, f"✅ Bot restarted! Status: running"
        return False, f"❌ Bot restart failed"

    elif task_type == "restart_agent":
        run_command("pkill -f telegram_agent.py")
        time.sleep(2)
        run_command(f"nohup python3 telegram_agent.py > agent.log 2>&1 &")
        return True, "✅ Telegram agent restarted!"

    elif task_type == "update_and_restart":
        # Full deploy: git pull + restart everything
        out1, c1 = run_command("git pull")
        if c1 != 0:
            return False, f"❌ Git pull failed: {out1[:200]}"
        run_command("pkill -f main.py")
        run_command("pkill -f telegram_agent.py")
        time.sleep(2)
        run_command("nohup python3 main.py > bot.log 2>&1 &")
        time.sleep(2)
        run_command("nohup python3 telegram_agent.py > agent.log 2>&1 &")
        time.sleep(3)
        verify, _ = run_command("curl -s http://localhost:5000/api/status")
        if "connected" in verify:
            return True, f"✅ Full deploy done!\n`{out1[:200]}`"
        return False, "❌ Deploy failed - bot not responding"

    elif task_type == "run_command":
        cmd = task.get("command", "echo 'no command'")
        out, code = run_command(cmd)
        if code == 0:
            return True, f"✅ Command done:\n`{out[:300]}`"
        return False, f"❌ Command failed:\n`{out[:300]}`"

    elif task_type == "update_config":
        # Update config values
        config_updates = task.get("config", {})
        config_file = os.path.join(BOT_DIR, "config.json")
        try:
            if os.path.exists(config_file):
                with open(config_file) as f:
                    cfg = json.load(f)
            else:
                cfg = {}
            cfg.update(config_updates)
            with open(config_file, 'w') as f:
                json.dump(cfg, f, indent=2)
            # Restart bot to apply
            run_command("pkill -f main.py")
            time.sleep(2)
            run_command("nohup python3 main.py > bot.log 2>&1 &")
            return True, f"✅ Config updated: {config_updates}"
        except Exception as e:
            return False, f"❌ Config update failed: {e}"

    elif task_type == "check_status":
        out, _ = run_command("curl -s http://localhost:5000/api/status")
        try:
            s = json.loads(out)
            return True, f"""✅ *Server Status*
• Coins: {s.get('coins_watched', 0)}
• Connected: {s.get('connected')}
• Last scan: {s.get('last_scan')}
• Open trades: {s.get('open_trades', 0)}
• PnL: ${s.get('total_pnl', 0):.2f}"""
        except:
            return False, f"❌ Status check failed: {out[:200]}"

    else:
        return False, f"❌ Unknown task type: {task_type}"

def main():
    log("=" * 50)
    log("Trade350 Deployment Agent Started!")
    log("Watching GitHub for tasks every 2 minutes")
    log("=" * 50)
    send_telegram("🤖 *Deployment Agent Started!*\nWatching for tasks every 2 minutes.")

    done_tasks = load_done_tasks()

    while True:
        try:
            tasks = fetch_tasks()
            
            for task in tasks:
                task_id = task.get("id", "")
                if not task_id or task_id in done_tasks:
                    continue
                
                # Execute the task
                success, result = execute_task(task)
                
                # Mark as done
                done_tasks.append(task_id)
                save_done_tasks(done_tasks)
                
                # Report to Telegram
                desc = task.get("description", "Task")
                if success:
                    send_telegram(f"✅ *{desc}*\n{result}")
                else:
                    send_telegram(f"❌ *{desc} FAILED*\n{result}")
                
                log(f"Task {task_id}: {'SUCCESS' if success else 'FAILED'}")
                time.sleep(1)

        except Exception as e:
            log(f"Main loop error: {e}")

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
