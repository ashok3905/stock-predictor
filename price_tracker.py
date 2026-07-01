"""
price_tracker.py — Live NSE Price Tracker for Intraday Trading App
Fetches current stock prices for predicted tickers and tracks intraday
price movements to measure prediction accuracy.

Run during market hours (9:15 AM - 3:30 PM IST):
  python price_tracker.py              (fetch once)
  python price_tracker.py --schedule   (fetch every 5 min during market hours)
"""

import os
import sys
import time
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import schedule
import yfinance as yf
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

# ─── Setup ────────────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
os.makedirs("data", exist_ok=True)

logging.basicConfig(
    filename="logs/price_tracker.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
console.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
logging.getLogger().addHandler(console)

engine = create_engine(os.getenv("DATABASE_URL", "sqlite:///data/news.db"))
IST = ZoneInfo("Asia/Kolkata")


# ─── Database schema ─────────────────────────────────────────────────────────
def ensure_price_table():
    """Create the stock_prices table if it doesn't exist."""
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS stock_prices (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker          TEXT NOT NULL,
                trade_date      TEXT NOT NULL,
                open_price      REAL,
                high_price      REAL,
                low_price       REAL,
                close_price     REAL,
                current_price   REAL,
                prev_close      REAL,
                day_change      REAL,
                day_change_pct  REAL,
                volume          INTEGER,
                fetched_at      TEXT
            )
        """))
        conn.commit()
    logging.info("stock_prices table ready.")


def ensure_accuracy_table():
    """Create the prediction_accuracy table to track pick performance."""
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS prediction_accuracy (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                prediction_date TEXT NOT NULL,
                rank            INTEGER,
                ticker          TEXT NOT NULL,
                sentiment       REAL,
                momentum        REAL,
                reason_summary  TEXT,
                open_price      REAL,
                current_price   REAL,
                day_change_pct  REAL,
                correct         INTEGER,
                fetched_at      TEXT
            )
        """))
        conn.commit()
    logging.info("prediction_accuracy table ready.")


# ─── Ticker conversion ───────────────────────────────────────────────────────
def to_yfinance_ticker(nse_ticker):
    """Convert NSE ticker (e.g. 'SUZLON') to Yahoo Finance format ('SUZLON.NS')."""
    return f"{nse_ticker}.NS"


# ─── Price fetching ───────────────────────────────────────────────────────────
def fetch_current_prices(tickers):
    """Fetch current market data for a list of NSE tickers using yfinance.

    Returns dict: ticker -> {current, open, high, low, close, prev_close, volume}
    """
    if not tickers:
        return {}

    yf_tickers = [to_yfinance_ticker(t) for t in tickers]
    results = {}

    try:
        # Download data for all tickers at once (more efficient)
        data = yf.download(
            yf_tickers,
            period="2d",
            interval="1d",
            progress=False,
        )

        if data.empty:
            logging.warning("No price data returned from yfinance.")
            return {}

        for ticker in tickers:
            yf_ticker = to_yfinance_ticker(ticker)
            try:
                if len(yf_tickers) == 1:
                    # Single ticker: yfinance returns flat columns
                    close_col = "Close"
                    open_col = "Open"
                    high_col = "High"
                    low_col = "Low"
                    vol_col = "Volume"
                    df = data
                else:
                    # Multiple tickers: columns are MultiIndex (Price, Ticker)
                    close_col = ("Close", yf_ticker)
                    open_col = ("Open", yf_ticker)
                    high_col = ("High", yf_ticker)
                    low_col = ("Low", yf_ticker)
                    vol_col = ("Volume", yf_ticker)
                    df = data

                if close_col not in df.columns:
                    continue

                # Get latest row (today) and previous row (yesterday)
                latest = df.iloc[-1]
                prev = df.iloc[-2] if len(df) > 1 else None

                current = float(latest[close_col]) if pd.notna(latest[close_col]) else None
                open_price = float(latest[open_col]) if pd.notna(latest[open_col]) else None
                high = float(latest[high_col]) if pd.notna(latest[high_col]) else None
                low = float(latest[low_col]) if pd.notna(latest[low_col]) else None
                volume = int(latest[vol_col]) if pd.notna(latest[vol_col]) else None
                prev_close = float(prev[close_col]) if prev is not None and pd.notna(prev[close_col]) else None

                if current and prev_close:
                    day_change = current - prev_close
                    day_change_pct = (day_change / prev_close) * 100
                else:
                    day_change = None
                    day_change_pct = None

                results[ticker] = {
                    "current": current,
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "close": current,
                    "prev_close": prev_close,
                    "day_change": day_change,
                    "day_change_pct": day_change_pct,
                    "volume": volume,
                }
            except Exception as e:
                logging.warning(f"Failed to parse data for {ticker}: {e}")

    except Exception as e:
        logging.error(f"yfinance download error: {e}")

    return results


