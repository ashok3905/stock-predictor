"""
predictor.py — Prediction Engine for Intraday Trading App
Reads the latest sentiment momentum scores per ticker and selects the
top 5 stocks for the day. Designed to run once daily, around 8:30 AM IST,
after collector.py and sentiment.py have built up the day's news data.
"""

import os
import re
import logging
from collections import Counter
from datetime import datetime
from sqlalchemy import create_engine, text

# ─── Logging setup ────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
os.makedirs("data", exist_ok=True)

logging.basicConfig(
    filename="logs/predictor.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
console.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
logging.getLogger().addHandler(console)

# ─── Database setup ───────────────────────────────────────────────────────────
engine = create_engine(os.getenv("DATABASE_URL", "sqlite:///data/news.db"))

def ensure_predictions_table():
    """Create the predictions table if it doesn't exist."""
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS predictions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                prediction_date TEXT NOT NULL,
                rank            INTEGER,
                ticker          TEXT NOT NULL,
                avg_sentiment   REAL,
                article_count   INTEGER,
                momentum_score  REAL,
                created_at      TEXT
            )
        """))
        conn.commit()
    logging.info("Predictions table ready.")

def ensure_reason_columns():
    """Add reason-related columns to the predictions table if they don't
    already exist. Safe to run multiple times."""
    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(predictions)")).fetchall()]
        if "reason_summary" not in cols:
            conn.execute(text("ALTER TABLE predictions ADD COLUMN reason_summary TEXT"))
            logging.info("Added column: reason_summary")
        if "top_headline_1" not in cols:
            conn.execute(text("ALTER TABLE predictions ADD COLUMN top_headline_1 TEXT"))
            logging.info("Added column: top_headline_1")
        if "top_headline_2" not in cols:
            conn.execute(text("ALTER TABLE predictions ADD COLUMN top_headline_2 TEXT"))
            logging.info("Added column: top_headline_2")
        conn.commit()

# ─── Key-phrase extraction from headlines ──────────────────────────────────
# Financial keyword patterns that indicate WHY a stock might rise.
# Each entry is (compiled_regex, human-readable label).
# Patterns are checked case-insensitively against each headline.
PHRASE_PATTERNS = [
    (re.compile(r"order win|order\s+bag|order from|bagged.*order|contract win|won.*contract", re.I), "Order wins"),
    (re.compile(r"brokerage.*buy|buy call|buy rating|outperform|overweight|target price|brokerage.*recommend", re.I), "Brokerage buy calls"),
    (re.compile(r"upper circuit|locked in upper|hit upper|surge|soar|rally|jump|spike", re.I), "Price surge"),
    (re.compile(r"Q[1-4]\s+result|quarterly result|earnings beat|profit.*rise|revenue.*growth|PAT.*jump|net profit|EBITDA", re.I), "Strong quarterly results"),
    (re.compile(r"Q[1-4]\s+earnings|annual result|full.year result|FY.*result", re.I), "Earnings update"),
    (re.compile(r"dividend|bonus|stock split|buyback", re.I), "Corporate action"),
    (re.compile(r"FII.*buy|DII.*buy|foreign.*invest|institutional.*buy|FIIs.*net buy", re.I), "Institutional buying"),
    (re.compile(r"upgrade|upgraded|initiate.*coverage|initiat.*buy", re.I), "Analyst upgrade"),
    (re.compile(r"market share|new client|expansion|capacity.*add|new plant|greenfield", re.I), "Growth catalyst"),
    (re.compile(r"debt.*reduc|asset sale|stake sale|strategic.*partner|JV|joint venture", re.I), "Strategic move"),
    (re.compile(r"pat.*record|profit.*record|revenue.*record|all.time high|lifetime high", re.I), "Record performance"),
]


def extract_key_phrases(headlines, max_phrases=3):
    """Scan a list of headline strings for known financial keyword patterns.
    Returns up to `max_phrases` most frequent matching labels.
    """
    phrase_counts = Counter()
    for headline in headlines:
        for pattern, label in PHRASE_PATTERNS:
            if pattern.search(headline):
                phrase_counts[label] += 1
    # Return phrases sorted by frequency (most common first)
    return [label for label, _ in phrase_counts.most_common(max_phrases)]


def get_reason(ticker, top_n_headlines=3, connection=None):
    """Build a human-readable reason for why a ticker was predicted, using
    REAL data only — never a fabricated narrative. Returns:
      - reason_str: a short summary like "2/4 articles positive; Brokerage buy calls; Price surge"
      - headlines: list of top N most positive actual headlines

    If `connection` (SQLAlchemy connection) is provided, reuses it instead of
    opening a new connection. This prevents "database is locked" errors when
    called from save_predictions() which already holds a write transaction.
    """
    if connection is not None:
        conn = connection
        top_headlines = conn.execute(text("""
            SELECT title, sentiment_score FROM news
            WHERE tickers LIKE :pattern AND sentiment_score IS NOT NULL
            ORDER BY sentiment_score DESC
            LIMIT :n
        """), {"pattern": f"%{ticker}%", "n": top_n_headlines}).fetchall()

        counts = conn.execute(text("""
            SELECT sentiment_label, COUNT(*) FROM news
            WHERE tickers LIKE :pattern AND sentiment_score IS NOT NULL
            GROUP BY sentiment_label
        """), {"pattern": f"%{ticker}%"}).fetchall()
    else:
        with engine.connect() as conn:
            top_headlines = conn.execute(text("""
                SELECT title, sentiment_score FROM news
                WHERE tickers LIKE :pattern AND sentiment_score IS NOT NULL
                ORDER BY sentiment_score DESC
                LIMIT :n
            """), {"pattern": f"%{ticker}%", "n": top_n_headlines}).fetchall()

            counts = conn.execute(text("""
                SELECT sentiment_label, COUNT(*) FROM news
                WHERE tickers LIKE :pattern AND sentiment_score IS NOT NULL
                GROUP BY sentiment_label
            """), {"pattern": f"%{ticker}%"}).fetchall()

    count_dict = dict(counts)
    pos = count_dict.get("positive", 0)
    neg = count_dict.get("negative", 0)
    neu = count_dict.get("neutral", 0)
    total = pos + neg + neu

    # Build sentiment ratio part of the reason
    reason_parts = [f"{pos}/{total} articles positive"]
    if neg > 0:
        reason_parts.append(f"{neg} negative")

    # Extract key financial phrases from the top headlines
    headline_texts = [h[0] for h in top_headlines]
    key_phrases = extract_key_phrases(headline_texts)
    reason_parts.extend(key_phrases)

    reason_str = "; ".join(reason_parts)
    return reason_str, headline_texts

# ─── Core prediction logic ────────────────────────────────────────────────────
MIN_ARTICLE_COUNT = 3  # require at least this many articles for a reliable signal

def get_latest_ticker_sentiment(min_articles=MIN_ARTICLE_COUNT):
    """Fetch the most recent sentiment snapshot for each ticker.

    Uses each ticker's latest `updated_at` snapshot only (not historical ones,
    since sentiment.py may run multiple times before the daily cutoff).
    Filters out tickers with too few articles, since a single hyped headline
    shouldn't be enough to justify a pick — momentum needs real news volume
    behind it.
    """
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT ticker, avg_sentiment, article_count, positive_count,
                   negative_count, neutral_count, momentum_score, updated_at
            FROM ticker_sentiment t1
            WHERE updated_at = (
                SELECT MAX(updated_at) FROM ticker_sentiment t2
                WHERE t2.ticker = t1.ticker
            )
            AND article_count >= :min_articles
            ORDER BY momentum_score DESC
        """), {"min_articles": min_articles}).fetchall()
    return rows

