# FastAPI entrypoint for the trading UI backend.
# Run: uvicorn ui.backend.app:app --reload
from fastapi import FastAPI

from ui.backend.routes import backtest, payoff, strategies, trades

app = FastAPI(title="goat-trading-bot UI")

app.include_router(strategies.router, prefix="/strategies", tags=["strategies"])
app.include_router(backtest.router, prefix="/backtest", tags=["backtest"])
app.include_router(payoff.router, prefix="/payoff", tags=["payoff"])
app.include_router(trades.router, prefix="/trades", tags=["trades"])


@app.get("/health")
def health():
    return {"ok": True}