# ─── Save prices to DB ────────────────────────────────────────────────────────
def save_prices(prices):
    """Save fetched prices to the stock_prices table."""
    if not prices:
        return

    today = datetime.now(IST).strftime("%Y-%m-%d")
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

    with engine.connect() as conn:
        # Remove existing prices for today to prevent duplicates on scheduled runs
        conn.execute(text("DELETE FROM stock_prices WHERE trade_date = :d"), {"d": today})
        for ticker, data in prices.items():
            conn.execute(text("""
                INSERT INTO stock_prices
                (ticker, trade_date, open_price, high_price, low_price,
                 close_price, current_price, prev_close, day_change,
                 day_change_pct, volume, fetched_at)
                VALUES (:t, :d, :o, :h, :l, :c, :cp, :pc, :dc, :dcp, :v, :now)
            """), {
                "t": ticker, "d": today,
                "o": data["open"], "h": data["high"], "l": data["low"],
                "c": data["close"], "cp": data["current"],
                "pc": data["prev_close"], "dc": data["day_change"],
                "dcp": data["day_change_pct"], "v": data["volume"],
                "now": now,
            })
        conn.commit()
    logging.info(f"Saved prices for {len(prices)} tickers.")


# ─── Accuracy tracking ────────────────────────────────────────────────────────
def update_prediction_accuracy(prices):
    """Compare today's predictions against actual price movements and
    store the results in the prediction_accuracy table."""
    today = datetime.now(IST).strftime("%Y-%m-%d")
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

    with engine.connect() as conn:
        preds = conn.execute(text("""
            SELECT rank, ticker, avg_sentiment, momentum_score, reason_summary
            FROM predictions
            WHERE prediction_date = :d
            ORDER BY rank ASC
        """), {"d": today}).fetchall()

        if not preds:
            return

        # Clear old accuracy data for today before inserting fresh
        conn.execute(text("DELETE FROM prediction_accuracy WHERE prediction_date = :d"), {"d": today})

        for rank, ticker, sentiment, momentum, reason in preds:
            price_data = prices.get(ticker)
            if not price_data or not price_data["day_change_pct"]:
                continue

            day_change_pct = price_data["day_change_pct"]
            # Prediction is "correct" if stock moved up (positive change)
            correct = 1 if day_change_pct > 0 else 0

            conn.execute(text("""
                INSERT INTO prediction_accuracy
                (prediction_date, rank, ticker, sentiment, momentum,
                 reason_summary, open_price, current_price, day_change_pct,
                 correct, fetched_at)
                VALUES (:d, :r, :t, :s, :m, :reason, :o, :cp, :dcp, :c, :now)
            """), {
                "d": today, "r": rank, "t": ticker, "s": sentiment,
                "m": momentum, "reason": reason,
                "o": price_data["open"], "cp": price_data["current"],
                "dcp": day_change_pct, "c": correct, "now": now,
            })
        conn.commit()

    logging.info(f"Updated prediction accuracy for {len(preds)} stocks.")


# ─── Console display ──────────────────────────────────────────────────────────
def print_live_prices(prices):
    """Print a formatted table of live prices."""
    if not prices:
        print("\nNo price data available.\n")
        return

    today = datetime.now(IST).strftime("%A, %B %d, %Y %H:%M IST")
    print(f"\n{'='*75}")
    print(f"  LIVE NSE PRICES — {today}")
    print(f"{'='*75}")
    print(f"  {'Ticker':<12}{'Price':>10}{'Change':>10}{'Change%':>10}{'Volume':>12}")
    print(f"  {'-'*54}")
    for ticker, data in sorted(prices.items()):
        price = data["current"] or 0
        change = data["day_change"] or 0
        change_pct = data["day_change_pct"] or 0
        volume = data["volume"] or 0
        sign = "+" if change >= 0 else ""
        print(f"  {ticker:<12}{price:>10.2f}{sign}{change:>9.2f}{sign}{change_pct:>9.2f}%{volume:>12,}")
    print(f"{'='*75}\n")


