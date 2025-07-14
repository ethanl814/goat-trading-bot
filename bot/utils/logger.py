import csv, pathlib, datetime as dt

LOG_PATH = pathlib.Path("logs"); LOG_PATH.mkdir(exist_ok=True)

def log_trade(filing, order):
    path = LOG_PATH / "trades.csv"
    is_new = not path.exists()
    with path.open("a", newline="") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["utc_time", "ticker", "form", "qty", "alpaca_id"])
        writer.writerow([
            dt.datetime.utcnow().isoformat(timespec="seconds"),
            filing["ticker"],
            filing["form"],
            order.qty,
            order.id,
        ])

def log_close(entry, exit_price, reason):
    path = LOG_PATH / "closed_trades.csv"
    is_new = not path.exists()
    with path.open("a", newline="") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["utc_exit", "symbol", "qty",
                             "entry_price", "exit_price", "pnl_dollars", "reason"])
        pnl = (exit_price - entry["entry_price"]) * entry["qty"]
        writer.writerow([
            dt.datetime.utcnow().isoformat(timespec="seconds"),
            entry["symbol"], entry["qty"],
            entry["entry_price"], exit_price, round(pnl, 2), reason
        ])
