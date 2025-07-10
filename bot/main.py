# bot/main.py
import time, hashlib
from bot.brokers.alpaca import AlpacaBroker
from bot.data.edgar_feed import latest_filings
from bot.strategies.insider_simple import decide_trade
from bot.utils.logger import log_trade
from bot.utils.state import load_seen, save_seen

broker = AlpacaBroker(paper=True)
print("Account equity:", broker.account_info().equity)

seen = load_seen()
print(f"Loaded {len(seen)} previously-seen filings")

while True:
    try:
        for filing in latest_filings():
            fid = hashlib.sha1(filing["link"].encode()).hexdigest()
            if fid in seen:
                continue
            seen.add(fid)
            save_seen(seen)

            order_params = decide_trade(filing, broker)
            if order_params:
                print("Signal:", filing["title"])
                try:
                    o = broker.submit_buy_market(order_params["symbol"],
                                                 order_params["qty"])
                    log_trade(filing, o)
                    print("   ↳ bought", order_params["symbol"])
                except Exception as e:
                    print("   ↳ order failed:", e)
        print("Polling cycle complete — sleeping")
        time.sleep(180)   # 3-minute poll
    except KeyboardInterrupt:
        break
    except Exception as e:
        print("loop error:", e)
        time.sleep(60)
