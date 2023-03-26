from src.helpers.types.url import URL


def test_urls():
    a = URL("hi")
    b = URL("bye")

    assert a.join(b) == URL("hi/bye")
