import argparse
import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def backup_db(db_path: str, data_dir: Path) -> Path:
    """Copy db_path to a timestamped file in data_dir using VACUUM INTO.

    VACUUM INTO writes a consistent snapshot of the live database without
    locking it for the duration of a file copy. Safe to run mid-backfill.
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = data_dir / f"metals_{ts}.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(f"VACUUM INTO '{dest}'")
    finally:
        conn.close()
    return dest


def export_csv(db_path: str, data_dir: Path) -> tuple[Path, Path]:
    """Export metal_prices and fx_rates to timestamped CSV files in data_dir."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    prices_path = data_dir / f"metal_prices_{ts}.csv"
    fx_path = data_dir / f"fx_rates_{ts}.csv"

    conn = sqlite3.connect(db_path)
    try:
        with prices_path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["date", "metal", "price_usd"])
            writer.writerows(conn.execute("SELECT date, metal, price_usd FROM metal_prices ORDER BY date, metal"))

        with fx_path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["date", "currency", "rate_to_usd"])
            writer.writerows(conn.execute("SELECT date, currency, rate_to_usd FROM fx_rates ORDER BY date, currency"))
    finally:
        conn.close()

    return prices_path, fx_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Back up the MetallicTrends SQLite database")
    parser.add_argument("--db", default="metals.db", help="SQLite database file (default: metals.db)")
    parser.add_argument("--data-dir", default="data", help="Output directory (default: data/)")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    data_dir.mkdir(exist_ok=True)

    db_dest = backup_db(args.db, data_dir)
    prices_path, fx_path = export_csv(args.db, data_dir)

    print(f"Database backup : {db_dest}")
    print(f"Metal prices CSV: {prices_path}")
    print(f"FX rates CSV    : {fx_path}")


if __name__ == "__main__":
    main()
