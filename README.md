# 📈 Stock Predictor — Intraday Trading App

An AI-powered intraday trading assistant that analyzes real-time news sentiment to predict the top 5 stocks most likely to rise during the trading day.

## 🧠 How It Works

1.  **News Collection**: Aggregates stock market news from NewsAPI and Google News RSS feeds.
2.  **Ticker Extraction**: Automatically identifies mentioned Indian NSE tickers (focused on high-volatility Midcap/Smallcap stocks).
3.  **Sentiment Analysis**: Uses **FinBERT** (ProsusAI/finbert) to score each article's sentiment.
4.  **Prediction**: Selects the top 5 stocks based on a momentum score (sentiment strength × article volume).
5.  **Accuracy Tracking**: Compares predictions against live NSE prices to measure historical performance.
6.  **Notification**: Sends daily picks via Email and Telegram before market open.

## ✨ Features

*   **AI Sentiment Engine**: FinBERT for high-precision financial news analysis.
*   **Real-time Tracking**: Monitors live prices and updates accuracy throughout the day.
*   **Interactive Dashboard**: Streamlit UI to explore predictions, sentiment trends, and historical accuracy.
*   **Dual Notifications**: Get picks via Email and Telegram.
*   **Backtesting**: Analyze past performance with the built-in backtester.
*   **Database**: SQLite storage for all news, sentiment, and prediction data.

## 🛠️ Prerequisites

*   Python 3.10+
*   NewsAPI Key (optional, but recommended)
*   Gmail App Password (for email notifications)
*   Telegram Bot Token (for Telegram notifications)

## 🚀 Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/ashok3905/stock-predictor.git
    cd stock-predictor
    ```

2.  **Install dependencies:**
    ```bash
    # Full install (all scripts including sentiment analysis with PyTorch)
    pip install -r requirements-worker.txt

    # Dashboard-only install (Streamlit Cloud uses this automatically)
    # pip install -r requirements.txt
    ```
    > **Note:** `requirements.txt` is trimmed for Streamlit Cloud (no torch/transformers).
    > `requirements-worker.txt` includes everything needed for local development and Heroku workers.
    > PyTorch (`torch`) is a large dependency (~2GB). If you have GPU support:
    > ```bash
    > pip install torch --index-url https://download.pytorch.org/whl/cu118
    > ```

3.  **Configure environment variables:**
    ```bash
    cp .env.example .env
    ```
    Edit `.env` with your API keys.

## ⚙️ Configuration

Create a `.env` file in the root directory:

```ini
# News Collection
NEWS_API_KEY=your_newsapi_key

# Email Notifications (Gmail)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
EMAIL_USER=your_email@gmail.com
EMAIL_PASS=your_2fa_app_password
EMAIL_TO=recipient@email.com

# Telegram Notifications
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

## 🏃 Usage

### 1. Start News Collection
Collects news every minute.
```bash
python collector.py
```

### 2. Run Sentiment Analysis
Scores unscored articles and updates ticker sentiment.
```bash
python sentiment.py
```

### 3. Generate Predictions
Selects top 5 stocks for the day.
```bash
python predictor.py
```

### 4. Track Prices & Accuracy
Fetches live prices during market hours (9:15 AM - 3:30 PM IST).
```bash
python price_tracker.py --schedule
```

### 5. Send Notifications
```bash
# Email
python notifier.py

# Telegram
python telegram_notifier.py
```

### 6. Launch Dashboard
```bash
streamlit run app.py
```

## 📊 Dashboard Preview

The Streamlit dashboard provides:
*   **Today's Picks**: Top 5 predicted stocks with reasons.
*   **Historical Predictions**: Browse past picks and their performance.
*   **Sentiment Explorer**: Deep dive into individual stock sentiment trends.
*   **Live Prices & Accuracy**: Real-time tracking and overall accuracy metrics.

## ☁️ Cloud Deployment (Heroku)

