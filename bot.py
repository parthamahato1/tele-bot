import os
import re
import sqlite3
import logging
import requests
from datetime import datetime
from telebot import TeleBot, types
from bs4 import BeautifulSoup
from flask import Flask, request

TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise ValueError("TOKEN environment variable not set!")

bot = TeleBot(TOKEN)
app = Flask(__name__)

logging.basicConfig(level=logging.INFO)

# Database
conn = sqlite3.connect('amazon_bot.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS users (telegram_id INTEGER PRIMARY KEY, first_name TEXT, username TEXT, created_at TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS conversions (id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id INTEGER, original_url TEXT, affiliate_url TEXT, asin TEXT, domain TEXT, product_title TEXT, created_at TEXT)''')
conn.commit()

def extract_asin(url):
    match = re.search(r'/([A-Z0-9]{10})(?:[/?#]|$)', url.upper())
    return match.group(1) if match else None

def get_domain(url):
    domains = ["amazon.in","amazon.com","amazon.co.uk","amazon.de","amazon.fr","amazon.it","amazon.nl","amazon.pl","amazon.es","amazon.se","amazon.ca"]
    for d in domains:
        if d in url.lower():
            return d
    return None

def fetch_product_title(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        title = soup.find('span', id='productTitle')
        if title:
            return title.get_text().strip()
        title = soup.find('h1', id='title')
        if title:
            return title.get_text().strip()
        return None
    except:
        return None

def expand_short_link(short_url):
    """Stronger expansion for amzn.in/d/ links"""
    try:
        # Try head request with redirects
        r = requests.head(short_url, allow_redirects=True, timeout=8)
        if r.url and "amazon" in r.url.lower():
            return r.url
    except:
        pass
    # Fallback: try GET
    try:
        r = requests.get(short_url, allow_redirects=True, timeout=8)
        if r.url and "amazon" in r.url.lower():
            return r.url
    except:
        pass
    return short_url

def generate_affiliate_link(original_url):
    # Expand if it's a shortened link
    if any(x in original_url.lower() for x in ["amzn.in", "amzn.to", "amzn.com/d"]):
        original_url = expand_short_link(original_url)
    
    asin = extract_asin(original_url)
    if not asin:
        return None, None, None
    
    domain = get_domain(original_url)
    tag = "teleb0t-21" if domain == "amazon.in" else "teleb0t-20"
    base = f"www.{domain}" if domain else "www.amazon.in"
    return f"https://{base}/dp/{asin}?tag={tag}", asin, domain or "amazon.in"

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, f"👋 Hello {message.from_user.first_name}!\n\nSend any Amazon link.")

@bot.message_handler(func=lambda m: True)
def handle_message(message):
    if not message.text:
        return
    patterns = [
        r'https?://[^\s<>"]+amazon\.[^\s<>"]+',
        r'https?://amzn\.(in|to|com)/[^\s<>"]+'
    ]
    found_urls = []
    for pattern in patterns:
        found_urls.extend(re.findall(pattern, message.text, re.IGNORECASE))
    
    for url in found_urls:
        affiliate_url, asin, domain = generate_affiliate_link(url)
        if not affiliate_url:
            continue
        title = fetch_product_title(url)
        cursor.execute('INSERT INTO conversions VALUES (NULL,?,?,?,?,?,?,?)',
                       (message.from_user.id, url, affiliate_url, asin, domain, title, datetime.now().isoformat()))
        conn.commit()
        reply = f"📦 {title}\n\n✅ Your Affiliate Link:\n{affiliate_url}" if title else f"✅ Your Affiliate Link:\n{affiliate_url}"
        bot.reply_to(message, reply)

@app.route('/', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = types.Update.de_json(json_string)
        bot.process_new_updates([update])
    return '', 200

@app.route('/')
def home():
    return "Amazon Affiliate Bot is running!"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    bot.remove_webhook()
    bot.set_webhook(url=f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME')}/")
    print(f"Bot started with webhook on port {port}")
    app.run(host='0.0.0.0', port=port)
