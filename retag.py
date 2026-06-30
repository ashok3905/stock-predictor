"""
retag.py — One-time utility to re-tag existing articles in news.db
using the latest (fixed) ticker extraction logic from collector.py.
Run this once after updating collector.py to refresh old rows.
"""

from collector import extract_tickers
from sqlalchemy import create_engine, text

engine = create_engine("sqlite:///data/news.db")

with engine.connect() as conn:
    rows = conn.execute(text("SELECT id, title, description FROM news")).fetchall()
    updated = 0
    changed = 0
    for row_id, title, desc in rows:
        new_tickers = extract_tickers(title, desc)
        old_tickers = conn.execute(
            text("SELECT tickers FROM news WHERE id=:i"), {"i": row_id}
        ).fetchone()[0]
        if new_tickers != old_tickers:
            changed += 1
        conn.execute(
            text("UPDATE news SET tickers=:t WHERE id=:i"),
            {"t": new_tickers, "i": row_id}
        )
        updated += 1
    conn.commit()

print(f"Re-tagged {updated} articles total. {changed} tags changed.")

# Show the Pine Labs row specifically to confirm the fix
with engine.connect() as conn:
    result = conn.execute(
        text("SELECT title, tickers FROM news WHERE title LIKE '%Pine Labs%'")
    ).fetchall()
    print("\nPine Labs check:")
    for r in result:
        print(f"  [{r[1]}] {r[0]}")
