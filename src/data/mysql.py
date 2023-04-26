import os
from time import sleep
from types import TracebackType

from mysql.connector import MySQLConnection, connect
from mysql.connector.cursor import MySQLCursor


class MySqlInterface:
    def __init__(self):
        command = "brew services start mysql"
        os.system(command)
        sleep(1)
        self._connection: MySQLConnection = connect(
            user="orderbook",
            password="orderbook123@",
            host="localhost",
        )
        self._cursor: MySQLCursor = self._connection.cursor()

    def fetch(self, command: str):
        self._cursor.execute(command)
        return self._cursor.fetchall()

    def __enter__(self) -> "MySqlInterface":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ):
        self._cursor.close()
        self._connection.close()
        command = "brew services stop mysql"
        os.system(command)
