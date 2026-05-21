"""AssetAdapter abstract base class.

Every venue/asset-class adapter implements this interface. The
ingestion service depends only on the abstract class, so swapping
or adding adapters does not require changes to the consumers.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from packages.core.models import QuoteL1Event, TradeEvent


class AssetAdapter(ABC):
    """Abstract base for venue/asset-class adapters.

    Adapters translate between canonical platform identifiers and
    venue-native ones, and they expose the venue's live data streams
    in canonical form.

    Subclasses must set `venue` as a class attribute matching the
    venue identifier used in canonical symbols.
    """

    venue: str

    @abstractmethod
    def to_native_symbol(self, canonical_symbol: str) -> str:
        """Translate a canonical symbol to its venue-native form.

        Example: 'BTC-USDT@BINANCEUS' -> 'BTCUSDT'.
        """

    @abstractmethod
    def to_canonical_symbol(self, native_symbol: str) -> str:
        """Translate a venue-native symbol to its canonical form.

        Example: 'BTCUSDT' -> 'BTC-USDT@BINANCEUS'.

        For venues where a pair-and-quote split is ambiguous, the
        adapter should maintain an internal table of known instruments.
        """

    @abstractmethod
    async def stream_trades(
        self,
        canonical_symbols: list[str],
    ) -> AsyncIterator[TradeEvent]:
        """Yield TradeEvent objects from the venue's live trade feed.

        Should reconnect on disconnect with exponential backoff. Should
        never raise out of the iterator under normal network failure;
        only unrecoverable errors (auth failure, etc.) should propagate.
        """

    @abstractmethod
    async def stream_quotes_l1(
        self,
        canonical_symbols: list[str],
    ) -> AsyncIterator[QuoteL1Event]:
        """Yield QuoteL1Event objects from the venue's top-of-book feed.

        Same reconnect semantics as stream_trades.
        """
