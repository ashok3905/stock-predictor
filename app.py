"""
app.py — Streamlit Dashboard for Intraday Trading App
Displays today's top 5 predictions, historical picks, sentiment trends,
live prices, accuracy tracking, and sentiment-accuracy correlation.
Run with: streamlit run app.py
"""

import logging
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text

# ─── Database setup ───────────────────────────────────────────────────────────
# Logging for graceful error handling
logging.basicConfig(level=logging.WARNING, format="%(asctime)s - %(levelname)s - %(message)s")
engine = create_engine("sqlite:///data/news.db")


def load_todays_predictions():
    """Fetch today's saved predictions with reasons."""
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT rank, ticker, avg_sentiment, article_count,
                           momentum_score, reason_summary, top_headline_1,
                           top_headline_2, created_at
                    FROM predictions
                    WHERE prediction_date = :d
                    ORDER BY rank ASC
                """),
                {"d": today},
            ).fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(
            rows,
            columns=[
                "Rank", "Ticker", "Avg Sentiment", "Articles", "Momentum",
                "Reason", "Headline 1", "Headline 2", "Created At",
            ],
        )
    except Exception as e:
        logging.warning(f"Failed to load today's predictions: {e}")
        return pd.DataFrame()


def load_historical_predictions(days=30):
    """Fetch predictions from the last N days."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT prediction_date, rank, ticker, avg_sentiment,
                           article_count, momentum_score, reason_summary,
                           top_headline_1, top_headline_2
                    FROM predictions
                    WHERE prediction_date >= :cutoff
                    ORDER BY prediction_date DESC, rank ASC
                """),
                {"cutoff": cutoff},
            ).fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(
            rows,
            columns=[
                "Date", "Rank", "Ticker", "Sentiment", "Articles",
                "Momentum", "Reason", "Headline 1", "Headline 2",
            ],
        )
    except Exception as e:
        logging.warning(f"Failed to load historical predictions: {e}")
        return pd.DataFrame()


def load_ticker_sentiment_history(ticker, days=30):
    """Fetch historical sentiment snapshots for a specific ticker."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT updated_at, avg_sentiment, article_count,
                           positive_count, negative_count, neutral_count,
                           momentum_score
                    FROM ticker_sentiment
                    WHERE ticker = :ticker AND updated_at >= :cutoff
                    ORDER BY updated_at ASC
                """),
                {"ticker": ticker, "cutoff": cutoff},
            ).fetchall()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(
            rows,
            columns=[
                "Timestamp", "Avg Sentiment", "Articles",
                "Positive", "Negative", "Neutral", "Momentum",
            ],
        )
        df["Timestamp"] = pd.to_datetime(df["Timestamp"])
        return df
    except Exception as e:
        logging.warning(f"Failed to load sentiment history for {ticker}: {e}")
        return pd.DataFrame()


def load_news_by_ticker(ticker, limit=20):
    """Fetch recent news articles for a specific ticker."""
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT title, description, source, sentiment_label,
                           sentiment_score, published_at, url
                    FROM news
                    WHERE tickers LIKE :pattern
                      AND sentiment_score IS NOT NULL
                    ORDER BY published_at DESC
                    LIMIT :limit
                """),
                {"pattern": f"%{ticker}%", "limit": limit},
            ).fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(
            rows,
            columns=[
                "Title", "Description", "Source", "Sentiment",
                "Score", "Published", "URL",
            ],
        )
    except Exception as e:
        logging.warning(f"Failed to load news for {ticker}: {e}")
        return pd.DataFrame()


def load_db_stats():
    """Get quick database statistics."""
    try:
        with engine.connect() as conn:
            news_count = conn.execute(text("SELECT COUNT(*) FROM news")).fetchone()[0]
            scored_count = conn.execute(
                text("SELECT COUNT(*) FROM news WHERE sentiment_score IS NOT NULL")
            ).fetchone()[0]
            ticker_count = conn.execute(
                text("SELECT COUNT(DISTINCT ticker) FROM ticker_sentiment")
            ).fetchone()[0]
            pred_count = conn.execute(
                text("SELECT COUNT(DISTINCT prediction_date) FROM predictions")
            ).fetchone()[0]
        return {
            "Total Articles": news_count,
            "Scored Articles": scored_count,
            "Tracked Tickers": ticker_count,
            "Prediction Days": pred_count,
        }
    except Exception as e:
        logging.warning(f"Failed to load DB stats: {e}")
        return {"Total Articles": 0, "Scored Articles": 0, "Tracked Tickers": 0, "Prediction Days": 0}


