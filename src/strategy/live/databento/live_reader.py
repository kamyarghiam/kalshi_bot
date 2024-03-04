from typing import Generator

import databento as db

from exchange.connection import Auth
from helpers.types.money import Cents


class Databento:
    """Live databento client for SPY"""

    def __init__(self, is_test_run: bool = True):
        self._auth = Auth(is_test_run)
        self._client = db.Live(key=self._auth.databento_api_key)
        self._client.subscribe(
            dataset="DBEQ.BASIC",
            schema="MBP-1",
            stype_in="raw_symbol",
            symbols="SPY",
        )

    def stream_data(self) -> Generator[Cents, None, None]:
        """Gives the next price"""
        for msg in self._client:
            if isinstance(msg, db.SymbolMappingMsg):
                continue
            elif isinstance(msg, db.MBP1Msg):
                price = round((msg.price / 1e7))
                yield Cents(price)
            else:
                raise ValueError("Unknown databento message: ", msg)
