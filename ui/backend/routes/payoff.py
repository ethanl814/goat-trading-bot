# Compute payoff diagrams for combined derivative positions.
from fastapi import APIRouter

router = APIRouter()


@router.post("/compute")
def compute_payoff():
    raise NotImplementedError
