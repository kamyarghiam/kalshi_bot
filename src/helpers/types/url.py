import urllib.parse


class URL(str):
    def add(self, other: "URL"):
        return URL(urllib.parse.urljoin(str(self + "/"), str(other)))
