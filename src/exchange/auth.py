class Auth:
    """The purpose of this class is to store authentication
    information to connect to the exchange"""

    def __init__(self, username: str, password: str):
        self._username = username
        self._password = password
