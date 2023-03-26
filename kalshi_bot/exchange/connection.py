from kalshi_bot.exchange.auth import Auth


class Connection:
    """The purpose of this class is to establish a connection to the
    exhcange and provide low level control over our connection"""

    def __init__(self, auth: Auth):
        self.auth = auth
        # TODO: connect here, refresh cookies, and rate limit
