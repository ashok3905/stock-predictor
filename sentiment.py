"""
sentiment.py — Sentiment Analysis for Intraday Trading App
Loads FinBERT, scores unscored articles in news.db, and aggregates
sentiment per stock ticker to support daily stock predictions.
"""

import os
import time
import logging
import pandas as pd
import torch
from datetime import datetime
from sqlalchemy import create_engine, text
from transformers import AutoTokenizer, AutoModelForSequenceClassification

# ─── Logging setup ────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
os.makedirs("data", exist_ok=True)

logging.basicConfig(
    filename="logs/sentiment.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
console.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
logging.getLogger().addHandler(console)

# ─── Database setup ───────────────────────────────────────────────────────────
engine = create_engine(os.getenv("DATABASE_URL", "sqlite:///data/news.db"))

def ensure_sentiment_columns():
    """Add sentiment columns to the news table if they don't already exist.
    Safe to run multiple times — checks before altering."""
    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(news)")).fetchall()]

        if "sentiment_label" not in cols:
            conn.execute(text("ALTER TABLE news ADD COLUMN sentiment_label TEXT"))
            logging.info("Added column: sentiment_label")
        if "sentiment_score" not in cols:
            conn.execute(text("ALTER TABLE news ADD COLUMN sentiment_score REAL"))
            logging.info("Added column: sentiment_score")
        if "sentiment_positive" not in cols:
            conn.execute(text("ALTER TABLE news ADD COLUMN sentiment_positive REAL"))
            logging.info("Added column: sentiment_positive")
        if "sentiment_negative" not in cols:
            conn.execute(text("ALTER TABLE news ADD COLUMN sentiment_negative REAL"))
            logging.info("Added column: sentiment_negative")
        if "sentiment_neutral" not in cols:
            conn.execute(text("ALTER TABLE news ADD COLUMN sentiment_neutral REAL"))
            logging.info("Added column: sentiment_neutral")
        conn.commit()

def ensure_ticker_sentiment_table():
    """Create the aggregated per-ticker sentiment table."""
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ticker_sentiment (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker          TEXT NOT NULL,
                avg_sentiment   REAL,
                article_count   INTEGER,
                positive_count  INTEGER,
                negative_count  INTEGER,
                neutral_count   INTEGER,
                momentum_score  REAL,
                updated_at      TEXT
            )
        """))
        conn.commit()

# ─── FinBERT model loading ────────────────────────────────────────────────────
MODEL_NAME = "ProsusAI/finbert"
_tokenizer = None
_model = None

def load_model():
    """Load FinBERT tokenizer and model once, reused across the run."""
    global _tokenizer, _model
    if _model is not None:
        return
    logging.info(f"Loading FinBERT model ({MODEL_NAME})... this may take a minute on first run.")
    _tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    _model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)
    _model.eval()
    logging.info(f"Model loaded. Labels: {_model.config.id2label}")

def score_text(text_input):
    """Run FinBERT on a single piece of text and return (label, score, probs dict).

    score = positive_prob - negative_prob, ranging from -1 (very negative)
    to +1 (very positive). This is the standard FinBERT sentiment score formula.
    """
    if not text_input or not text_input.strip():
        return "neutral", 0.0, {"positive": 0.0, "negative": 0.0, "neutral": 1.0}

    inputs = _tokenizer(
        text_input,
        return_tensors="pt",
        truncation=True,
        max_length=512
    )

    with torch.no_grad():
        outputs = _model(**inputs)
        probs = torch.softmax(outputs.logits, dim=1)[0]

    # FinBERT's id2label is {0: 'positive', 1: 'negative', 2: 'neutral'}
    id2label = _model.config.id2label
    prob_dict = {id2label[i].lower(): probs[i].item() for i in range(len(probs))}

    positive = prob_dict.get("positive", 0.0)
    negative = prob_dict.get("negative", 0.0)
    neutral  = prob_dict.get("neutral", 0.0)

    label = max(prob_dict, key=prob_dict.get)
    score = positive - negative

    return label, score, {"positive": positive, "negative": negative, "neutral": neutral}

# ─── Read unscored articles ───────────────────────────────────────────────────
def get_unscored_articles(limit=200):
    """Fetch articles that haven't been sentiment-scored yet."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, title, description FROM news
            WHERE sentiment_score IS NULL
            ORDER BY id ASC
            LIMIT :limit
        """), {"limit": limit}).fetchall()
    return rows

# ─── Score and save ───────────────────────────────────────────────────────────
def score_articles(batch_size=200):
    """Score unscored articles in batches and write results back to the DB."""
    load_model()

    total_scored = 0
    while True:
        rows = get_unscored_articles(limit=batch_size)
        if not rows:
            break

        with engine.connect() as conn:
            for row_id, title, description in rows:
                # Combine title + description for richer context, title carries more weight
                # by being included once on its own and once in the combined text.
                text_to_score = f"{title or ''}. {description or ''}".strip()

                try:
                    label, score, probs = score_text(text_to_score)
                except Exception as e:
                    logging.error(f"Error scoring article id={row_id}: {e}")
                    continue

                conn.execute(text("""
                    UPDATE news
                    SET sentiment_label = :label,
                        sentiment_score = :score,
                        sentiment_positive = :pos,
                        sentiment_negative = :neg,
                        sentiment_neutral = :neu
                    WHERE id = :id
                """), {
                    "label": label,
                    "score": score,
                    "pos": probs["positive"],
                    "neg": probs["negative"],
                    "neu": probs["neutral"],
                    "id": row_id
                })
                total_scored += 1

            conn.commit()

        logging.info(f"Scored batch of {len(rows)} articles. Total so far: {total_scored}")

    logging.info(f"Finished scoring. Total articles scored this run: {total_scored}")
    return total_scored

# ─── Aggregate sentiment per ticker ───────────────────────────────────────────
def aggregate_ticker_sentiment(recency_hours=24):
    """Aggregate sentiment scores per stock ticker from recently scored articles.

    Articles mentioning multiple tickers (e.g. 'IRFC,RVNL') contribute to
    each ticker individually. GENERAL articles (no specific stock) are excluded.
    A simple momentum score rewards both strong sentiment AND higher article
    volume, capped so one single very active stock doesn't dominate unfairly.
    """
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT tickers, sentiment_score, sentiment_label, fetched_at
            FROM news
            WHERE sentiment_score IS NOT NULL
              AND tickers != 'GENERAL'
              AND datetime(fetched_at) >= datetime('now', :cutoff)
        """), {"cutoff": f"-{recency_hours} hours"}).fetchall()

    if not rows:
        logging.warning("No scored, ticker-specific articles found for aggregation.")
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=["tickers", "sentiment_score", "sentiment_label", "fetched_at"])

    # Explode multi-ticker articles so each mentioned stock gets its own row
    df["ticker_list"] = df["tickers"].str.split(",")
    df = df.explode("ticker_list")
    df = df.rename(columns={"ticker_list": "ticker"})
    df["ticker"] = df["ticker"].str.strip()

    # Aggregate per ticker
    agg = df.groupby("ticker").agg(
        avg_sentiment=("sentiment_score", "mean"),
        article_count=("sentiment_score", "count"),
    ).reset_index()

    # Count positive/negative/neutral articles per ticker
    label_counts = df.groupby(["ticker", "sentiment_label"]).size().unstack(fill_value=0)
    for col in ["positive", "negative", "neutral"]:
        if col not in label_counts.columns:
            label_counts[col] = 0
    label_counts = label_counts.reset_index()

    agg = agg.merge(label_counts, on="ticker", how="left")
    agg = agg.rename(columns={
        "positive": "positive_count",
        "negative": "negative_count",
        "neutral":  "neutral_count",
    })

    # Momentum score: sentiment strength × article volume (capped at 10 articles
    # so one over-covered stock doesn't completely dominate the ranking)
    agg["momentum_score"] = agg["avg_sentiment"] * agg["article_count"].clip(upper=10)
    agg = agg.sort_values("momentum_score", ascending=False).reset_index(drop=True)

    return agg

