"""
Not-yet-built adapter stubs.

These construct cleanly (so `get_adapters()` returns a complete container)
but raise a clear, actionable error if any method is actually called. They
get replaced by real implementations in their respective PRs:

  PolymarketReal  → PR 3
  HyperliquidReal → PR 5
  GatewayReal     → PR 4
  USYCReal        → PR 4
"""
from __future__ import annotations


class _NotBuiltAdapter:
    """Any attribute access that looks like a method raises with guidance."""

    _adapter_name = "adapter"
    _pr = "a later PR"

    def __getattr__(self, item: str):
        if item.startswith("_"):
            raise AttributeError(item)

        async def _raise(*args, **kwargs):
            raise NotImplementedError(
                f"{self._adapter_name}.{item}() is not implemented yet "
                f"(lands in {self._pr}). See docs/LIVE_IMPLEMENTATION_PLAN.md."
            )

        return _raise


class PolymarketNotBuilt(_NotBuiltAdapter):
    _adapter_name = "PolymarketReal"
    _pr = "PR 3 (Polymarket V2 live path)"


class HyperliquidNotBuilt(_NotBuiltAdapter):
    _adapter_name = "HyperliquidReal"
    _pr = "PR 5 (Hedge loop)"


class GatewayNotBuilt(_NotBuiltAdapter):
    _adapter_name = "GatewayReal"
    _pr = "PR 4 (Circle treasury path)"


class USYCNotBuilt(_NotBuiltAdapter):
    _adapter_name = "USYCReal"
    _pr = "PR 4 (Circle treasury path)"
