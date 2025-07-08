# bot/data/edgar_feed.py
import feedparser
import re
from datetime import datetime
from typing import Iterator, Dict
import requests, os
from dotenv import load_dotenv

load_dotenv()
UA = os.getenv("SEC_USER_AGENT")

FORM_RE = re.compile(r"Form\s+(4|13D|13G)", re.I)
TICKER_RE = re.compile(r"\((?P<ticker>[A-Z]{1,5})\)")

FEED_URL = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=&count=100&output=atom"

def latest_filings() -> Iterator[Dict]:
    headers = {"User-Agent": UA or "GoatTradingBot/0.1"}
    raw = requests.get(FEED_URL, headers=headers, timeout=10)
    raw.raise_for_status()
    feed = feedparser.parse(raw.content)

    for entry in feed.entries:
        if not FORM_RE.search(entry.title):
            continue
        ticker_match = TICKER_RE.search(entry.title)
        if not ticker_match:
            continue  # no ticker symbol → skip
        yield {
            "form": FORM_RE.search(entry.title).group(1).upper(),
            "ticker": ticker_match.group("ticker"),
            "title": entry.title,
            "link": entry.link,
            "filed_at": datetime(*entry.updated_parsed[:6]),
        }
