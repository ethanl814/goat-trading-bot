# bot/main.py
import time, hashlib, datetime as dt
from bot.brokers.alpaca import AlpacaBroker
from bot.data.edgar_feed import latest_filings
from bot.strategies.insider_simple import decide_trade
from bot.utils.logger import log_trade, log_close
from bot.utils.state import load_seen, save_seen
from bot.utils.positions import load_open, add_position, remove_position
from bot.risk.exit import should_exit

# ---------------- startup ----------------------------------------------------
broker = AlpacaBroker(paper=True)
print("Account equity:", broker.account_info().equity)

seen = load_seen()
print(f"Loaded {len(seen)} previously-seen filings")

print("Bot started — polling every 3 min")
# ---------------------------------------------------------------------------

while True:
    try:
        # ---------- 1. Check for new filings & open entries  ----------
        for filing in latest_filings():
            fid = hashlib.sha1(filing["link"].encode()).hexdigest()
            if fid in seen:
                continue
            seen.add(fid); save_seen(seen)

            order = decide_trade(filing, broker)
            if order:
                try:
                    resp = broker.submit_buy_market(order["symbol"], order["qty"])
                    log_trade(filing, resp)
                    add_position({
                        "symbol": order["symbol"],
                        "qty": order["qty"],
                        "entry_price": order["entry_price"],
                        "entry_time": dt.datetime.utcnow()
                    })
                    print(f"BUY {order['symbol']} {order['qty']} @ {order['entry_price']}")
                except Exception as e:
                    print("order failed:", e)

        # ---------- 2. Check exits for every open position  ----------
        for pos in load_open():
            cur_price = broker.current_price(pos["symbol"])
            reason = should_exit(pos["entry_price"], cur_price, pos["entry_time"])
            if reason:
                try:
                    broker.submit_sell_market(pos["symbol"], pos["qty"])
                    log_close(pos, cur_price, reason)
                    remove_position(pos["symbol"])
                    print(f"EXIT {pos['symbol']} via {reason} @ {cur_price}")
                except Exception as e:
                    print("exit failed:", e)

        # ---------- 3. Sleep until next cycle  ----------
        print("Polling cycle complete — sleeping")
        time.sleep(180)       # 3-minute poll

    except KeyboardInterrupt:
        print("Manual stop — goodbye")
        break
    except Exception as e:
        print("loop error:", e)
        time.sleep(60)
