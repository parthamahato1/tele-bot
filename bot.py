import os
import re
import sqlite3
import logging
import requests
from datetime import datetime
from telebot import TeleBot, types
from flask import Flask, request

# --- CONFIGURATION ---
# Ensure these environment variables are set in your Render Dashboard
TOKEN = os.getenv("TOKEN")
WEBHOOK_URL = os.getenv("RENDER_EXTERNAL_HOSTNAME") 

if not TOKEN:
    raise ValueError("TOKEN environment variable not set! Please add it to Render.")

bot = TeleBot(TOKEN)
app = Flask(__name__)

logging.basicConfig(level=logging.INFO)

# --- DATABASE SETUP ---
# SQLite is persistent on Render as long as the disk doesn't wipe (use a Disk for permanent storage)
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
        # Use HEAD request to save bandwidth and memory
        r = requests.head(short_url, allow_redirects=True, timeout=5)
        return r.url
    except Exception as e:
        logging.error(f"Expansion error: {e}")
        return short_url

def extract_asin(url):
    """Extracts the 10-character Amazon Product ID"""
    # Standard patterns for Amazon ASINs
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
    
    # Logic: .in uses teleb0t-21, all others (like .com) use teleb0t-20
    tag = "teleb0t-21" if domain == "amazon.in" else "teleb0t-20"
    
    affiliate_url = f"https://www.{domain}/dp/{asin}?tag={tag}"
    return affiliate_url, asin, domain

def show_help(chat_id, error_mode=False):
    """Sends the welcome message or an error notification"""
    msg = ""
    if error_mode:
        msg += "⚠️ **Not a valid Amazon URL.**\n\n"
    
    msg += (
        f"👋 *Hello {message.from_user.first_name}!*\n\n"
        "Welcome to the **Bot of Savings**. 💰\n\n"
        "Send me any Amazon link and I will\n\n"
        "✅ Get you the **best offers** available.\n\n"
        "🚀 *Paste your link below to start saving!*\n\n"
    )
    bot.send_message(chat_id, msg, parse_mode="Markdown")

# --- BOT HANDLERS ---

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    show_help(message.chat.id)

@bot.message_handler(func=lambda m: True)
def handle_message(message):
    if not message.text:
        return
    
    # 1. Regex to find any URLs in the text
    url_pattern = r'https?://[^\s<>"]+'
    found_urls = re.findall(url_pattern, message.text)
    
    # 2. Filter for Amazon-specific domains
    amazon_urls = [url for url in found_urls if "amazon" in url.lower() or "amzn" in url.lower()]
    
    if not amazon_urls:
        # User sent text or a non-Amazon link
        show_help(message.chat.id, error_mode=True)
        return

    # 3. Process each Amazon URL found
    for url in amazon_urls:
        bot.send_chat_action(message.chat.id, 'typing')
        
        affiliate_url, asin, domain = generate_affiliate_link(url)
        
        if affiliate_url:
            # Save conversion data to SQLite
            try:
                cursor.execute(
                    'INSERT INTO conversions (telegram_id, original_url, affiliate_url, asin, domain, created_at) VALUES (?,?,?,?,?,?)',
                    (message.from_user.id, url, affiliate_url, asin, domain, datetime.now().isoformat())
                )
                conn.commit()
            except Exception as e:
                logging.error(f"Database error: {e}")
            
            # Format and send the response
            reply = (
                f"✅ **Savings Link Ready:**\n\n"
                f"🔗 {affiliate_url}\n\n"
                f"✨ *Best value and rewards enabled.*\n"
                f"✨ *Search and enabled for best value and rewards via affiliate ads._.*\n\n"
            )
            bot.send_message(message.chat.id, reply, parse_mode="Markdown", disable_web_page_preview=True)
        else:
            # It looked like an Amazon link but didn't have a valid Product ID
            show_help(message.chat.id, error_mode=True)

# --- FLASK & WEBHOOK ---

@app.route('/' + TOKEN, methods=['POST'])
def getMessage():
    """Receives updates from Telegram via Webhook"""
    json_string = request.get_data().decode('utf-8')
    update = types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return "!", 200

@app.route("/")
def webhook():
    """Initializes the Webhook on bot startup"""
    bot.remove_webhook()
    # RENDER_EXTERNAL_HOSTNAME is automatically provided by Render
    full_url = f"https://{WEBHOOK_URL}/{TOKEN}"
    bot.set_webhook(url=full_url)
    return f"Bot is Active and Webhook is set to {full_url}", 200

if __name__ == "__main__":
    # Render uses port 10000 by default
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
