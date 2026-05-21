"""Live adapter implementations.

Concrete clients behind the protocols in `adapters/base.py`. Constructed
by `adapters._build_real_adapters()`. Each adapter comes online
independently; the factory wires up whatever is ready and raises a clear
error for the ones that aren't.
"""
