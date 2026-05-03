import os
import re
import sqlite3
import logging
import requests
from datetime import datetime
from telebot import TeleBot, types
from flask import Flask, request

# --- CONFIGURATION ---
TOKEN = os.getenv("TOKEN")
WEBHOOK_URL = os.getenv("RENDER_EXTERNAL_HOSTNAME")
# Replace with your real Telegram ID (e.g., 123456789)
ADMIN_ID = 1049695277 

if not TOKEN:
    raise ValueError("TOKEN environment variable not set! Please add it to Render.")

bot = TeleBot(TOKEN)
app = Flask(__name__)

logging.basicConfig(level=logging.INFO)

# --- DATABASE SETUP ---
conn = sqlite3.connect('amazon_bot.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS conversions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        telegram_id INTEGER, 
        original_url TEXT, 
        affiliate_url TEXT, 
        asin TEXT, 
        domain TEXT, 
        created_at TEXT
    )
''')
conn.commit()

# --- HELPER FUNCTIONS ---

def expand_short_link(short_url):
    """Expands amzn.to/in links using headers only (High Performance)"""
    try:
        r = requests.head(short_url, allow_redirects=True, timeout=5)
        return r.url
    except Exception as e:
        logging.error(f"Expansion error: {e}")
        return short_url

def extract_asin(url):
    """Extracts the 10-character Amazon Product ID"""
    match = re.search(r'/(?:dp|gp/product)/([A-Z0-9]{10})', url.upper())
    if match: return match.group(1)
    match = re.search(r'/([A-Z0-9]{10})(?:[/?#]|$)', url.upper())
    return match.group(1) if match else None

def get_domain(url):
    """Determines if the link is for .in or .com"""
    if "amazon.com" in url.lower():
        return "amazon.com"
    return "amazon.in"

def generate_affiliate_link(original_url):
    """Processes URL and attaches the correct Associate Tag"""
    if any(x in original_url.lower() for x in ["amzn.in", "amzn.to", "amzn.com/d"]):
        expanded_url = expand_short_link(original_url)
    else:
        expanded_url = original_url
    
    asin = extract_asin(expanded_url)
    if not asin:
        return None, None, None
    
    domain = get_domain(expanded_url)
    tag = "teleb0t-21" if domain == "amazon.in" else "teleb0t-20"
    
    affiliate_url = f"https://www.{domain}/dp/{asin}?tag={tag}"
    return affiliate_url, asin, domain

def show_help(chat_id, user_name, error_mode=False):
    """Sends the welcome message or an error notification"""
    name = user_name if user_name else "there"
    msg = ""
    if error_mode:
        msg += "⚠️ **Not a valid Amazon URL.**\n\n"
   
    msg += (
        f"👋 *Hello {name}!*\n\n"
        "Welcome to the **Bot of Savings**. 💰\n\n"
        "Send me any Amazon link and I will\n\n"
        "✅ Get you the **best offers** available.\n\n"
        "🚀 *Paste your link below to start saving!*\n\n"
    )
    bot.send_message(chat_id, msg, parse_mode="Markdown")

def check_and_send_backup():
    """Checks if a backup has been sent today and sends it to Admin"""
    today = datetime.now().strftime('%Y-%m-%d')
    flag_file = "last_backup.txt"
    last_sent = ""
    
    if os.path.exists(flag_file):
        with open(flag_file, "r") as f:
            last_sent = f.read().strip()

    if last_sent != today:
        try:
            if os.path.exists('amazon_bot.db'):
                with open('amazon_bot.db', 'rb') as f:
                    bot.send_document(ADMIN_ID, f, caption=f"📅 Daily Auto-Backup: {today}")
                
                with open(flag_file, "w") as f:
                    f.write(today)
        except Exception as e:
            logging.error(f"Auto-backup failed: {e}")

# --- BOT HANDLERS ---

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    show_help(message.chat.id, message.from_user.first_name)

@bot.message_handler(func=lambda m: True)
def handle_message(message):
    if not message.text:
        return
    
    url_pattern = r'https?://[^\s<>"]+'
    found_urls = re.findall(url_pattern, message.text)
    amazon_urls = [url for url in found_urls if "amazon" in url.lower() or "amzn" in url.lower()]
    user_name = message.from_user.first_name
    
    if not amazon_urls:
        show_help(message.chat.id, user_name, error_mode=True)
        return

    for url in amazon_urls:
        bot.send_chat_action(message.chat.id, 'typing')
        affiliate_url, asin, domain = generate_affiliate_link(url)
        
        if affiliate_url:
            try:
                cursor.execute(
                    'INSERT INTO conversions (telegram_id, original_url, affiliate_url, asin, domain, created_at) VALUES (?,?,?,?,?,?)',
                    (message.from_user.id, url, affiliate_url, asin, domain, datetime.now().isoformat())
                )
                conn.commit()
            except Exception as e:
                logging.error(f"Database error: {e}")
            
            name = user_name if user_name else "there"
            reply = (
                f"✅ **Your saving Link Ready:**\n\n"
                f"🔗 {affiliate_url}\n\n"
                f"✨ *Search and enabled for best value and rewards via affiliate ads.*\n\n"
            )
            bot.send_message(message.chat.id, reply, parse_mode="Markdown", disable_web_page_preview=True)
        else:
            show_help(message.chat.id, user_name, error_mode=True)

# --- FLASK & WEBHOOK ---

@app.route('/' + TOKEN, methods=['POST'])
def getMessage():
    json_string = request.get_data().decode('utf-8')
    update = types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return "!", 200

@app.route("/")
def webhook():
    # Triggered by cron-job ping
    check_and_send_backup()
    bot.remove_webhook()
    full_url = f"https://{WEBHOOK_URL}/{TOKEN}"
    bot.set_webhook(url=full_url)
    return f"Bot is Active. Webhook: {full_url}", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
