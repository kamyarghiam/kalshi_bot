"""
The goal of this model is to take in orderbook information from
a market and to output a prediction of how much the price will
fluctuate and  and in how many minutes that price movement will occur:

Input:
    Market orderbook
Output:
    Price movement (Cents between -98 to 98)
    Time until movement (Milliseconds 1 - inf)

________________________________________________
Implementation

For the event orderbooks, we want to capture interactions
between different layers. This is why choose to use a neural
network. Since this is a time series, we decided to use a
recurrent neural network, and because we want to remember
info from further than one time step, we decided to use an LSTM.

The market orderbook information is inputted as follow:
1. We capture volumes as percentages between 0 and 1
2. We need time information to represent the time until expiration in
the market.

In the future, we can train a model with multiple markets in a single event

Input vector looks like:

- Time until expiration
- Yes price 1 volume percentage
- Yes price 2 volume percentage
...
- Yes price 99 volume percentage
- No price 1 volume percentage
- No price 2 volume percentage
...
- No price 99 volume percentage

Example: [20000, 0.15, 0.2, 0.1 ...]

The size of the vector is always 1 + 99 + 99 = 199
"""


import datetime

import numpy as np

from helpers.types.orderbook import Orderbook


def orderbook_to_input_vector(ob: Orderbook):
    """Converts orderbook info into an input vector for model

    Assumes expiration time is always 4 pm of the day of the orderbook"""
    # See description at beginning of file why below is 199
    # Consists of: Time until expiration, 1 - 99 volumes Yes, 1 - 99 Volumes No
    seconds_until_expiration = get_seconds_until_4pm(ob.ts)
    input_vector = np.zeros(199)
    input_vector[0] = seconds_until_expiration
    total_quantity_yes = ob.yes.get_total_quantity()
    for price, quantity in ob.yes.levels.items():
        input_vector[price] = (quantity) / total_quantity_yes

    total_quantity_no = ob.no.get_total_quantity()
    for price, quantity in ob.no.levels.items():
        input_vector[99 + price] = (quantity) / total_quantity_no

    for value in input_vector:
        assert value != 0

    return input_vector


def get_seconds_until_4pm(ts: datetime.datetime):
    """Gets you seconds left until 4 pm same day of ob"""
    target_time = ts.replace(hour=16, minute=0, second=0, microsecond=0)
    time_difference = target_time - ts

    # Get the total seconds left until 4 PM
    return time_difference.total_seconds()
