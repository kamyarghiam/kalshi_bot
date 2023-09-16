import pytest
from mock import MagicMock, call, patch

from data.collection.orderbook import retry_collect_orderbook_data
from exchange.interface import ExchangeInterface


def test_retry_collect_orderbook_data():
    mock_exchange_interface = MagicMock(spec=ExchangeInterface)

    with patch(
        "data.collection.orderbook.collect_orderbook_data"
    ) as mock_collect_orderbook_data:
        error = ValueError("error from collect_orderbook_data")
        mock_collect_orderbook_data.side_effect = error
        with patch("data.collection.orderbook.sleep") as mock_sleep:
            with patch(
                "data.collection.orderbook.send_alert_email"
            ) as mock_send_alert_email:
                # This is a hack to force the while loop to stop
                mock_sleep.side_effect = [
                    True,
                    ValueError("Error to make while loop stop"),
                ]
                with pytest.raises(ValueError) as e:
                    retry_collect_orderbook_data(mock_exchange_interface)
                assert e.match("Error to make while loop stop")
                mock_collect_orderbook_data.assert_has_calls(
                    [call(mock_exchange_interface), call(mock_exchange_interface)]
                )
                # Email only sent once the first round
                mock_send_alert_email.assert_called_once_with(
                    f"Received error: {str(error)}. Re-running collect orderbook algo"
                )
                # But we went through two sleep iterations
                mock_sleep.assert_has_calls([call(10), call(10)])
