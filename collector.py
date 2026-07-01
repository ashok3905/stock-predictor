"""
collector.py — News Collector for Intraday Trading App
Fetches stock market news every minute from multiple sources.
Extracts ticker symbols and stores articles in SQLite database.
"""

import os
import re
import time
import logging
import requests
import feedparser
import pandas as pd
import schedule
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# ─── Load environment variables ───────────────────────────────────────────────
load_dotenv()
NEWS_API_KEY = os.getenv("NEWS_API_KEY")

# ─── Logging setup ────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
os.makedirs("data", exist_ok=True)

logging.basicConfig(
    filename="logs/collector.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
console.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
logging.getLogger().addHandler(console)

# ─── Database setup ───────────────────────────────────────────────────────────
engine = create_engine(os.getenv("DATABASE_URL", "sqlite:///data/news.db"))

def create_table():
    """Create the news table if it doesn't exist."""
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS news (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT NOT NULL,
                description TEXT,
                url         TEXT UNIQUE,
                published_at TEXT,
                source      TEXT,
                tickers     TEXT,
                fetched_at  TEXT
            )
        """))
        conn.commit()
    logging.info("Database ready.")

# ─── Ticker extraction ────────────────────────────────────────────────────────
# Maps company keywords → NSE ticker symbols.
# Focused on Indian MIDCAP and SMALLCAP stocks, since these move far more
# (often 3-15% intraday) than large caps, which rarely cross 1% in a day.
# A short list of large caps is kept at low priority for context only.
TICKER_MAP = {
    # ── Midcap (Nifty Midcap 100 / 150 universe) ──────────────────────────
    "suzlon":            "SUZLON",
    "yes bank":          "YESBANK",
    "yesbank":           "YESBANK",
    "idfc first":        "IDFCFIRSTB",
    "punjab national":   "PNB",
    "pnb":               "PNB",
    "bank of baroda":    "BANKBARODA",
    "bankbaroda":        "BANKBARODA",
    "canara bank":       "CANBK",
    "union bank":        "UNIONBANK",
    "indian overseas":   "IOB",
    "irctc":             "IRCTC",
    "ireda":             "IREDA",
    "rvnl":              "RVNL",
    "rail vikas":        "RVNL",
    "irfc":              "IRFC",
    "hudco":             "HUDCO",
    "nbcc":              "NBCC",
    "nhpc":              "NHPC",
    "sjvn":              "SJVN",
    "gail":              "GAIL",
    "indian oil":        "IOC",
    "hpcl":              "HINDPETRO",
    "bpcl":              "BPCL",
    "mrpl":              "MRPL",
    "gmr airports":      "GMRAIRPORT",
    "gmr":               "GMRAIRPORT",
    "adani power":       "ADANIPOWER",
    "adani green":       "ADANIGREEN",
    "adani energy":      "ADANIENSOL",
    "adani total gas":   "ATGL",
    "adani wilmar":      "AWL",
    "jindal steel":      "JINDALSTEL",
    "nmdc":              "NMDC",
    "steel authority":   "SAIL",
    "vedanta":           "VEDL",
    "national aluminium":"NATIONALUM",
    "nalco":             "NATIONALUM",
    "hindustan zinc":    "HINDZINC",
    "rec limited":       "RECLTD",
    "pfc":               "PFC",
    "power finance":     "PFC",
    "zomato":            "ZOMATO",
    "eternal":           "ETERNAL",
    "paytm":             "PAYTM",
    "nykaa":             "NYKAA",
    "policybazaar":      "PBFINTECH",
    "pb fintech":        "PBFINTECH",
    "delhivery":         "DELHIVERY",
    "indigo airlines":   "INDIGO",
    "interglobe aviation":"INDIGO",
    "spicejet":          "SPICEJET",
    "vodafone idea":     "IDEA",
    "tata power":        "TATAPOWER",
    "tata chemicals":    "TATACHEM",
    "tata communications":"TATACOMM",
    "tata elxsi":        "TATAELXSI",
    "trent ltd":         "TRENT",
    "voltas":            "VOLTAS",
    "havells":           "HAVELLS",
    "dixon":             "DIXON",
    "polycab":           "POLYCAB",
    "page industries":   "PAGEIND",
    "muthoot finance":   "MUTHOOTFIN",
    "manappuram":        "MANAPPURAM",
    "chola finance":     "CHOLAFIN",
    "cholamandalam":     "CHOLAFIN",
    "lic housing":       "LICHSGFIN",
    "piramal":           "PEL",
    "godrej properties": "GODREJPROP",
    "dlf":               "DLF",
    "oberoi realty":     "OBEROIRLTY",
    "prestige estates":  "PRESTIGE",
    "macrotech":         "LODHA",
    "lodha":             "LODHA",
    "phoenix mills":     "PHOENIXLTD",
    "indus towers":      "INDUSTOWER",
    "biocon":            "BIOCON",
    "lupin":             "LUPIN",
    "aurobindo":         "AUROPHARMA",
    "alkem":             "ALKEM",
    "torrent pharma":    "TORNTPHARM",
    "torrent power":     "TORNTPOWER",
    "mankind pharma":    "MANKIND",
    "glenmark":          "GLENMARK",
    "laurus labs":       "LAURUSLABS",
    "sona blw":          "SONACOMS",
    "motherson":         "MOTHERSON",
    "bharat forge":      "BHARATFORG",
    "bosch":             "BOSCHLTD",
    "exide":             "EXIDEIND",
    "amara raja":        "ARE&M",
    "balkrishna":        "BALKRISIND",
    "mrf":               "MRF",
    "apollo tyres":      "APOLLOTYRE",
    "ceat":              "CEATLTD",
    "ashok leyland":     "ASHOKLEY",
    "escorts":           "ESCORTS",
    "tvs motor":         "TVSMOTOR",
    "bajaj auto":        "BAJAJ-AUTO",
    "abb india":         "ABB",
    "siemens":           "SIEMENS",
    "cummins":           "CUMMINSIND",
    "thermax":           "THERMAX",
    "bhel":              "BHEL",
    "bharat electronics":"BEL",
    "hal":               "HAL",
    "hindustan aeronautics":"HAL",
    "mazagon dock":      "MAZDOCK",
    "cochin shipyard":   "COCHINSHIP",
    "garden reach":      "GRSE",
    "bharat dynamics":   "BDL",
    "solar industries":  "SOLARINDS",
    "astral":            "ASTRAL",
    "supreme industries":"SUPREMEIND",
    "pidilite":          "PIDILITIND",
    "berger paints":     "BERGEPAINT",
    "godrej consumer":   "GODREJCP",
    "dabur":             "DABUR",
    "marico":            "MARICO",
    "united spirits":    "MCDOWELL-N",
    "united breweries":  "UBL",
    "varun beverages":   "VBL",
    "jubilant foodworks":"JUBLFOOD",
    "devyani":           "DEVYANI",
    "westlife":          "WESTLIFE",
    # ── Smallcap / high-volatility momentum names ─────────────────────────
    "ideaforge":         "IDEAFORGE",
    "ola electric":      "OLAELEC",
    "railtel":           "RAILTEL",
    "rites":             "RITES",
    "engineers india":   "ENGINERSIN",
    "rcf":               "RCF",
    "gnfc":              "GNFC",
    "deepak nitrite":    "DEEPAKNTR",
    "alkyl amines":      "ALKYLAMINE",
    "navin fluorine":    "NAVINFLUOR",
    "tata teleservices": "TTML",
    "route mobile":      "ROUTE",
    "tanla":             "TANLA",
    "happiest minds":    "HAPPSTMNDS",
    "mastek":            "MASTEK",
    "cyient":            "CYIENT",
    "kpit":              "KPITTECH",
    "persistent":        "PERSISTENT",
    "coforge":           "COFORGE",
    "zensar":            "ZENSARTECH",
    "central bank":      "CENTRALBK",
    "indian bank":       "INDIANB",
    "uco bank":          "UCOBANK",
    "bank of india":     "BANKINDIA",
    "bank of maharashtra":"MAHABANK",
    "south indian bank": "SOUTHBANK",
    "rbl bank":          "RBLBANK",
    "ujjivan":           "UJJIVANSFB",
    "equitas":           "EQUITASBNK",
    "suryoday":          "SURYODAY",
    "aavas financiers":  "AAVAS",
    "aptus":             "APTUS",
    "home first":        "HOMEFIRST",
    "spandana":          "SPANDANA",
    "reliance power":    "RPOWER",
    "reliance infra":    "RELINFRA",
    "ircon":             "IRCON",
    "transformers and rectifiers":"TARIL",
    "hbl power":         "HBLPOWER",
    "apar industries":   "APARINDS",
    "kei industries":    "KEI",
    "rajesh exports":    "RAJESHEXPO",
    "vakrangee":         "VAKRANGEE",
    "yatra":             "YATRA",
    "easemytrip":        "EASEMYTRIP",
    "ixigo":             "IXIGO",
    "swiggy":            "SWIGGY",
    "honasa":            "HONASA",
    "mamaearth":         "HONASA",
    "go digit":          "GODIGIT",
    "star health":       "STARHEALTH",
    "niva bupa":         "NIVABUPA",
    "premier energies":  "PREMIERENE",
    "waaree":            "WAAREEENER",
    "websol":            "WEBELSOLAR",
    "kpi green":         "KPIGREEN",
    "borosil renewables":"BORORENEW",
    "inox wind":         "INOXWIND",
    "jupiter wagons":    "JWL",
    "titagarh":          "TITAGARH",
    "texmaco rail":      "TEXRAIL",
    "ramkrishna forgings":"RKFORGE",
    "jbm auto":          "JBMA",
    "olectra greentech": "OLECTRA",
    "force motors":      "FORCEMOT",
    "sml isuzu":         "SMLISUZU",
    "vst tillers":       "VSTTILLERS",
    "action construction":"ACE",
    "elecon engineering":"ELECON",
    "triveni engineering":"TRIVENI",
    "kirloskar":         "KIRLOSENG",
    "thejo engineering": "THEJO",
    "shaily engineering":"SHAILY",
    "data patterns":     "DATAPATTNS",
    "azad engineering":  "AZAD",
    "syrma sgs":         "SYRMA",
    "kaynes":            "KAYNES",
    "amber enterprises": "AMBER",
    "pg electroplast":   "PGEL",
    "centum electronics":"CENTUM",
    "schneider":         "SCHNEIDER",
    "kalyan jewellers":  "KALYANKJIL",
    "kalyan":            "KALYANKJIL",
    "titan company":     "TITAN",
    "rainbow childrens": "RAINBOW",
    "jk cement":         "JKCEMENT",
    "jk tyre":           "JKTYRE",
    "blue star":         "BLUESTARCO",
    "whirlpool":         "WHIRLPOOL",
    "crompton":          "CROMPTON",
    "v-guard":           "VGUARD",
    "kajaria":           "KAJARIACER",
    "century plyboards": "CENTURYPLY",
    "greenpanel":        "GREENPANEL",
    "praj industries":   "PRAJIND",
    "ion exchange":      "IONEXCHANG",
    "gujarat gas":       "GUJGASLTD",
    "gujarat state petronet":"GSPL",
    "indraprastha gas":  "IGL",
    "mahanagar gas":     "MGL",
    "petronet lng":      "PETRONET",
    "lemon tree":        "LEMONTREE",
    "chalet hotels":     "CHALET",
    "indian hotels":     "INDHOTEL",
    "mahindra holidays": "MHRIL",
    "redington":         "REDINGTON",
    "info edge":         "NAUKRI",
    "naukri":            "NAUKRI",
    "just dial":         "JUSTDIAL",
    "affle india":       "AFFLE",
    "affle":             "AFFLE",
    "newgen software":   "NEWGEN",
    "intellect design":  "INTELLECT",
    "sonata software":   "SONATSOFTW",
    "birlasoft":         "BSOFT",
    "rategain":          "RATEGAIN",
    "latent view":       "LATENTVIEW",
    "tips industries":   "TIPSMUSIC",
    "saregama":          "SAREGAMA",
    "pvr inox":          "PVRINOX",
    "nazara technologies":"NAZARA",
    "nazara":            "NAZARA",
    "delta corp":        "DELTACORP",
    "sapphire foods":    "SAPPHIRE",
    "barbeque nation":   "BARBEQUE",
    "cera sanitaryware": "CERA",
    "sheela foam":       "SFL",
    "relaxo footwear":   "RELAXO",
    "bata india":        "BATAINDIA",
    "metro brands":      "METROBRAND",
    "campus activewear": "CAMPUS",
    "vip industries":    "VIPIND",
    "safari industries": "SAFARI",
    "gravita india":     "GRAVITA",
    "kfin technologies": "KFINTECH",
    "cams":              "CAMS",
    "cdsl":              "CDSL",
    "bse limited":       "BSE",
    "multi commodity":   "MCX",
    "angel one":         "ANGELONE",
    "motilal oswal":     "MOTILALOFS",
    "iifl finance":      "IIFL",
    "5paisa":            "5PAISA",
    "geojit":            "GEOJITFSL",
    "ujjivan small finance":"UJJIVANSFB",
    "fino payments":     "FINOPB",
    "cams services":     "CAMS",
    "pine labs":         "PINELABS",
    "anant raj":         "ANANTRAJ",
    "motilal oswal financial": "MOFSL",
    "mofsl":             "MOFSL",
    "larsen":            "LT",
    "l&t":               "LT",
    "beml":              "BEML",
    "reliance industries limited": "RELIANCE",
    "ril":               "RELIANCE",
    "pcbl":              "PCBL",
    "lancor":            "LANCORHOL",
    "sattrix":           "SATTRIX",
    "hfcl":              "HFCL",
    "itc hotels":        "ITCHOTELS",
    "om power transmission": "OMPOWER",
    "kims":              "KIMS",
    "general insurance corporation": "GICRE",
    "gic re":            "GICRE",
    "hdb financial":     "HDBFS",
    "tejas networks":    "TEJASNET",
    "ghv infra":         "GHV",
    "john cockerill":    "JOHNCOCKERILL",
    "samhi hotels":      "SAMHI",
    "urban company":     "URBANCO",
    "physicswallah":     "PHYSICSWALLAH",
    "hdfc amc":          "HDFCAMC",
    "jio financial":     "JIOFIN",
    "lg electronics":    "LGEIL",
    "bse shares":        "BSE",
    "orkla india":       "ORKLAINDIA",
    "m&m":               "M&M",
    "mahindra & mahindra":"M&M",
    "icici pru":         "ICICIPRULI",
    "icici prudential":  "ICICIPRULI",
    "global health":     "MEDANTA",
    "groww":             "GROWW",
    "shriram finance":   "SHRIRAMFIN",
    "fractal analytics": "FRACTAL",
    "nlc india":         "NLCINDIA",
    "ola electric":      "OLAELEC",
    "alkem labs":        "ALKEM",
    "itc hotels limited":"ITCHOTELS",
    "tata steel":        "TATASTEEL",
    "power grid":        "POWERGRID",
    "rajesh exports":    "RAJESHEXPO",
    "hero motocorp":     "HEROMOTOCO",
    "waaree renewable":  "WAAREEENER",
    "rail vikas nigam":  "RVNL",
    "premier energies":  "PREMIERENE",
    "bank of maharashtra":"MAHABANK",
    "vedanta aluminium": "VEDL",
    "avience biomedicals":"AVIENCE",
    "trident ltd":       "TRIDENT",
    "trident limited":   "TRIDENT",
    "jsw energy":        "JSWENERGY",
    "awfis space":       "AWFIS",
    "awfis":             "AWFIS",
    "hitachi energy":    "HITACHIENERGY",
    # ── A handful of large caps kept for context only (low priority) ──────
    "reliance industries":"RELIANCE",
    "tata consultancy": "TCS",
    "hdfc bank":         "HDFCBANK",
    "icici bank":        "ICICIBANK",
    "infosys":           "INFY",
}

# Large caps are deprioritized, never excluded — used by predictor.py later
LARGE_CAP_TICKERS = {"RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY"}

# Tickers that are also common English words — only matched when written in
# ALL CAPS in the original headline (e.g. "SAIL shares jump"), never via
# lowercase substring/word search, to avoid false positives like "ships sail"
# or "this is a fact".
AMBIGUOUS_WORD_TICKERS = {"SAIL", "FACT", "INDIGO", "TRENT", "PRESTIGE", "TRIDENT"}

def extract_tickers(title, description):
    """Extract stock ticker symbols from news text, sorted with mid/small caps first.

    Uses word-boundary regex matching (not plain substring search) to avoid
    false positives like 'sail' matching inside 'ships sail', 'fact' matching
    inside 'this is a fact', 'hal' matching inside 'halt', etc.
    """
    combined = f"{title or ''} {description or ''}".lower()
    original = f"{title or ''} {description or ''}"
    found = set()

    # Match company keywords as whole words/phrases only (word-boundary safe)
    for keyword in sorted(TICKER_MAP.keys(), key=len, reverse=True):
        pattern = r'\b' + re.escape(keyword) + r'\b'
        if re.search(pattern, combined):
            found.add(TICKER_MAP[keyword])

    # Ambiguous-word tickers (SAIL, FACT, GAIL, MRF, DLF) are only accepted
    # if they appear in ALL CAPS in the original text — this is how financial
    # news actually writes stock tickers, so it's a safe, high-precision signal.
    for ticker in AMBIGUOUS_WORD_TICKERS:
        pattern = r'\b' + re.escape(ticker) + r'\b'
        if re.search(pattern, original):
            found.add(ticker)

    if not found:
        return "GENERAL"

    # Put mid/small caps first, large caps last — predictor.py can use this order
    # as a simple priority signal, or just split on the large-cap set directly.
    midsmall = sorted(t for t in found if t not in LARGE_CAP_TICKERS)
    large    = sorted(t for t in found if t in LARGE_CAP_TICKERS)
    return ",".join(midsmall + large)

# ─── News sources ─────────────────────────────────────────────────────────────
# Source 1: NewsAPI (requires API key)
def fetch_from_newsapi():
    """Fetch articles from NewsAPI.org."""
    if not NEWS_API_KEY:
        logging.warning("NEWS_API_KEY not set. Skipping NewsAPI.")
        return []

    url = "https://newsapi.org/v2/everything"
    queries = [
        '"upper circuit" stock NSE',
        "smallcap stock surge india",
        "stock order win contract india",
        "brokerage buy call target price india",
        "stock multibagger india",
    ]
    all_articles = []

    for q in queries:
        try:
            params = {
                "q":        q,
                "language": "en",
                "sortBy":   "publishedAt",
                "pageSize": 20,
                "apiKey":   NEWS_API_KEY,
            }
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            articles = resp.json().get("articles", [])
            all_articles.extend(articles)
            logging.info(f"NewsAPI [{q}]: {len(articles)} articles")
        except Exception as e:
            logging.error(f"NewsAPI error for query '{q}': {e}")

    return all_articles

# Source 2: Google News RSS (free, no key needed) — India, midcap/smallcap focus
# NOTE: avoid generic "stock market" / "NSE BSE" queries — they mostly return
# index-level Sensex/Nifty wrap-up articles with no single stock to extract.
# These queries are phrased to surface individual stock-movement headlines instead.
RSS_FEEDS = [
    ("Google News - Midcap Smallcap Stocks",
     "https://news.google.com/rss/search?q=midcap+smallcap+stocks+india&hl=en-IN&gl=IN&ceid=IN:en"),
    ("Google News - Upper Circuit Stocks",
     "https://news.google.com/rss/search?q=%22upper+circuit%22+share+nse&hl=en-IN&gl=IN&ceid=IN:en"),
    ("Google News - Stocks to Watch",
     "https://news.google.com/rss/search?q=stocks+to+watch+today+india&hl=en-IN&gl=IN&ceid=IN:en"),
    ("Google News - Shares Jump Surge",
     "https://news.google.com/rss/search?q=shares+jump+surge+india+nse&hl=en-IN&gl=IN&ceid=IN:en"),
    ("Google News - Stock Breakout",
     "https://news.google.com/rss/search?q=stock+breakout+buy+target+nse&hl=en-IN&gl=IN&ceid=IN:en"),
    ("Google News - Smallcap Multibagger",
     "https://news.google.com/rss/search?q=smallcap+multibagger+stock+india&hl=en-IN&gl=IN&ceid=IN:en"),
    ("Google News - Stock Specific Order Win",
     "https://news.google.com/rss/search?q=stock+order+win+contract+india&hl=en-IN&gl=IN&ceid=IN:en"),
    ("Google News - Brokerage Buy Call",
     "https://news.google.com/rss/search?q=brokerage+buy+call+stock+target+price&hl=en-IN&gl=IN&ceid=IN:en"),
]

def fetch_from_rss():
    """Fetch articles from Google News RSS feeds."""
    all_articles = []
    for name, url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            articles = []
            for entry in feed.entries:
                articles.append({
                    "title":       entry.get("title", ""),
                    "description": entry.get("summary", ""),
                    "url":         entry.get("link", ""),
                    "publishedAt": entry.get("published", datetime.now().isoformat()),
                    "source":      {"name": name},
                })
            all_articles.extend(articles)
            logging.info(f"RSS [{name}]: {len(articles)} articles")
        except Exception as e:
            logging.error(f"RSS error [{name}]: {e}")
    return all_articles

# ─── Deduplication ────────────────────────────────────────────────────────────
def get_existing_urls():
    """Return set of URLs already stored in the database."""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT url FROM news"))
            return {row[0] for row in result.fetchall()}
    except Exception:
        return set()

# ─── Store articles ───────────────────────────────────────────────────────────
def save_articles(raw_articles):
    """Clean, deduplicate and save articles to the database."""
    if not raw_articles:
        logging.info("No articles to save.")
        return 0

    existing_urls = get_existing_urls()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    records = []

    for a in raw_articles:
        title       = (a.get("title") or "").strip()
        description = (a.get("description") or "").strip()
        url         = (a.get("url") or "").strip()
        published   = (a.get("publishedAt") or now).strip()
        source      = (a.get("source") or {}).get("name", "Unknown")

        # Skip if missing key fields or already stored
        if not title or not url:
            continue
        if url in existing_urls:
            continue

        tickers = extract_tickers(title, description)

        records.append({
            "title":        title,
            "description":  description,
            "url":          url,
            "published_at": published,
            "source":       source,
            "tickers":      tickers,
            "fetched_at":   now,
        })
        existing_urls.add(url)  # prevent duplicates within the same batch

    if not records:
        logging.info("All articles already stored. No new records.")
        return 0

    df = pd.DataFrame(records)
    df.to_sql("news", engine, if_exists="append", index=False)
    logging.info(f"Saved {len(records)} new articles to database.")
    return len(records)

# ─── Main collection job ──────────────────────────────────────────────────────
def collect_news():
    """Main job: fetch from all sources and save to database."""
    logging.info("=" * 50)
    logging.info("Starting news collection cycle...")

    # Fetch from all sources
    newsapi_articles = fetch_from_newsapi()
    rss_articles     = fetch_from_rss()
    all_articles     = newsapi_articles + rss_articles

    logging.info(f"Total fetched: {len(all_articles)} articles (before dedup)")

    # Save to DB
    saved = save_articles(all_articles)
    logging.info(f"Collection cycle complete. {saved} new articles saved.")
    logging.info("=" * 50)

# ─── Database stats ───────────────────────────────────────────────────────────
def print_stats():
    """Print current database stats to console."""
    try:
        with engine.connect() as conn:
            total = conn.execute(text("SELECT COUNT(*) FROM news")).fetchone()[0]
            recent = conn.execute(text("""
                SELECT title, tickers, fetched_at FROM news
                ORDER BY id DESC LIMIT 5
            """)).fetchall()

        print(f"\n{'='*60}")
        print(f"  DATABASE STATS — Total articles stored: {total}")
        print(f"{'='*60}")
        print("  Latest 5 articles:")
        for row in recent:
            print(f"  [{row[1]:20s}] {row[0][:55]}")
        print(f"{'='*60}\n")
    except Exception as e:
        print(f"Stats error: {e}")

# ─── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.info("Initializing news collector...")

    # Setup DB
    create_table()

    # Run immediately on start
    collect_news()
    print_stats()

    # Schedule to run every minute
    schedule.every(1).minutes.do(collect_news)
    schedule.every(5).minutes.do(print_stats)

    logging.info("Scheduler started. Collecting news every minute...")
    logging.info("Press Ctrl+C to stop.\n")

    while True:
        try:
            schedule.run_pending()
            time.sleep(1)
        except KeyboardInterrupt:
            logging.info("Collector stopped by user.")
            print("\nCollector stopped.")
            break
        except Exception as e:
            logging.error(f"Unexpected error in scheduler: {e}")
            time.sleep(5)