# bot/framework/recorder.py
"""Recorder: append fills, the equity curve, and decisions to disk.

CSV (stdlib `csv`, no pandas in the hot path — pandas is for the analysis step
only). Files land in `logs/` alongside the legacy bot's logs, namespaced by a
run id so live and backtest runs don't clobber each other. The equity curve is
the artifact the analysis script turns into PnL / Sharpe / max-drawdown / turnover.
"""
from __future__ import annotations

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path

from bot.framework.broker import Fill

log = logging.getLogger(__name__)


class Recorder:
    def __init__(self, run_id: str | None = None, outdir: str = "logs"):
        self.run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        self.dir = Path(outdir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.equity_path = self.dir / f"equity_{self.run_id}.csv"
        self.fills_path = self.dir / f"fills_{self.run_id}.csv"
        self._equity_f = self.equity_path.open("w", newline="")
        self._fills_f = self.fills_path.open("w", newline="")
        self._equity_w = csv.writer(self._equity_f)
        self._fills_w = csv.writer(self._fills_f)
        self._equity_w.writerow(["ts", "equity", "cash", "gross", "net", "realized", "unrealized"])
        self._fills_w.writerow(["ts", "instrument", "qty", "price", "fee", "realized"])
        log.info("recording run %s -> %s", self.run_id, self.dir)

    def record_fill(self, fill: Fill) -> None:
        self._fills_w.writerow([fill.ts.isoformat(), fill.instrument, fill.qty,
                                fill.price, fill.fee, fill.realized])
        self._fills_f.flush()

    def record_equity(self, ts: datetime, equity: float, cash: float,
                      gross: float, net: float, realized: float, unrealized: float) -> None:
        self._equity_w.writerow([ts.isoformat(), equity, cash, gross, net, realized, unrealized])
        self._equity_f.flush()

    def close(self) -> None:
        self._equity_f.close()
        self._fills_f.close()
