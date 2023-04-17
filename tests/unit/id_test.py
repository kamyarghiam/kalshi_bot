from src.helpers.types.websockets.common import CommandId, SubscriptionId


def test_increment_id():
    last_id = CommandId.LAST_ID
    sub_last_id = SubscriptionId.LAST_ID

    id = CommandId.get_new_id()
    assert id == CommandId(last_id + 1)

    sub_id = SubscriptionId.get_new_id()
    assert sub_id == SubscriptionId(sub_last_id + 1)

    id = CommandId.get_new_id()
    assert id == CommandId(last_id + 2)

    sub_id = SubscriptionId.get_new_id()
    assert sub_id == SubscriptionId(sub_last_id + 2)
