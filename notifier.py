"""
notifier.py — Daily Email Notifier for Intraday Trading App
Sends the top 5 predicted stocks with reasons via email each morning
before market open (8:30 AM IST).

Setup:
  1. Copy .env.example to .env and fill in your email credentials
  2. For Gmail: enable 2FA and create an App Password at
     https://myaccount.google.com/apppasswords
  3. Run: python notifier.py          (sends immediately)
  4. Run: python notifier.py --schedule (runs daily at 8:30 AM IST)
"""

import os
import sys
import time
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from zoneinfo import ZoneInfo

import schedule
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# ─── Load environment variables ───────────────────────────────────────────────
load_dotenv()

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
EMAIL_USER = os.getenv("EMAIL_USER", "")
EMAIL_PASS = os.getenv("EMAIL_PASS", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")

# ─── Logging setup ────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    filename="logs/notifier.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
console.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
logging.getLogger().addHandler(console)

# ─── Database setup ───────────────────────────────────────────────────────────
engine = create_engine("sqlite:///data/news.db")

IST = ZoneInfo("Asia/Kolkata")


# ─── Fetch today's predictions ───────────────────────────────────────────────
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


# ─── Build HTML email ────────────────────────────────────────────────────────
def build_html_email(predictions):
    """Build a styled HTML email from today's predictions."""
    today_str = datetime.now(IST).strftime("%A, %B %d, %Y")

    stock_cards = ""
    for rank, ticker, avg_sentiment, article_count, momentum, reason, h1, h2 in predictions:
        # Sentiment color
        if avg_sentiment and avg_sentiment > 0.3:
            sent_color = "#4ade80"
            sent_emoji = "🟢"
        elif avg_sentiment and avg_sentiment < -0.1:
            sent_color = "#f87171"
            sent_emoji = "🔴"
        else:
            sent_color = "#94a3b8"
            sent_emoji = "⚪"

        sentiment_str = f"{avg_sentiment:+.3f}" if avg_sentiment else "N/A"
        reason_str = reason or "No reason available"

        headlines_html = ""
        if h1:
            headlines_html += f'<div style="color:#94a3b8;font-size:13px;padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.05);">📰 {h1}</div>'
        if h2:
            headlines_html += f'<div style="color:#94a3b8;font-size:13px;padding:4px 0;">📰 {h2}</div>'

        stock_cards += f"""
        <tr><td style="padding:0 20px 20px 20px;">
            <div style="background:linear-gradient(135deg,#1e293b,#2d3a4f);border:1px solid rgba(255,255,255,0.08);border-radius:14px;padding:20px;">
                <div style="display:inline-block;background:linear-gradient(135deg,#3b82f6,#2563eb);color:white;font-weight:700;font-size:13px;padding:4px 12px;border-radius:20px;margin-bottom:10px;">
                    #{rank}
                </div>
                <div style="font-size:24px;font-weight:800;color:#f1f5f9;margin:0 0 10px 0;">
                    {ticker}
                </div>
                <table width="100%" cellpadding="0" cellspacing="0" style="margin:10px 0;">
                    <tr>
                        <td width="33%" style="padding-right:10px;">
                            <div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;">Sentiment</div>
                            <div style="font-size:16px;font-weight:600;color:{sent_color};">{sent_emoji} {sentiment_str}</div>
                        </td>
                        <td width="33%" style="padding-right:10px;">
                            <div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;">Momentum</div>
                            <div style="font-size:16px;font-weight:600;color:#e2e8f0;">{momentum:.3f}</div>
                        </td>
                        <td width="33%">
                            <div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;">Articles</div>
                            <div style="font-size:16px;font-weight:600;color:#e2e8f0;">{article_count}</div>
                        </td>
                    </tr>
                </table>
                <div style="background:rgba(59,130,246,0.1);border-left:3px solid #3b82f6;padding:10px 14px;border-radius:0 8px 8px 0;margin:10px 0;">
                    <div style="font-size:10px;color:#60a5fa;text-transform:uppercase;letter-spacing:0.8px;font-weight:600;margin-bottom:4px;">Why this pick?</div>
                    <div style="color:#cbd5e1;font-size:14px;line-height:1.5;">{reason_str}</div>
                </div>
                {f'<div style="margin-top:10px;">{headlines_html}</div>' if headlines_html else ''}
            </div>
        </td></tr>"""

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background-color:#0f172a;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#0f172a;padding:20px 0;">
        <tr><td align="center">
            <table width="600" cellpadding="0" cellspacing="0">
                <!-- Header -->
                <tr><td style="background:linear-gradient(135deg,#0f172a 0%,#1e293b 50%,#334155 100%);padding:30px;border-radius:16px 16px 0 0;border:1px solid rgba(255,255,255,0.05);text-align:center;">
                    <div style="font-size:28px;margin-bottom:8px;">📈</div>
                    <h1 style="color:#f1f5f9;font-size:22px;margin:0;font-weight:700;">Intraday Trading Picks</h1>
                    <p style="color:#94a3b8;font-size:14px;margin:8px 0 0 0;">{today_str} — AI-powered news sentiment analysis</p>
                </td></tr>
                <!-- Stock Cards -->
                {stock_cards}
                <!-- Footer -->
                <tr><td style="padding:20px;text-align:center;border-top:1px solid rgba(255,255,255,0.05);">
                    <p style="color:#64748b;font-size:12px;margin:0;">
                        ⚠️ These picks are based on news sentiment analysis and are NOT financial advice.<br>
                        Always do your own research before trading. Pick 3 of these 5 manually before market open.
                    </p>
                    <p style="color:#475569;font-size:11px;margin:8px 0 0 0;">
                        Generated by Intraday Trading App • {datetime.now(IST).strftime("%H:%M IST")}
                    </p>
                </td></tr>
            </table>
        </td></tr>
    </table>
</body>
</html>"""
    return html


def build_plain_text(predictions):
    """Build a plain-text version for email clients that don't render HTML."""
    today_str = datetime.now(IST).strftime("%A, %B %d, %Y")
    lines = [
        f"📈 Intraday Trading Picks — {today_str}",
        "=" * 50,
        "",
    ]
    for rank, ticker, avg_sentiment, article_count, momentum, reason, h1, h2 in predictions:
        sentiment_str = f"{avg_sentiment:+.3f}" if avg_sentiment else "N/A"
        lines.append(f"#{rank} {ticker}")
        lines.append(f"   Sentiment: {sentiment_str}  |  Momentum: {momentum:.3f}  |  Articles: {article_count}")
        lines.append(f"   Reason: {reason or 'N/A'}")
        if h1:
            lines.append(f"   Headline: {h1}")
        if h2:
            lines.append(f"   Headline: {h2}")
        lines.append("")

    lines.extend([
        "=" * 50,
        "⚠️ These picks are NOT financial advice. Always do your own research.",
        "Pick 3 of these 5 manually before market open.",
    ])
    return "\n".join(lines)


# ─── Send email ───────────────────────────────────────────────────────────────
def send_email(html_body, plain_body):
    """Send the email via SMTP."""
    if not EMAIL_USER or not EMAIL_PASS or not EMAIL_TO:
        logging.error(
            "Email credentials not configured. Set EMAIL_USER, EMAIL_PASS, "
            "and EMAIL_TO in your .env file."
        )
        return False

    today_str = datetime.now(IST).strftime("%B %d, %Y")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📈 Trading Picks — {today_str}"
    msg["From"] = EMAIL_USER
    msg["To"] = EMAIL_TO

    # Attach both plain-text and HTML versions
    msg.attach(MIMEText(plain_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, EMAIL_TO, msg.as_string())
        logging.info(f"Email sent to {EMAIL_TO}")
        return True
    except smtplib.SMTPAuthenticationError:
        logging.error(
            "SMTP authentication failed. For Gmail, use an App Password "
            "(https://myaccount.google.com/apppasswords) instead of your "
            "regular password."
        )
        return False
    except Exception as e:
        logging.error(f"Failed to send email: {e}")
        return False


# ─── Main job ─────────────────────────────────────────────────────────────────
def send_daily_picks():
    """Main job: fetch predictions and send the email."""
    logging.info("Starting daily notification job...")

    predictions = get_todays_predictions()
    if not predictions:
        logging.warning("No predictions found for today. Skipping email.")
        return

    html_body = build_html_email(predictions)
    plain_body = build_plain_text(predictions)
    success = send_email(html_body, plain_body)

    if success:
        logging.info(f"Daily picks email sent successfully ({len(predictions)} stocks).")
    else:
        logging.error("Failed to send daily picks email.")


# ─── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if "--schedule" in sys.argv:
        # Schedule to run daily at 8:30 AM IST
        schedule.every().day.at("08:30").do(send_daily_picks)
        logging.info("Scheduler started. Daily email scheduled for 8:30 AM IST.")
        logging.info("Press Ctrl+C to stop.\n")

        while True:
            try:
                schedule.run_pending()
                time.sleep(30)
            except KeyboardInterrupt:
                logging.info("Notifier stopped by user.")
                print("\nNotifier stopped.")
                break
            except Exception as e:
                logging.error(f"Unexpected error in scheduler: {e}")
                time.sleep(5)
    else:
        # Send immediately (for testing)
        send_daily_picks()
