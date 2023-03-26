from src.exchange.connection import Connection


class Portfolio:
    """This class contains the portfolio balance of the account"""

    def __init__(self, connection: Connection):
        self._connection = connection