This app can be deployed to the cloud so it runs 24/7 without your PC.

### Quick Deploy Steps

1. **Push to GitHub:**
   ```bash
   git add .
   git commit -m "Prepare for deployment"
   git push origin master
   ```

2. **Create Heroku App:**
   ```bash
   heroku create your-app-name
   ```

3. **Add PostgreSQL Database:**
   ```bash
   heroku addons:create heroku-postgresql:essential-0
   ```

4. **Configure Environment Variables:**
   ```bash
   heroku config:set NEWS_API_KEY=your_key
   heroku config:set EMAIL_USER=your_email@gmail.com
   heroku config:set EMAIL_PASS=your_app_password
   heroku config:set EMAIL_TO=recipient@email.com
   heroku config:set TELEGRAM_BOT_TOKEN=your_token
   heroku config:set TELEGRAM_CHAT_ID=your_chat_id
   ```

5. **Install full dependencies on Heroku** (needed for torch/transformers in sentiment analysis):
   ```bash
   # Create a post_compile hook so Heroku installs worker deps after the build
   mkdir -p bin
   echo '#!/usr/bin/env bash\n\npip install -r requirements-worker.txt\n' > bin/post_compile
   chmod +x bin/post_compile
   ```

6. **Deploy:**
   ```bash
   git add bin/post_compile
   git commit -m "Add post_compile hook for Heroku worker deps"
   git push heroku master
   ```
   > **Note:** `requirements.txt` is trimmed for Streamlit Cloud (no torch/transformers).
   > The `bin/post_compile` hook ensures Heroku installs the full `requirements-worker.txt` during build.

6. **Set Up Background Jobs (Heroku Scheduler):**
   ```bash
   heroku addons:create scheduler:standard
   heroku open
   ```
   In the Scheduler dashboard, add these jobs:
   - `python collector.py` — Run every 10 minutes (collects news)
   - `python sentiment.py` — Run every 10 minutes (scores articles)
   - `python predictor.py` — Run daily at 8:30 AM IST (generates picks)
   - `python telegram_notifier.py` — Run daily at 8:30 AM IST (sends alerts)
   - `python price_tracker.py` — Run every 5 minutes during market hours

7. **View Logs:**
   ```bash
   heroku logs --tail
   ```

### Streamlit Cloud (Dashboard Only)

Host the dashboard for free on Streamlit Community Cloud:

1. **Push to GitHub:**
   ```bash
   git add .
   git commit -m "Deploy dashboard to Streamlit Cloud"
   git push origin master
   ```

2. **Go to [share.streamlit.io](https://share.streamlit.io)** and sign in with your GitHub account.

3. **Click "New app"** and configure:
   - **Repository:** Your GitHub repo (e.g., `ashok3905/stock-predictor`)
   - **Branch:** `master`
   - **Main file path:** `app.py`

4. **Click "Advanced settings"** and paste your secrets in the **Secrets** box:
   ```toml
   DATABASE_URL = "postgresql://user:password@host:5432/dbname"
   NEWS_API_KEY = "your_newsapi_key"
   ```
   > The dashboard uses `os.getenv()` which picks up Streamlit Cloud secrets as environment variables.
   > For the dashboard, `DATABASE_URL` is the only critical secret (point it to your PostgreSQL instance).

5. **Click "Deploy"** — your app will be live at a public URL.

> **Note:** `requirements.txt` is trimmed for fast Streamlit Cloud builds (no torch/transformers).
> Background workers (collector, sentiment, predictor) run separately on Heroku with `requirements-worker.txt`.

### PostgreSQL Migration Notes

- The app auto-detects PostgreSQL via the `DATABASE_URL` environment variable
- Falls back to SQLite for local development
- All tables auto-create on first run

## ⚠️ Disclaimer

This project is for educational and informational purposes only. **This is NOT financial advice.** Always do your own research before making any investment decisions. Trading in the stock market involves risk.

## 📝 License

MIT License