def select_top_stocks(top_n=5, min_articles=MIN_ARTICLE_COUNT):
    """Select the top N stocks by momentum score.

    Only considers stocks with positive average sentiment — a stock with
    negative sentiment, however high its article volume, has no business
    being on a "likely to rise" list. Momentum score already factors in
    both sentiment strength and volume, so ranking by it directly is sound,
    but we still gate on avg_sentiment > 0 as a sanity floor.
    """
    rows = get_latest_ticker_sentiment(min_articles=min_articles)

    if not rows:
        logging.warning("No ticker sentiment data available for prediction.")
        return []

    # Filter to only positive-sentiment stocks, then take top N by momentum
    positive_rows = [r for r in rows if r[1] > 0]

    if not positive_rows:
        logging.warning("No stocks with positive sentiment found today.")
        return []

    top_stocks = positive_rows[:top_n]
    return top_stocks

# ─── Save predictions ─────────────────────────────────────────────────────────
def save_predictions(top_stocks):
    """Save today's top picks into the predictions table, including a reason
    for each pick derived from real headlines and sentiment data."""
    if not top_stocks:
        logging.info("No predictions to save.")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with engine.connect() as conn:
        # Remove any existing predictions for today before saving fresh ones,
        # so re-running predictor.py on the same day doesn't create duplicates.
        conn.execute(text("DELETE FROM predictions WHERE prediction_date = :d"), {"d": today})

        for rank, row in enumerate(top_stocks, start=1):
            ticker, avg_sentiment, article_count = row[0], row[1], row[2]
            momentum_score = row[6]

            # Build the reason from real headlines and sentiment breakdown
            # Pass the connection to avoid "database is locked" errors
            reason_str, headlines = get_reason(ticker, connection=conn)

            conn.execute(text("""
                INSERT INTO predictions
                (prediction_date, rank, ticker, avg_sentiment, article_count,
                 momentum_score, reason_summary, top_headline_1, top_headline_2, created_at)
                VALUES (:d, :r, :t, :a, :c, :m, :reason, :h1, :h2, :now)
            """), {
                "d": today, "r": rank, "t": ticker,
                "a": round(avg_sentiment, 4), "c": article_count,
                "m": round(momentum_score, 4),
                "reason": reason_str,
                "h1": headlines[0] if len(headlines) > 0 else None,
                "h2": headlines[1] if len(headlines) > 1 else None,
                "now": now,
            })
        conn.commit()

    logging.info(f"Saved {len(top_stocks)} predictions for {today} (with reasons).")

