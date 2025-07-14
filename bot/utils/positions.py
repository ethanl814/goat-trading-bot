import json, pathlib
from datetime import datetime

POS_FILE = pathlib.Path("state/open_positions.json")
POS_FILE.parent.mkdir(exist_ok=True)

def _convert(dt):  # helper for json default
    return dt.isoformat()

def load_open() -> list[dict]:
    if POS_FILE.exists():
        data = json.loads(POS_FILE.read_text())
        for d in data:
            d["entry_time"] = datetime.fromisoformat(d["entry_time"])
        return data
    return []

def save_open(open_pos: list[dict]):
    for d in open_pos:
        d["entry_time"] = d["entry_time"].isoformat()
    POS_FILE.write_text(json.dumps(open_pos, default=_convert, indent=2))

def add_position(pos):
    open_pos = load_open()
    open_pos.append(pos)
    save_open(open_pos)

def remove_position(symbol):
    open_pos = [p for p in load_open() if p["symbol"] != symbol]
    save_open(open_pos)
