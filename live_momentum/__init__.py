"""Live / paper trading system for the adopted intraday momentum configuration.

The research code in `crypto_intraday_momentum/` is the specification. This package
reuses its session and signal code unchanged and adds the parts a live system needs:
an event-driven maker_chase execution state machine, per-session sizing from data known
before the open, configuration, and (in later phases) exchange connectivity and risk limits.
"""
