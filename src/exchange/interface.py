from src.exchange.connection import Connection


class ExchangeInterface:
    def __init__(self, connection: Connection):
        """This class provides a high level interace with the exchange"""
        self._connection = connection
