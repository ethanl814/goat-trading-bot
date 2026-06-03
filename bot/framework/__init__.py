# bot/framework/
"""Event-driven, multi-asset signal-evaluation framework.

This is the new core (asyncio) that supersedes the thread/queue prototype in
`bot/core`. It is mode-agnostic: the *same* engine, signals, allocator, risk
monitor, and SimBroker run in both live-paper and backtest modes — only the
data `Source` swaps. Asset-class quirks live behind `adapters/`, never in the
core. See `docs/framework-design.md` for the design rationale.
"""
