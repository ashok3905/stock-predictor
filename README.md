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
    pip install -r requirements.txt
    ```
    > **Note:** PyTorch (`torch`) is a large dependency. If you have GPU support, you can install a CUDA-optimized version:
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

## ⚠️ Disclaimer

This project is for educational and informational purposes only. **This is NOT financial advice.** Always do your own research before making any investment decisions. Trading in the stock market involves risk.

## 📝 License

MIT License
