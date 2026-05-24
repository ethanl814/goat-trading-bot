# Run backtests on one or more strategies against historical data.
from fastapi import APIRouter

router = APIRouter()


@router.post("/run")
def run_backtest():
    raise NotImplementedError