def print_accuracy():
    """Print prediction accuracy summary for today."""
    today = datetime.now(IST).strftime("%Y-%m-%d")
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT rank, ticker, sentiment, momentum, open_price,
                   current_price, day_change_pct, correct
            FROM prediction_accuracy
            WHERE prediction_date = :d
            ORDER BY rank ASC
        """), {"d": today}).fetchall()

    if not rows:
        print("\nNo accuracy data available for today.\n")
        return

    correct_count = sum(1 for r in rows if r[7] == 1)
    total = len(rows)
    accuracy = (correct_count / total * 100) if total > 0 else 0

    print(f"\n{'='*80}")
    print(f"  PREDICTION ACCURACY — {today}")
    print(f"  Correct: {correct_count}/{total} ({accuracy:.0f}%)")
    print(f"{'='*80}")
    print(f"  {'Rank':<6}{'Ticker':<12}{'Sentiment':>10}{'Momentum':>10}{'Open':>10}{'Current':>10}{'Change%':>10}{'Result':>8}")
    print(f"  {'-'*76}")
    for rank, ticker, sentiment, momentum, open_p, current, change_pct, correct in rows:
        result = "[+]" if correct else "[-]"
        sent_str = f"{sentiment:+.3f}" if sentiment else "N/A"
        mom_str = f"{momentum:.3f}" if momentum else "N/A"
        opn = f"{open_p:.2f}" if open_p else "N/A"
        cur = f"{current:.2f}" if current else "N/A"
        chg = f"{change_pct:+.2f}%" if change_pct else "N/A"
        print(f"  {rank:<6}{ticker:<12}{sent_str:>10}{mom_str:>10}{opn:>10}{cur:>10}{chg:>10}{result:>8}")
    print(f"{'='*80}\n")


# ─── Main job ─────────────────────────────────────────────────────────────────
def fetch_and_track():
    """Main job: fetch prices for predicted tickers and update accuracy."""
    logging.info("Starting price fetch cycle...")

    today = datetime.now(IST).strftime("%Y-%m-%d")
    with engine.connect() as conn:
        tickers = conn.execute(text("""
            SELECT DISTINCT ticker FROM predictions
            WHERE prediction_date = :d
        """), {"d": today}).fetchall()

    ticker_list = [r[0] for r in tickers]
    if not ticker_list:
        logging.info("No predictions found for today. Nothing to track.")
        return

    logging.info(f"Fetching prices for: {', '.join(ticker_list)}")
    prices = fetch_current_prices(ticker_list)

    if prices:
        save_prices(prices)
        update_prediction_accuracy(prices)
        print_live_prices(prices)
        print_accuracy()
    else:
        logging.warning("No price data fetched.")

    logging.info("Price fetch cycle complete.")


# ─── Market hours check ──────────────────────────────────────────────────────
def is_market_hours():
    """Check if current time is within NSE market hours (9:15 AM - 3:30 PM IST)."""
    now = datetime.now(IST)
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


# ─── Backtesting ──────────────────────────────────────────────────────────────
def backtest_predictions():
    """Backtest all past predictions by fetching actual prices on prediction dates.
    For each prediction date, fetches the stock price and records whether the pick
    was correct (stock went up that day)."""
    today = datetime.now(IST).strftime("%Y-%m-%d")
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

    with engine.connect() as conn:
        # Find all prediction dates that don't have accuracy data yet
        pred_dates = conn.execute(text("""
            SELECT DISTINCT prediction_date FROM predictions
            WHERE prediction_date < :today
            ORDER BY prediction_date ASC
        """), {"today": today}).fetchall()

        existing_dates = conn.execute(text("""
            SELECT DISTINCT prediction_date FROM prediction_accuracy
        """)).fetchall()
        existing_set = {r[0] for r in existing_dates}

        dates_to_backtest = [r[0] for r in pred_dates if r[0] not in existing_set]

    if not dates_to_backtest:
        print("\n[OK] All predictions already have accuracy data. Nothing to backtest.\n")
        return

    print(f"\n[INFO] Backtesting {len(dates_to_backtest)} prediction dates...\n")

    for pred_date in dates_to_backtest:
        print(f"  [{pred_date}]")

        with engine.connect() as conn:
            preds = conn.execute(text("""
                SELECT rank, ticker, avg_sentiment, momentum_score, reason_summary
                FROM predictions
                WHERE prediction_date = :d
                ORDER BY rank ASC
            """), {"d": pred_date}).fetchall()

        if not preds:
            print(f"    No predictions found. Skipping.")
            continue

        # Collect all tickers for this date and batch-fetch prices
        # Start 2 days before pred_date so iloc[0] = day before, iloc[1] = pred_date
        tickers = [r[1] for r in preds]
        yf_tickers = [to_yfinance_ticker(t) for t in tickers]
        pred_dt = datetime.strptime(pred_date, "%Y-%m-%d")
        start = (pred_dt - timedelta(days=3)).strftime("%Y-%m-%d")
        end = (pred_dt + timedelta(days=7)).strftime("%Y-%m-%d")

        try:
            data = yf.download(yf_tickers, start=start, end=end, progress=False)
        except Exception as e:
            logging.warning(f"yfinance error for {pred_date}: {e}")
            print(f"    [SKIP] Failed to fetch prices.")
            continue

        if data.empty:
            print(f"    [SKIP] No price data available.")
            continue

        # Build price lookup: for each ticker, find the pred_date row
        # Data starts 3 days before pred_date, so iloc[0]=day_before, iloc[1]=pred_date
        # We scan for the row whose date matches pred_date
        price_lookup = {}
        for ticker in tickers:
            yf_t = to_yfinance_ticker(ticker)
            try:
                if len(yf_tickers) == 1:
                    df = data
                    close_col, open_col = "Close", "Open"
                else:
                    close_col = ("Close", yf_t)
                    open_col = ("Open", yf_t)
                    df = data

                if close_col not in df.columns:
                    continue

                # Find the row matching pred_date
                pred_idx = None
                for i in range(len(df)):
                    row_date = df.index[i].strftime("%Y-%m-%d")
                    if row_date == pred_date:
                        pred_idx = i
                        break

                if pred_idx is None:
                    continue

                pred_row = df.iloc[pred_idx]
                open_p = float(pred_row[open_col]) if pd.notna(pred_row[open_col]) else None
                close = float(pred_row[close_col]) if pd.notna(pred_row[close_col]) else None

                # Previous day is pred_idx - 1
                if pred_idx > 0 and pd.notna(df.iloc[pred_idx - 1][close_col]):
                    prev_close = float(df.iloc[pred_idx - 1][close_col])
                    day_change_pct = ((close - prev_close) / prev_close * 100) if close and prev_close else None
                else:
                    day_change_pct = None

                price_lookup[ticker] = {
                    "open": open_p,
                    "current": close,
                    "day_change_pct": day_change_pct,
                }
            except Exception as e:
                logging.warning(f"Parse error for {ticker} on {pred_date}: {e}")

        # Save accuracy records
        with engine.connect() as conn:
            for rank, ticker, sentiment, momentum, reason in preds:
                pdata = price_lookup.get(ticker)
                if not pdata or pdata["day_change_pct"] is None:
                    continue

                correct = 1 if pdata["day_change_pct"] > 0 else 0
                conn.execute(text("""
                    INSERT INTO prediction_accuracy
                    (prediction_date, rank, ticker, sentiment, momentum,
                     reason_summary, open_price, current_price, day_change_pct,
                     correct, fetched_at)
                    VALUES (:d, :r, :t, :s, :m, :reason, :o, :cp, :dcp, :c, :now)
                """), {
                    "d": pred_date, "r": rank, "t": ticker, "s": sentiment,
                    "m": momentum, "reason": reason,
                    "o": pdata["open"], "cp": pdata["current"],
                    "dcp": pdata["day_change_pct"], "c": correct, "now": now,
                })
            conn.commit()

        # Print summary for this date
        records = [(r[1], price_lookup.get(r[1])) for r in preds if price_lookup.get(r[1])]
        if records:
            correct_count = sum(1 for _, p in records if p["day_change_pct"] and p["day_change_pct"] > 0)
            total = len(records)
            acc = (correct_count / total * 100) if total > 0 else 0
            print(f"    [OK] {correct_count}/{total} correct ({acc:.0f}%)")
            for ticker, pdata in records:
                chg = pdata["day_change_pct"]
                symbol = "+" if chg > 0 else "-"
                print(f"      [{symbol}] {ticker}: {chg:+.2f}%")
        else:
            print(f"    [WARN] No price data found for any tickers.")

    print(f"\n[DONE] Backtesting complete! Accuracy data saved to database.\n")


# ─── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ensure_price_table()
    ensure_accuracy_table()

    if "--backtest" in sys.argv:
        backtest_predictions()
    elif "--schedule" in sys.argv:
        # Fetch every 5 minutes during market hours
        schedule.every(5).minutes.do(fetch_and_track)
        logging.info("Scheduler started. Fetching prices every 5 min during market hours (9:15-3:30 IST).")
        logging.info("Press Ctrl+C to stop.\n")

        # Run immediately on start
        if is_market_hours():
            fetch_and_track()

        while True:
            try:
                schedule.run_pending()
                time.sleep(30)
            except KeyboardInterrupt:
                logging.info("Price tracker stopped by user.")
                print("\nPrice tracker stopped.")
                break
            except Exception as e:
                logging.error(f"Unexpected error: {e}")
                time.sleep(5)
    else:
        # Fetch once and exit
        fetch_and_track()
