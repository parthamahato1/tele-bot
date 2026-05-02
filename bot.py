import os
import re
import sqlite3
import logging
import requests
from datetime import datetime
from telebot import TeleBot, types
from bs4 import BeautifulSoup
from flask import Flask, request
from telebot.types import LinkPreviewOptions

# --- CONFIGURATION ---
TOKEN = os.getenv("TOKEN")
# Render provides RENDER_EXTERNAL_HOSTNAME automatically
WEBHOOK_URL = os.getenv("RENDER_EXTERNAL_HOSTNAME") 

if not TOKEN:
    raise ValueError("TOKEN environment variable not set!")

bot = TeleBot(TOKEN)
app = Flask(__name__)

logging.basicConfig(level=logging.INFO)

# --- DATABASE SETUP ---
# Note: On Render's free tier, this file resets on every deploy/restart.
conn = sqlite3.connect('amazon_bot.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS users (telegram_id INTEGER PRIMARY KEY, first_name TEXT, username TEXT, created_at TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS conversions (id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id INTEGER, original_url TEXT, affiliate_url TEXT, asin TEXT, domain TEXT, product_title TEXT, created_at TEXT)''')
conn.commit()

# --- HELPER FUNCTIONS ---

def expand_short_link(short_url):
    """Handles stubborn amzn.in/d/ links using Session and Meta-Refresh checks"""
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    try:
        # Initial request
        r = session.get(short_url, headers=headers, allow_redirects=True, timeout=15)
        
        # Check for HTML Meta Refresh (Common in amzn.in/d/ links)
        if "refresh" in r.text.lower()[:500]: # Look only in header area
            match = re.search(r'url=(.*)"', r.text, re.IGNORECASE)
            if match:
                refresh_url = match.group(1).split('"')[0]
                r = session.get(refresh_url, headers=headers, allow_redirects=True, timeout=15)
        
        return r.url
    except Exception as e:
        logging.error(f"Expansion error: {e}")
        return short_url

def extract_asin(url):
    # ASIN is usually 10 alphanumeric characters after /dp/ or /gp/product/
    match = re.search(r'/(?:dp|gp/product)/([A-Z0-9]{10})', url.upper())
    if match:
        return match.group(1)
    # Fallback for links that don't have /dp/ yet
    match = re.search(r'/([A-Z0-9]{10})(?:[/?#]|$)', url.upper())
    return match.group(1) if match else None

def get_domain(url):
    domains = ["amazon.in","amazon.com","amazon.co.uk","amazon.de","amazon.fr","amazon.it","amazon.nl","amazon.pl","amazon.es","amazon.se","amazon.ca"]
    for d in domains:
        if d in url.lower():
            return d
    return "amazon.in"

def fetch_product_title(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # Try multiple title selectors
        for selector in ['span#productTitle', 'h1#title', 'meta[name="title"]']:
            tag = soup.select_one(selector)
            if tag:
                content = tag.get_text().strip() if tag.name != 'meta' else tag.get('content')
                if content: return content
        return None
    except:
        return None

def generate_affiliate_link(original_url):
    # Expand if it's a shortened link
    if any(x in original_url.lower() for x in ["amzn.in", "amzn.to", "amzn.com/d"]):
        expanded_url = expand_short_link(original_url)
    else:
        expanded_url = original_url
    
    asin = extract_asin(expanded_url)
    if not asin:
        return None, None, None
    
    domain = get_domain(expanded_url)
    # Choose tag based on domain
    tag = "teleb0t-21" if domain == "amazon.in" else "teleb0t-20"
    
    # Construct clean link
    affiliate_url = f"https://www.{domain}/dp/{asin}?tag={tag}"
    return affiliate_url, asin, domain

# --- BOT HANDLERS ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    welcome_text = (
        f"👋 *Hello {message.from_user.first_name}!*\n\n"
        "Welcome to the **Bot of Savings**. 💰\n\n"
        "Send me any Amazon link and I will:\n\n"
        "✅ Get you the **best offer** available.\n\n"
        "🚀 *Paste your link below to start saving!*\n\n"
        f"ℹ️ This bot uses affiliate ads"
        
    )
    # ADDED: Logic to actually send the message
    bot.send_message(message.chat.id, welcome_text, parse_mode="Markdown")

@bot.message_handler(func=lambda m: True)
def handle_message(message):
    if not message.text:
        return
    bot.send_chat_action(message.chat.id, 'typing')
    # Extract URLs from text
    url_pattern = r'https?://[^\s<>"]+'
    found_urls = re.findall(url_pattern, message.text)
    
    for url in found_urls:
        if "amazon" in url.lower() or "amzn" in url.lower():
            affiliate_url, asin, domain = generate_affiliate_link(url)
            
            if affiliate_url:
                title = fetch_product_title(affiliate_url)
                
                # Database storage
                cursor.execute('INSERT INTO conversions VALUES (NULL,?,?,?,?,?,?,?)',
                               (message.from_user.id, url, affiliate_url, asin, domain, title, datetime.now().isoformat()))
                conn.commit()
                
                if title:
                    reply = (
                      
                        f"📦 *{title}*\n\n"
                        f"✅ *Savings link:*\n\n"
                        f"🔗 *{affiliate_url}*\n\n"
                        f"✨ *Search and enabled for best value and rewards.*\n\n\n\n"
                        f"affiliate ads"

                    )
                else:
                    reply = (
                        
                        f"✅ *Savings link:*\n\n"
                        f"🔗 *{affiliate_url}*\n\n"
                        f"✨ *Search and enabled for best value and rewards.*\n\n\n\n"
                        f"affiliate ads"

                    )
                          
                bot.send_message(
                    message.chat.id, 
                    reply, 
                    parse_mode="Markdown", 
                    disable_web_page_preview=True
                )
# --- FLASK & WEBHOOK ---

@app.route('/' + TOKEN, methods=['POST'])
def getMessage():
    json_string = request.get_data().decode('utf-8')
    update = types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return "!", 200

@app.route("/")
def webhook():
    bot.remove_webhook()
    bot.set_webhook(url=f"https://{WEBHOOK_URL}/{TOKEN}")
    return "Bot is Active!", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
