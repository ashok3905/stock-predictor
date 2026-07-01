"""
telegram_notifier.py — Telegram Bot Notifier for Intraday Trading App
Sends daily top 5 picks with reasons via Telegram bot.

Setup:
  1. Open Telegram, search for @BotFather
  2. Send /newbot, follow prompts to create your bot
  3. Copy the bot token BotFather gives you
  4. Send a message to your bot, then visit:
     https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
     to find your chat_id
  5. Add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to your .env file
  6. Run: python telegram_notifier.py          (send immediately)
  7. Run: python telegram_notifier.py --schedule (runs daily at 8:30 AM IST)
"""

import os
import sys
import time
import logging
from html import escape as html_escape
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import schedule
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    filename="logs/telegram_notifier.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
console.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
logging.getLogger().addHandler(console)

engine = create_engine(os.getenv("DATABASE_URL", "sqlite:///data/news.db"))
IST = ZoneInfo("Asia/Kolkata")


# ─── Fetch predictions ───────────────────────────────────────────────────────
def get_todays_predictions():
    """Fetch today's saved predictions from the database."""
    today = datetime.now(IST).strftime("%Y-%m-%d")
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT rank, ticker, avg_sentiment, article_count,
                       momentum_score, reason_summary, top_headline_1,
                       top_headline_2
                FROM predictions
                WHERE prediction_date = :d
                ORDER BY rank ASC
            """),
            {"d": today},
        ).fetchall()
    return rows


# ─── Format message ──────────────────────────────────────────────────────────
def format_telegram_message(predictions):
    """Build a clean Telegram message using HTML formatting."""
    today_str = datetime.now(IST).strftime("%A, %B %d, %Y")

    lines = [f"📈 <b>Intraday Trading Picks</b>", f"📅 {today_str}", ""]

    for rank, ticker, avg_sentiment, article_count, momentum, reason, h1, h2 in predictions:
        sentiment_str = f"{avg_sentiment:+.3f}" if avg_sentiment else "N/A"
        reason_str = html_escape(reason or "N/A")

        if avg_sentiment and avg_sentiment > 0.3:
            sent_emoji = "🟢"
        elif avg_sentiment and avg_sentiment < -0.1:
            sent_emoji = "🔴"
        else:
            sent_emoji = "⚪"

        lines.append(f"<b>#{rank} {ticker}</b>")
        lines.append(f"  {sent_emoji} Sentiment: <code>{sentiment_str}</code>  |  Momentum: <code>{momentum:.3f}</code>  |  Articles: <code>{article_count}</code>")
        lines.append(f"  💡 <i>{reason_str}</i>")
        if h1:
            lines.append(f"  📰 {html_escape(h1[:120])}{'...' if len(h1) > 120 else ''}")
        if h2:
            lines.append(f"  📰 {html_escape(h2[:120])}{'...' if len(h2) > 120 else ''}")
        lines.append("")

    lines.append("⚠️ <i>Not financial advice. Pick 3 of 5 before market open.</i>")
    lines.append(f"🤖 <i>Generated {datetime.now(IST).strftime('%H:%M IST')}</i>")

    return "\n".join(lines)


# ─── Send via Telegram ────────────────────────────────────────────────────────
def send_telegram(text_content):
    """Send a message via Telegram Bot API."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logging.error(
            "Telegram credentials not configured. Set TELEGRAM_BOT_TOKEN "
            "and TELEGRAM_CHAT_ID in your .env file."
        )
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text_content,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        resp = requests.post(url, json=payload, timeout=15)
        data = resp.json()

        if data.get("ok"):
            logging.info(f"Telegram message sent to chat {TELEGRAM_CHAT_ID}")
            return True
        else:
            logging.error(f"Telegram API error: {data.get('description', 'Unknown error')}")
            return False
    except Exception as e:
        logging.error(f"Failed to send Telegram message: {e}")
        return False


# ─── Main job ─────────────────────────────────────────────────────────────────
def send_daily_picks_telegram():
    """Main job: fetch predictions and send via Telegram."""
    logging.info("Starting Telegram notification job...")

    predictions = get_todays_predictions()
    if not predictions:
        logging.warning("No predictions found for today. Skipping Telegram.")
        return

    message = format_telegram_message(predictions)

    # Telegram has a 4096 character limit per message
    if len(message) > 4000:
        message = message[:3997] + "..."

    success = send_telegram(message)

    if success:
        logging.info(f"Telegram picks sent successfully ({len(predictions)} stocks).")
    else:
        logging.error("Failed to send Telegram picks.")


# ─── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if "--schedule" in sys.argv:
        schedule.every().day.at("08:30").do(send_daily_picks_telegram)
        logging.info("Scheduler started. Telegram sends daily at 8:30 AM IST.")
        logging.info("Press Ctrl+C to stop.\n")

        while True:
            try:
                schedule.run_pending()
                time.sleep(30)
            except KeyboardInterrupt:
                logging.info("Telegram notifier stopped by user.")
                print("\nNotifier stopped.")
                break
            except Exception as e:
                logging.error(f"Unexpected error: {e}")
                time.sleep(5)
    else:
        send_daily_picks_telegram()
