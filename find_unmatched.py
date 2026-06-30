"""
find_unmatched.py — Pulls 'Stocks to Watch' style roundup headlines and other
GENERAL-tagged articles that mention multiple company names, so we can spot
which tickers are still missing from TICKER_MAP.
"""

from sqlalchemy import create_engine, text

engine = create_engine("sqlite:///data/news.db")

with engine.connect() as conn:
    # Roundup-style headlines often start with "Stocks to Watch" or similar
    # and are likely to contain multiple company names we haven't mapped yet.
    roundups = conn.execute(text("""
        SELECT title FROM news
        WHERE title LIKE '%Stocks to Watch%'
           OR title LIKE '%stocks in focus%'
           OR title LIKE '%shares in focus%'
        ORDER BY id DESC
        LIMIT 20
    """)).fetchall()

    print("=" * 70)
    print("ROUNDUP HEADLINES (likely contain multiple unmapped tickers)")
    print("=" * 70)
    for r in roundups:
        print(r[0])

    print()
    print("=" * 70)
    print("OTHER GENERAL-TAGGED HEADLINES (sample)")
    print("=" * 70)
    general = conn.execute(text("""
        SELECT title FROM news
        WHERE tickers = 'GENERAL'
        ORDER BY id DESC
        LIMIT 40
    """)).fetchall()
    for r in general:
        print(r[0])
