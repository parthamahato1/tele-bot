import re
import sqlite3
import logging
import requests
from datetime import datetime
from telebot import TeleBot, types
from bs4 import BeautifulSoup

# ========================= CONFIG =========================
TOKEN = "8573866345:AAGGT2Twt4FquYBYpe0BpN9to7s9LaupY-0"   # ← Replace with your bot token

# Tag Configuration
TAGS = {
    "amazon.in": "teleb0t-21",
    "amazon.com": "teleb0t-20",
    "amazon.co.uk": "teleb0t-20",
    "amazon.de": "teleb0t-20",
    "amazon.fr": "teleb0t-20",
    "amazon.it": "teleb0t-20",
    "amazon.nl": "teleb0t-20",
    "amazon.pl": "teleb0t-20",
    "amazon.es": "teleb0t-20",
    "amazon.se": "teleb0t-20",
    "amazon.ca": "teleb0t-20",
}

DEFAULT_TAG = "teleb0t-20"

# Headers to reduce chance of blocking
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
}

# =========================================================

bot = TeleBot(TOKEN)
logging.basicConfig(level=logging.INFO)

# Database Setup
conn = sqlite3.connect('amazon_bot.db', check_same_thread=False)
cursor = conn.cursor()

cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    first_name TEXT,
    username TEXT,
    created_at TEXT
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS conversions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER,
    original_url TEXT,
    affiliate_url TEXT,
    asin TEXT,
    domain TEXT,
    product_title TEXT,
    created_at TEXT
)
''')
conn.commit()

# Helper Functions
def extract_asin(url):
    match = re.search(r'/([A-Z0-9]{10})(?:[/?#]|$)', url.upper())
    return match.group(1) if match else None

def get_domain(url):
    for domain in TAGS.keys():
        if domain in url.lower():
            return domain
    return None

def fetch_product_title(url):
    """Try to fetch product title from Amazon page"""
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code != 200:
            return None
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Most common title selectors
        title = None
        title_tag = soup.find('span', id='productTitle')
        if title_tag:
            title = title_tag.get_text().strip()
        
        if not title:
            title_tag = soup.find('h1', id='title')
            if title_tag:
                title = title_tag.get_text().strip()
        
        return title if title else None
    except:
        return None

def generate_affiliate_link(original_url):
    asin = extract_asin(original_url)
    if not asin:
        return None, None, None, None
    
    domain = get_domain(original_url)
    tag = TAGS.get(domain, DEFAULT_TAG)
    
    base_domain = f"www.{domain}" if domain else "www.amazon.in"
    affiliate_url = f"https://{base_domain}/dp/{asin}?tag={tag}"
    
    return affiliate_url, asin, domain or "amazon.in", tag

# Welcome Message
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    first_name = message.from_user.first_name or ""
    username = message.from_user.username

    cursor.execute('''
        INSERT OR REPLACE INTO users (telegram_id, first_name, username, created_at)
        VALUES (?, ?, ?, ?)
    ''', (user_id, first_name, username, datetime.now().isoformat()))
    conn.commit()

    welcome_text = f"""
👋 Hello {first_name}!

Send me any Amazon product link and I'll instantly convert it to your affiliate link.

Supported countries: India, US, UK, Germany, France, Italy, etc.

Just paste the link!
    """
    bot.reply_to(message, welcome_text)

# Main Handler
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    if not message.text:
        return

    amazon_urls = re.findall(r'https?://[^\s<>"]+amazon\.[^\s<>"]+', message.text, re.IGNORECASE)
    
    if not amazon_urls:
        return

    for url in amazon_urls:
        affiliate_url, asin, domain, tag = generate_affiliate_link(url)
        if not affiliate_url:
            continue

        # Fetch product title (silently)
        product_title = fetch_product_title(url)

        # Save to database
        cursor.execute('''
            INSERT INTO conversions 
            (telegram_id, original_url, affiliate_url, asin, domain, product_title, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (message.from_user.id, url, affiliate_url, asin, domain, product_title, datetime.now().isoformat()))
        conn.commit()

        # Prepare clean reply
        if product_title:
            reply_text = f"📦 {product_title}\n\n✅ Your Affiliate Link:\n{affiliate_url}"
        else:
            reply_text = f"✅ Your Affiliate Link:\n{affiliate_url}"

        bot.reply_to(message, reply_text)

print("Amazon Affiliate Bot is running... (with title fetching)")
bot.infinity_polling()