def save_ticker_sentiment(agg_df):
    """Save the aggregated ticker sentiment snapshot to the database."""
    if agg_df.empty:
        logging.info("No aggregated data to save.")
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    records = []
    for _, row in agg_df.iterrows():
        records.append({
            "ticker":         row["ticker"],
            "avg_sentiment":  round(float(row["avg_sentiment"]), 4),
            "article_count":  int(row["article_count"]),
            "positive_count": int(row["positive_count"]),
            "negative_count": int(row["negative_count"]),
            "neutral_count":  int(row["neutral_count"]),
            "momentum_score": round(float(row["momentum_score"]), 4),
            "updated_at":     now,
        })

    out_df = pd.DataFrame(records)
    out_df.to_sql("ticker_sentiment", engine, if_exists="append", index=False)
    logging.info(f"Saved sentiment snapshot for {len(records)} tickers.")

# ─── Display results ──────────────────────────────────────────────────────────
def print_top_stocks(agg_df, top_n=10):
    """Print the top N stocks by momentum score."""
    if agg_df.empty:
        print("\nNo ticker sentiment data available yet.\n")
        return

    print(f"\n{'='*70}")
    print(f"  TOP {top_n} STOCKS BY SENTIMENT MOMENTUM")
    print(f"{'='*70}")
    print(f"  {'Ticker':<15}{'Avg Sentiment':<16}{'Articles':<10}{'Momentum':<10}")
    print(f"  {'-'*65}")
    for _, row in agg_df.head(top_n).iterrows():
        print(f"  {row['ticker']:<15}{row['avg_sentiment']:<16.3f}{row['article_count']:<10}{row['momentum_score']:<10.3f}")
    print(f"{'='*70}\n")

# ─── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.info("Starting sentiment analysis pipeline...")

    ensure_sentiment_columns()
    ensure_ticker_sentiment_table()

    # Step 1: Score any new/unscored articles
    scored = score_articles(batch_size=200)

    # Step 2: Aggregate sentiment per ticker (last 24 hours of scored articles)
    agg = aggregate_ticker_sentiment(recency_hours=24)

    # Step 3: Save the aggregated snapshot
    save_ticker_sentiment(agg)

    # Step 4: Show results
    print_top_stocks(agg, top_n=10)

    logging.info("Sentiment analysis pipeline complete.")
