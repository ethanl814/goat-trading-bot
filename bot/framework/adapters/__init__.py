# bot/framework/adapters/
"""Asset-class adapters. Each translates one market's quirks into the core's
normalized vocabulary and declares its instruments' constraints via
`InstrumentSpec`. Adding an asset class = one adapter here; nothing in the core
changes. `equities_alpaca` is fully wired; `prediction_market` is a stub that
proves the seam (probability prices + Resolution events)."""
