# Submit live/paper orders via the connected broker.
from fastapi import APIRouter

router = APIRouter()


@router.get("/account")
def account():
    raise NotImplementedError


@router.post("/order")
def submit_order():
    raise NotImplementedError
