from src.exchange.interface import Id
from src.helpers.types.websockets.common import SubscriptionId


def test_increment_id():
    last_id = Id.LAST_ID
    sub_last_id = SubscriptionId.LAST_ID

    id = Id.get_new_id()
    assert id == Id(last_id + 1)

    sub_id = SubscriptionId.get_new_id()
    assert sub_id == SubscriptionId(sub_last_id + 1)

    id = Id.get_new_id()
    assert id == Id(last_id + 2)

    sub_id = SubscriptionId.get_new_id()
    assert sub_id == SubscriptionId(sub_last_id + 2)
