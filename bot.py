import os
from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    return "Amazon Affiliate Bot is running on Render!"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"Starting on port {port}")
    app.run(host='0.0.0.0', port=port)
