# bot/utils/state.py
import json, pathlib
STATE_FILE = pathlib.Path("state/seen.json")
STATE_FILE.parent.mkdir(exist_ok=True)

def load_seen() -> set[str]:
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text()))
    return set()

def save_seen(seen: set[str]):
    STATE_FILE.write_text(json.dumps(list(seen)))
