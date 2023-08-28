from rich.console import Console
from rich.table import Table


class OrderbookCollectionPrinter:
    def __init__(self):
        self._console = Console()
        self.num_snapshots = 0
        self.num_deltas = 0

    def run(self):
        self._console.clear()
        table = Table(title="Portfolio")
        table.add_row("Snapshot msgs", str(self.num_snapshots))
        table.add_row("Delta msgs", str(self.num_deltas))
        self._console.print(table)