# ─── Display ───────────────────────────────────────────────────────────────────
def print_predictions(top_stocks):
    """Print today's predicted top stocks to the console, with reasons.
    Reads the saved reasons from the DB (already persisted by save_predictions)
    to avoid redundant queries."""
    if not top_stocks:
        print("\nNo predictions available — not enough positive-sentiment news today.\n")
        return

    # Fetch the saved predictions (which include reasons) from the DB
    saved = get_todays_predictions()
    reason_map = {row[1]: row[5] for row in saved}  # ticker -> reason_summary

    today = datetime.now().strftime("%Y-%m-%d (%A)")
    print(f"\n{'='*80}")
    print(f"  TODAY'S TOP {len(top_stocks)} PREDICTED STOCKS — {today}")
    print(f"{'='*80}")
    print(f"  {'Rank':<6}{'Ticker':<15}{'Sentiment':<12}{'Articles':<10}{'Momentum':<10}")
    print(f"  {'-'*73}")
    for rank, row in enumerate(top_stocks, start=1):
        ticker, avg_sentiment, article_count, momentum_score = row[0], row[1], row[2], row[6]
        reason_str = reason_map.get(ticker, "No reason available")
        print(f"  {rank:<6}{ticker:<15}{avg_sentiment:<12.3f}{article_count:<10}{momentum_score:<10.3f}")
        print(f"         Reason: {reason_str}")
    print(f"{'='*80}")
    print("  Reminder: pick 3 of these 5 manually before market open.")
    print(f"{'='*80}\n")

def get_todays_predictions():
    """Fetch today's saved predictions from the database (for use by other
    scripts, e.g. the Streamlit dashboard or the email notifier).
    Returns rows with: rank, ticker, avg_sentiment, article_count,
    momentum_score, reason_summary, top_headline_1, top_headline_2."""
    today = datetime.now().strftime("%Y-%m-%d")
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT rank, ticker, avg_sentiment, article_count, momentum_score,
                   reason_summary, top_headline_1, top_headline_2
            FROM predictions
            WHERE prediction_date = :d
            ORDER BY rank ASC
        """), {"d": today}).fetchall()
    return rows

# ─── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.info("Starting prediction engine...")

    ensure_predictions_table()
    ensure_reason_columns()

    top_stocks = select_top_stocks(top_n=5, min_articles=MIN_ARTICLE_COUNT)
    save_predictions(top_stocks)
    print_predictions(top_stocks)

    logging.info("Prediction engine run complete.")