def load_todays_accuracy():
    """Fetch today's prediction accuracy with live prices."""
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT rank, ticker, sentiment, momentum, reason_summary,
                           open_price, current_price, day_change_pct, correct
                    FROM prediction_accuracy
                    WHERE prediction_date = :d
                    ORDER BY rank ASC
                """),
                {"d": today},
            ).fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(
            rows,
            columns=[
                "Rank", "Ticker", "Sentiment", "Momentum", "Reason",
                "Open", "Current", "Change %", "Correct",
            ],
        )
    except Exception as e:
        logging.warning(f"Failed to load today's accuracy: {e}")
        return pd.DataFrame()


def load_accuracy_summary(days=30):
    """Get overall accuracy stats per day."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT prediction_date,
                           COUNT(*) as total,
                           SUM(correct) as correct_count,
                           ROUND(AVG(day_change_pct), 2) as avg_change
                    FROM prediction_accuracy
                    WHERE prediction_date >= :cutoff
                    GROUP BY prediction_date
                    ORDER BY prediction_date DESC
                """),
                {"cutoff": cutoff},
            ).fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(
            rows,
            columns=["Date", "Total Picks", "Correct", "Avg Change %"],
        )
    except Exception as e:
        logging.warning(f"Failed to load accuracy summary: {e}")
        return pd.DataFrame()


def load_sentiment_accuracy_data(days=30):
    """Fetch all accuracy records for sentiment-accuracy analysis."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT sentiment, momentum, day_change_pct, correct, ticker
                    FROM prediction_accuracy
                    WHERE prediction_date >= :cutoff
                      AND sentiment IS NOT NULL
                      AND day_change_pct IS NOT NULL
                """),
                {"cutoff": cutoff},
            ).fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(
            rows,
            columns=["Sentiment", "Momentum", "Change %", "Correct", "Ticker"],
        )
    except Exception as e:
        logging.warning(f"Failed to load sentiment accuracy data: {e}")
        return pd.DataFrame()


def load_sentiment_buckets(days=30):
    """Group accuracy data into sentiment buckets and compute accuracy per bucket."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT
                        CASE
                            WHEN sentiment >= 0.5 THEN '0.50+'
                            WHEN sentiment >= 0.4 THEN '0.40-0.50'
                            WHEN sentiment >= 0.3 THEN '0.30-0.40'
                            WHEN sentiment >= 0.2 THEN '0.20-0.30'
                            WHEN sentiment >= 0.1 THEN '0.10-0.20'
                            ELSE '<0.10'
                        END as bucket,
                        COUNT(*) as total,
                        SUM(CASE WHEN day_change_pct > 0 THEN 1 ELSE 0 END) as correct,
                        ROUND(AVG(day_change_pct), 2) as avg_change,
                        ROUND(MIN(day_change_pct), 2) as min_change,
                        ROUND(MAX(day_change_pct), 2) as max_change
                    FROM prediction_accuracy
                    WHERE prediction_date >= :cutoff
                      AND sentiment IS NOT NULL
                      AND day_change_pct IS NOT NULL
                    GROUP BY bucket
                    ORDER BY bucket DESC
                """),
                {"cutoff": cutoff},
            ).fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(
            rows,
            columns=["Sentiment Range", "Total Picks", "Correct", "Avg Change %", "Min Change %", "Max Change %"],
        )
    except Exception as e:
        logging.warning(f"Failed to load sentiment buckets: {e}")
        return pd.DataFrame()


DASHBOARD_CSS = """
<style>
    .main-header {
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #334155 100%);
        padding: 2rem 2.5rem;
        border-radius: 16px;
        margin-bottom: 2rem;
        border: 1px solid rgba(255,255,255,0.05);
        box-shadow: 0 4px 24px rgba(0,0,0,0.3);
    }
    .main-header h1 { color: #f1f5f9; font-size: 2rem; margin: 0; font-weight: 700; }
    .main-header p { color: #94a3b8; font-size: 1rem; margin: 0.5rem 0 0 0; }
    .metric-card {
        background: linear-gradient(135deg, #1e293b, #334155);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 12px; padding: 1.25rem; text-align: center;
    }
    .metric-card .value { font-size: 2rem; font-weight: 700; color: #60a5fa; display: block; }
    .metric-card .label { font-size: 0.85rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; }
    .stock-card {
        background: linear-gradient(135deg, #1e293b, #2d3a4f);
        border: 1px solid rgba(255,255,255,0.08); border-radius: 14px;
        padding: 1.5rem; margin-bottom: 1rem;
        transition: transform 0.2s, box-shadow 0.2s; box-shadow: 0 2px 12px rgba(0,0,0,0.2);
    }
    .stock-card:hover { transform: translateY(-2px); box-shadow: 0 6px 24px rgba(0,0,0,0.3); border-color: rgba(96,165,250,0.3); }
    .stock-card .rank-badge { display: inline-block; background: linear-gradient(135deg, #3b82f6, #2563eb); color: white; font-weight: 700; font-size: 0.85rem; padding: 0.25rem 0.75rem; border-radius: 20px; margin-bottom: 0.75rem; }
    .stock-card .ticker-name { font-size: 1.6rem; font-weight: 800; color: #f1f5f9; margin: 0; }
    .stock-card .stats-row { display: flex; gap: 1.5rem; margin: 0.75rem 0; flex-wrap: wrap; }
    .stock-card .stat { display: flex; flex-direction: column; }
    .stock-card .stat-label { font-size: 0.75rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; }
    .stock-card .stat-value { font-size: 1.1rem; font-weight: 600; color: #e2e8f0; }
    .stock-card .reason-box { background: rgba(59, 130, 246, 0.1); border-left: 3px solid #3b82f6; padding: 0.75rem 1rem; border-radius: 0 8px 8px 0; margin: 0.75rem 0; }
    .stock-card .reason-label { font-size: 0.7rem; color: #60a5fa; text-transform: uppercase; letter-spacing: 0.08em; font-weight: 600; margin-bottom: 0.25rem; }
    .stock-card .reason-text { color: #cbd5e1; font-size: 0.95rem; line-height: 1.5; }
    .stock-card .headline { color: #94a3b8; font-size: 0.85rem; padding: 0.5rem 0; border-bottom: 1px solid rgba(255,255,255,0.05); line-height: 1.4; }
    .stock-card .headline:last-child { border-bottom: none; }
    .positive { color: #4ade80 !important; }
    .negative { color: #f87171 !important; }
    .neutral { color: #94a3b8 !important; }
    .section-header { color: #f1f5f9; font-size: 1.3rem; font-weight: 700; margin: 2rem 0 1rem 0; padding-bottom: 0.5rem; border-bottom: 2px solid rgba(96,165,250,0.2); }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
</style>
"""


@st.cache_data(ttl=300)
def _get_ticker_list():
    """Fetch list of distinct tickers with sentiment data."""
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT DISTINCT ticker FROM ticker_sentiment ORDER BY ticker ASC")
        ).fetchall()
    return [r[0] for r in rows]


def render_stock_card(rank, ticker, sentiment, articles, momentum, reason, h1, h2, reason_label="Why this pick?"):
    """Render a stock prediction card with dark theme styling."""
    if sentiment > 0.3:
        sent_class = "positive"
    elif sentiment < -0.1:
        sent_class = "negative"
    else:
        sent_class = "neutral"

    headlines_html = ""
    if h1:
        headlines_html += f'<div class="headline">{h1}</div>'
    if h2:
        headlines_html += f'<div class="headline">{h2}</div>'

    st.markdown(f"""
    <div class="stock-card">
        <span class="rank-badge">#{rank}</span>
        <h3 class="ticker-name">{ticker}</h3>
        <div class="stats-row">
            <div class="stat">
                <span class="stat-label">Sentiment</span>
                <span class="stat-value {sent_class}">{sentiment:+.3f}</span>
            </div>
            <div class="stat">
                <span class="stat-label">Momentum</span>
                <span class="stat-value">{momentum:.3f}</span>
            </div>
            <div class="stat">
                <span class="stat-label">Articles</span>
                <span class="stat-value">{articles}</span>
            </div>
        </div>
        <div class="reason-box">
            <div class="reason-label">{reason_label}</div>
            <div class="reason-text">{reason}</div>
        </div>
        {f'<div style="margin-top:0.5rem"><span class="stat-label">Top Headlines</span>{headlines_html}</div>' if headlines_html else ''}
    </div>
    """, unsafe_allow_html=True)


def main():
    st.set_page_config(
        page_title="Intraday Trading Dashboard",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    st.markdown(DASHBOARD_CSS, unsafe_allow_html=True)

    st.markdown("""
    <div class="main-header">
        <h1>Intraday Trading Dashboard</h1>
        <p>AI-powered stock picks based on real-time news sentiment analysis</p>
    </div>
    """, unsafe_allow_html=True)

    # DB Stats
    stats = load_db_stats()
    cols = st.columns(4)
    for i, (label, value) in enumerate(stats.items()):
        with cols[i]:
            st.markdown(f"""
            <div class="metric-card">
                <span class="value">{value:,}</span>
                <span class="label">{label}</span>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Tab Navigation
    tab1, tab2, tab3, tab4 = st.tabs([
        "Today's Picks",
        "Historical Predictions",
        "Sentiment Explorer",
        "Live Prices & Accuracy",
    ])

    # ─── Tab 1: Today's Picks ─────────────────────────────────────────────
    with tab1:
        today_df = load_todays_predictions()

        if today_df.empty:
            today_str = datetime.now().strftime("%B %d, %Y")
            st.info(f"No predictions generated yet for **{today_str}**.\n\n"
                     "Run `python predictor.py` to generate today's picks.")
        else:
            date_str = datetime.now().strftime("%A, %B %d, %Y")
            st.markdown(f'<div class="section-header">Top {len(today_df)} Predictions - {date_str}</div>',
                        unsafe_allow_html=True)

            for _, row in today_df.iterrows():
                render_stock_card(
                    rank=int(row["Rank"]),
                    ticker=row["Ticker"],
                    sentiment=row["Avg Sentiment"],
                    articles=int(row["Articles"]),
                    momentum=row["Momentum"],
                    reason=row["Reason"] or "No reason available",
                    h1=row["Headline 1"],
                    h2=row["Headline 2"],
                )

    # ─── Tab 2: Historical Predictions ────────────────────────────────────
    with tab2:
        st.markdown('<div class="section-header">Historical Predictions</div>',
                    unsafe_allow_html=True)

        hist_days = st.slider(
            "Look back (days)", min_value=7, max_value=90, value=30,
            help="Number of days of historical predictions to display",
        )

        hist_df = load_historical_predictions(days=hist_days)

        if hist_df.empty:
            st.info("No historical predictions found for the selected period.")
        else:
            unique_dates = hist_df["Date"].nunique()
            unique_tickers = hist_df["Ticker"].nunique()
            avg_momentum = hist_df["Momentum"].mean()

            c1, c2, c3 = st.columns(3)
            c1.metric("Prediction Days", unique_dates)
            c2.metric("Unique Tickers", unique_tickers)
            c3.metric("Avg Momentum", f"{avg_momentum:.3f}")

            st.markdown("<br>", unsafe_allow_html=True)

            all_dates = sorted(hist_df["Date"].unique(), reverse=True)
            selected_date = st.selectbox(
                "Select a date to view predictions",
                options=all_dates,
                format_func=lambda d: datetime.strptime(d, "%Y-%m-%d").strftime("%A, %B %d, %Y"),
            )

            if selected_date:
                day_df = hist_df[hist_df["Date"] == selected_date].copy()
                day_df = day_df.sort_values("Rank")

                for _, row in day_df.iterrows():
                    render_stock_card(
                        rank=int(row["Rank"]),
                        ticker=row["Ticker"],
                        sentiment=row["Sentiment"],
                        articles=int(row["Articles"]),
                        momentum=row["Momentum"],
                        reason=row["Reason"] or "No reason available",
                        h1=row["Headline 1"],
                        h2=row["Headline 2"],
                        reason_label="Reason",
                    )

    # ─── Tab 3: Sentiment Explorer ────────────────────────────────────────
    with tab3:
        st.markdown('<div class="section-header">Sentiment Explorer</div>',
                    unsafe_allow_html=True)

        ticker_list = _get_ticker_list()

        if not ticker_list:
            st.info("No sentiment data available yet. Run `python sentiment.py` first.")
        else:
            col1, col2 = st.columns([2, 1])
            with col1:
                selected_ticker = st.selectbox(
                    "Select a ticker to explore",
                    options=ticker_list,
                    index=0,
                )
            with col2:
                hist_range = st.selectbox(
                    "Time range",
                    options=[7, 14, 30, 60],
                    index=2,
                    format_func=lambda x: f"Last {x} days",
                )

            if selected_ticker:
                sent_df = load_ticker_sentiment_history(selected_ticker, days=hist_range)

                if sent_df.empty:
                    st.warning(f"No sentiment history found for {selected_ticker} in the last {hist_range} days.")
                else:
                    latest = sent_df.iloc[-1]
                    mc1, mc2, mc3, mc4 = st.columns(4)
                    mc1.metric("Avg Sentiment", f"{latest['Avg Sentiment']:+.3f}")
                    mc2.metric("Momentum", f"{latest['Momentum']:.3f}")
                    mc3.metric("Articles", int(latest["Articles"]))
                    mc4.metric("Data Points", len(sent_df))

                    st.markdown(f"**{selected_ticker}** - Sentiment Trend ({hist_range} days)")
                    chart_df = sent_df.set_index("Timestamp")[["Avg Sentiment", "Momentum"]]
                    st.line_chart(chart_df, height=300)

                    st.markdown("**Article Volume Over Time**")
                    volume_df = sent_df.set_index("Timestamp")[["Positive", "Negative", "Neutral"]]
                    st.bar_chart(volume_df, height=250)

                    st.markdown(f"**Latest News for {selected_ticker}**")
                    news_df = load_news_by_ticker(selected_ticker, limit=10)

                    if not news_df.empty:
                        for _, article in news_df.iterrows():
                            sent = article["Sentiment"]
                            score = article["Score"]
                            if sent == "positive":
                                badge_color = "#4ade80"
                            elif sent == "negative":
                                badge_color = "#f87171"
                            else:
                                badge_color = "#64748b"

                            st.markdown(f"""
                            <div style="padding:0.75rem; margin-bottom:0.5rem; background:rgba(30,41,59,0.5);
                                        border-radius:8px; border-left:3px solid {badge_color};">
                                <div style="font-weight:600; color:#e2e8f0; font-size:0.95rem;">
                                    {article['Title']}
                                </div>
                                <div style="font-size:0.8rem; color:#64748b; margin-top:0.25rem;">
                                    {article['Source']} | {sent} ({score:+.3f}) | {article['Published'][:16] if article['Published'] else 'N/A'}
                                </div>
                            </div>
                            """, unsafe_allow_html=True)
                    else:
                        st.info("No scored news articles found for this ticker.")

    # ─── Tab 4: Live Prices & Accuracy ──────────────────────────────────
    with tab4:
        st.markdown('<div class="section-header">Live Prices & Prediction Accuracy</div>',
                    unsafe_allow_html=True)

        acc_days = st.slider(
            "Look back (days)", min_value=7, max_value=90, value=30,
            key="acc_slider",
        )

        # Today's accuracy
        today_acc = load_todays_accuracy()
        if today_acc.empty:
            st.info("No accuracy data yet for today. Run `python price_tracker.py` to fetch live prices.")
        else:
            total = len(today_acc)
            correct = int(today_acc["Correct"].sum())
            accuracy = (correct / total * 100) if total > 0 else 0
            avg_change = today_acc["Change %"].mean()

            mc1, mc2, mc3, mc4 = st.columns(4)
            mc1.metric("Today's Accuracy", f"{accuracy:.0f}%", f"{correct}/{total} correct")
            mc2.metric("Avg Price Change", f"{avg_change:+.2f}%")
            mc3.metric("Picks That Rose", f"{correct}", f"of {total}")
            mc4.metric("Picks That Fell", f"{total - correct}", f"of {total}")

            st.markdown("<br>", unsafe_allow_html=True)

            st.markdown("**Today's Picks vs Actual Prices**")
            for _, row in today_acc.iterrows():
                rank = int(row["Rank"])
                ticker = row["Ticker"]
                sentiment = row["Sentiment"]
                momentum = row["Momentum"]
                open_p = row["Open"]
                current = row["Current"]
                change_pct = row["Change %"]
                correct_flag = row["Correct"]
                reason = row["Reason"] or "N/A"

                result_text = "CORRECT" if correct_flag else "WRONG"
                result_color = "#4ade80" if correct_flag else "#f87171"

                change_str = f"{change_pct:+.2f}%" if change_pct is not None else "N/A"
                open_str = f"{open_p:.2f}" if open_p is not None else "N/A"
                current_str = f"{current:.2f}" if current is not None else "N/A"

                if sentiment and sentiment > 0.3:
                    sent_class = "positive"
                elif sentiment and sentiment < -0.1:
                    sent_class = "negative"
                else:
                    sent_class = "neutral"

                st.markdown(f"""
                <div class="stock-card">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.75rem;">
                        <div>
                            <span class="rank-badge">#{rank}</span>
                            <span style="font-size:1.4rem; font-weight:800; color:#f1f5f9; margin-left:0.5rem;">{ticker}</span>
                        </div>
                        <div style="background:{result_color}20; color:{result_color}; padding:0.35rem 1rem; border-radius:20px; font-weight:700; font-size:0.9rem;">
                            {result_text}
                        </div>
                    </div>
                    <div class="stats-row">
                        <div class="stat">
                            <span class="stat-label">Sentiment</span>
                            <span class="stat-value {sent_class}">{sentiment:+.3f}</span>
                        </div>
                        <div class="stat">
                            <span class="stat-label">Momentum</span>
                            <span class="stat-value">{momentum:.3f}</span>
                        </div>
                        <div class="stat">
                            <span class="stat-label">Open</span>
                            <span class="stat-value">{open_str}</span>
                        </div>
                        <div class="stat">
                            <span class="stat-label">Current</span>
                            <span class="stat-value">{current_str}</span>
                        </div>
                        <div class="stat">
                            <span class="stat-label">Change</span>
                            <span class="stat-value {sent_class}">{change_str}</span>
                        </div>
                    </div>
                    <div class="reason-box">
                        <div class="reason-label">Reason</div>
                        <div class="reason-text">{reason}</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

        # Historical accuracy
        st.markdown("<br>", unsafe_allow_html=True)
        acc_summary = load_accuracy_summary(days=acc_days)
        if not acc_summary.empty:
            st.markdown(f"**Historical Accuracy - Last {acc_days} Days**")

            total_picks = acc_summary["Total Picks"].sum()
            total_correct = acc_summary["Correct"].sum()
            overall_accuracy = (total_correct / total_picks * 100) if total_picks > 0 else 0
            avg_daily_change = acc_summary["Avg Change %"].mean()

            sc1, sc2, sc3 = st.columns(3)
            sc1.metric("Overall Accuracy", f"{overall_accuracy:.1f}%", f"{total_correct}/{total_picks}")
            sc2.metric("Trading Days", f"{len(acc_summary)}")
            sc3.metric("Avg Daily Change", f"{avg_daily_change:+.2f}%")

            st.markdown("<br>", unsafe_allow_html=True)

            chart_df = acc_summary.set_index("Date")[["Correct", "Total Picks"]]
            st.bar_chart(chart_df, height=300)

            st.markdown("**Daily Breakdown**")
            for _, row in acc_summary.iterrows():
                date_str = row["Date"]
                total = int(row["Total Picks"])
                correct = int(row["Correct"])
                avg_chg = row["Avg Change %"]
                acc = (correct / total * 100) if total > 0 else 0
                acc_color = "#4ade80" if acc >= 60 else "#f59e0b" if acc >= 40 else "#f87171"

                chg_color = "#4ade80" if avg_chg and avg_chg > 0 else "#f87171" if avg_chg and avg_chg < 0 else "#94a3b8"
                st.markdown(f"""
                <div style="display:flex; justify-content:space-between; align-items:center; padding:0.75rem 1rem; margin-bottom:0.5rem; background:rgba(30,41,59,0.5); border-radius:8px; border-left:3px solid {acc_color};">
                    <div style="color:#e2e8f0; font-weight:600;">{date_str}</div>
                    <div style="display:flex; gap:2rem; align-items:center;">
                        <span style="color:#94a3b8; font-size:0.9rem;">{correct}/{total} correct</span>
                        <span style="color:{acc_color}; font-weight:700; font-size:1.1rem;">{acc:.0f}%</span>
                        <span style="color:{chg_color}; font-weight:600; font-size:0.9rem;">{avg_chg:+.2f}% avg</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No historical accuracy data yet. Run `python price_tracker.py` daily to build accuracy history.")

        # ─── Sentiment-Accuracy Correlation Analysis ─────────────────────
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div class="section-header">Sentiment vs Accuracy Analysis</div>',
                    unsafe_allow_html=True)

        sent_acc_df = load_sentiment_accuracy_data(days=acc_days)
        sent_buckets_df = load_sentiment_buckets(days=acc_days)

        if sent_acc_df.empty:
            st.info("Not enough data for sentiment-accuracy analysis. Run `python price_tracker.py` over multiple days.")
        else:
            # Overall correlation stats
            total_picks = len(sent_acc_df)
            overall_acc = sent_acc_df["Correct"].mean() * 100
            avg_sentiment = sent_acc_df["Sentiment"].mean()

            correlation = None
            if total_picks >= 3:
                correlation = sent_acc_df["Sentiment"].corr(sent_acc_df["Change %"])

            mc1, mc2, mc3, mc4 = st.columns(4)
            mc1.metric("Total Analyzed", f"{total_picks} picks")
            mc2.metric("Overall Accuracy", f"{overall_acc:.0f}%")
            mc3.metric("Avg Sentiment", f"{avg_sentiment:+.3f}")
            if correlation is not None:
                mc4.metric("Sentiment-Return Correlation", f"{correlation:+.3f}")
            else:
                mc4.metric("Correlation", "Need more data")

            st.markdown("<br>", unsafe_allow_html=True)

            # Sentiment buckets accuracy table
            st.markdown("**Accuracy by Sentiment Range**")
            st.markdown("*Which sentiment scores predict actual price increases?*")

            if not sent_buckets_df.empty:
                for _, bucket in sent_buckets_df.iterrows():
                    bucket_name = bucket["Sentiment Range"]
                    total = int(bucket["Total Picks"])
                    correct = int(bucket["Correct"])
                    avg_chg = bucket["Avg Change %"]
                    acc = (correct / total * 100) if total > 0 else 0

                    bar_color = "#4ade80" if acc >= 60 else "#f59e0b" if acc >= 40 else "#f87171"
                    chg_color = "#4ade80" if avg_chg and avg_chg > 0 else "#f87171" if avg_chg and avg_chg < 0 else "#94a3b8"

                    st.markdown(f"""
                    <div style="display:flex; justify-content:space-between; align-items:center; padding:0.75rem 1rem; margin-bottom:0.5rem; background:rgba(30,41,59,0.5); border-radius:8px; border-left:3px solid {bar_color};">
                        <div style="display:flex; gap:1.5rem; align-items:center; flex:1;">
                            <div style="min-width:100px;">
                                <span style="color:#60a5fa; font-weight:700; font-size:1.1rem;">{bucket_name}</span>
                            </div>
                            <div style="min-width:80px;">
                                <span style="color:#e2e8f0; font-weight:600;">{correct}/{total}</span>
                                <span style="color:#94a3b8; font-size:0.85rem;"> picks</span>
                            </div>
                            <div style="flex:1; height:8px; background:rgba(255,255,255,0.1); border-radius:4px; overflow:hidden;">
                                <div style="width:{acc}%; height:100%; background:{bar_color}; border-radius:4px;"></div>
                            </div>
                        </div>
                        <div style="display:flex; gap:2rem; align-items:center; margin-left:1rem;">
                            <span style="color:{bar_color}; font-weight:700; font-size:1.1rem; min-width:50px; text-align:right;">{acc:.0f}%</span>
                            <span style="color:{chg_color}; font-weight:600; min-width:80px; text-align:right;">avg {avg_chg:+.2f}%</span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

            # Sentiment vs Price Change scatter chart
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("**Sentiment Score vs Price Change**")
            st.markdown("*Each point is a stock pick. X-axis = sentiment score, Y-axis = actual price change %*")

            scatter_df = sent_acc_df[["Sentiment", "Change %", "Ticker"]].copy()
            scatter_df = scatter_df.sort_values("Sentiment")
            st.scatter_chart(scatter_df.set_index("Ticker")[["Sentiment", "Change %"]], height=350)

            # Individual picks table
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("**All Analyzed Picks**")

            display_df = sent_acc_df.copy()
            display_df["Result"] = display_df["Correct"].map({1: "CORRECT", 0: "WRONG"})
            display_df["Sentiment"] = display_df["Sentiment"].map(lambda x: f"{x:+.3f}")
            display_df["Change %"] = display_df["Change %"].map(lambda x: f"{x:+.2f}%")
            display_df["Momentum"] = display_df["Momentum"].map(lambda x: f"{x:.3f}")
            st.dataframe(
                display_df[["Ticker", "Sentiment", "Momentum", "Change %", "Result"]],
                use_container_width=True,
                hide_index=True,
            )


if __name__ == "__main__":
    main()
