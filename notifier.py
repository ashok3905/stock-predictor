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
engine = create_engine(os.getenv("DATABASE_URL", "sqlite:///data/news.db"))

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


def get_top3_recommended():
    """Identify the top 3 stocks most likely to rise >1% today.

    Uses the exact same confidence-scoring logic as app.py's
    load_most_recommended(), so the email matches the dashboard exactly.
    Confidence = historical >1% probability + momentum boost + sentiment boost.
    Falls back to a sentiment-based heuristic for new tickers with no history.
    """
    today = datetime.now(IST).strftime("%Y-%m-%d")
    try:
        with engine.connect() as conn:
            preds = conn.execute(text("""
                SELECT rank, ticker, avg_sentiment, article_count,
                       momentum_score, reason_summary, top_headline_1, top_headline_2
                FROM predictions
                WHERE prediction_date = :d
                ORDER BY rank ASC
            """), {"d": today}).fetchall()

            if not preds:
                return []

            ticker_list = [r[1] for r in preds]
            placeholders = ",".join(f":t{i}" for i in range(len(ticker_list)))
            params = {f"t{i}": t for i, t in enumerate(ticker_list)}

            ticker_stats = conn.execute(text(f"""
                SELECT ticker,
                       COUNT(*) as total_predictions,
                       SUM(CASE WHEN day_change_pct > 1 THEN 1 ELSE 0 END) as above_1pct,
                       ROUND(AVG(day_change_pct), 2) as avg_change
                FROM prediction_accuracy
                WHERE ticker IN ({placeholders})
                  AND day_change_pct IS NOT NULL
                GROUP BY ticker
            """), params).fetchall()

        ticker_prob = {}
        for r in ticker_stats:
            ticker, total, above_1pct, avg_change = r
            ticker_prob[ticker] = {
                "total": total,
                "prob": (above_1pct / total * 100) if total > 0 else 0,
                "avg_change": avg_change,
            }

        results = []
        for pred in preds:
            rank, ticker, sentiment, articles, momentum, reason, h1, h2 = pred
            hist = ticker_prob.get(ticker, {"total": 0, "prob": 0, "avg_change": 0})

            if hist["total"] >= 2:
                base_confidence = hist["prob"]
            else:
                base_confidence = max(0, (sentiment - 0.1) * 100)

            momentum_factor = min(momentum * 5, 20)
            sentiment_factor = max(0, (sentiment - 0.2) * 30)
            final_confidence = min(base_confidence + momentum_factor + sentiment_factor, 99.9)

            results.append({
                "ticker": ticker,
                "sentiment": sentiment,
                "momentum": momentum,
                "articles": articles,
                "reason": reason or "No reason available",
                "h1": h1,
                "h2": h2,
                "confidence": round(final_confidence, 1),
            })

        results.sort(key=lambda x: x["confidence"], reverse=True)
        return results[:3]

    except Exception as e:
        logging.warning(f"Could not compute top 3 recommended: {e}")
        return []


# ─── Build HTML email ────────────────────────────────────────────────────────
def build_top3_html(top3):
    """Build the highlighted Top 3 Most Likely to Rise >1% section."""
    if not top3:
        return ""

    cards = ""
    medals = ["🥇", "🥈", "🥉"]
    for i, stock in enumerate(top3):
        medal = medals[i] if i < 3 else f"#{i+1}"
        conf_color = "#4ade80" if stock["confidence"] >= 60 else "#f59e0b" if stock["confidence"] >= 40 else "#94a3b8"
        cards += f"""
        <td width="33%" style="padding:0 6px;" valign="top">
            <div style="background:linear-gradient(135deg,rgba(30,41,59,0.9),rgba(45,27,105,0.5));border:1px solid rgba(245,158,11,0.25);border-radius:12px;padding:16px;text-align:center;">
                <div style="font-size:24px;margin-bottom:4px;">{medal}</div>
                <div style="font-size:20px;font-weight:800;color:#f1f5f9;margin:4px 0;">{stock["ticker"]}</div>
                <div style="font-size:22px;font-weight:700;color:{conf_color};margin:6px 0;">{stock["confidence"]}%</div>
                <div style="font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:0.5px;">Confidence</div>
                <div style="margin-top:10px;font-size:12px;color:#94a3b8;">
                    Sentiment: <span style="color:#60a5fa;font-weight:600;">{stock["sentiment"]:+.3f}</span>
                </div>
                <div style="font-size:12px;color:#94a3b8;margin-top:2px;">
                    Momentum: <span style="color:#e2e8f0;font-weight:600;">{stock["momentum"]:.3f}</span>
                </div>
                <div style="margin-top:10px;font-size:11px;color:#cbd5e1;background:rgba(59,130,246,0.1);border-radius:6px;padding:6px 8px;text-align:left;">
                    {stock["reason"][:120]}{"..." if len(stock["reason"]) > 120 else ""}
                </div>
            </div>
        </td>"""

    return f"""
    <tr><td style="padding:0 20px 24px 20px;">
        <div style="background:linear-gradient(135deg,#1e293b,#2d1b69,#1e293b);border:1px solid rgba(245,158,11,0.3);border-radius:14px;padding:20px;">
            <div style="text-align:center;margin-bottom:16px;">
                <div style="font-size:20px;font-weight:800;color:#fbbf24;">🎯 Top 3 Most Likely to Rise >1% Today</div>
                <div style="font-size:12px;color:#94a3b8;margin-top:4px;">Ranked by confidence score — sentiment + momentum + historical accuracy</div>
            </div>
            <table width="100%" cellpadding="0" cellspacing="0">
                <tr>{cards}</tr>
            </table>
        </div>
    </td></tr>"""


def build_html_email(predictions, top3=None):
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
                <!-- Top 3 Most Likely to Rise >1% -->
                {build_top3_html(top3) if top3 else ""}
                <!-- All Top 5 Stock Cards -->
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


def build_plain_text(predictions, top3=None):
    """Build a plain-text version for email clients that don't render HTML."""
    today_str = datetime.now(IST).strftime("%A, %B %d, %Y")
    lines = [
        f"📈 Intraday Trading Picks — {today_str}",
        "=" * 50,
        "",
    ]

    # Top 3 section
    if top3:
        lines.append("🎯 TOP 3 MOST LIKELY TO RISE >1% TODAY")
        lines.append("-" * 40)
        medals = ["🥇", "🥈", "🥉"]
        for i, stock in enumerate(top3):
            lines.append(f"{medals[i]} {stock['ticker']}  —  Confidence: {stock['confidence']}%")
            lines.append(f"   Sentiment: {stock['sentiment']:+.3f}  |  Momentum: {stock['momentum']:.3f}")
            lines.append(f"   Reason: {stock['reason']}")
            lines.append("")
        lines.append("=" * 50)
        lines.append("")

    lines.append("ALL TOP 5 PREDICTIONS")
    lines.append("-" * 40)
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

    # Get top 3 most likely to rise >1% (may be empty if no history yet)
    top3 = get_top3_recommended()
    if top3:
        logging.info(f"Top 3 recommended: {[s['ticker'] for s in top3]}")
    else:
        logging.info("No top-3 confidence data yet (runs after prediction_accuracy is populated).")

    html_body = build_html_email(predictions, top3=top3)
    plain_body = build_plain_text(predictions, top3=top3)
    success = send_email(html_body, plain_body)

    if success:
        logging.info(f"Daily picks email sent successfully ({len(predictions)} stocks, {len(top3)} top picks).")
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
