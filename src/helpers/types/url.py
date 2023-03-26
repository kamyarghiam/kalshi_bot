import urllib.parse


class URL(str):
    def join(self, other: "URL"):  # type:ignore[override]
        return URL(urllib.parse.urljoin(str(self + "/"), str(other)))
