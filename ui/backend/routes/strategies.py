# List, enable, disable strategies across categories.
from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def list_strategies():
    raise NotImplementedError
