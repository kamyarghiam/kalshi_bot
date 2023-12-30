import math

from scipy.optimize import basinhopping, minimize_scalar
from scipy.stats import norm

from helpers.utils import Price


def compute_std(bound: float, mean: float, probability: float):
    """Computes the standard deviation on a normal distribution curve
    in which we have the probability is less than the bound with a given mean"""
    assert 0 < probability < 1
    assert bound < mean

    z_score = norm.ppf(probability)

    return (bound - mean) / z_score


def spy_market_std(
    spy_lower_bound: float,
    spy_upper_bound: float,
    current_spy_price: float,
    kalshi_market_price: Price,
):
    """Computes the implied standard deviation on a SPY market"""
    mean = (spy_upper_bound - spy_lower_bound) / 2
    probability = ((100 - kalshi_market_price) / 2) / 100
    return compute_std(spy_lower_bound, mean, probability)


def compute(mean, std, value):
    return norm(mean, std).pdf(value)


def use_scipy_to_solve_system():
    price = 0
    mean = 0.1
    curr_val = 0.1

    result = minimize_scalar(
        lambda std: abs(compute(mean, std, curr_val) - price), bounds=(0, 1)
    )
    closest_argument = result.x
    compute(mean, closest_argument, curr_val)


def binary_call_option_price(S, K, T, r, sigma, is_put=True):
    d2 = (math.log(S / K) + (r - 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    if is_put:
        d2 *= -1
    option_price = math.exp(-r * T) * norm.cdf(d2)
    return option_price


def double_no_touch_option_price(S: float, L: float, U: float, T: float, sigma: float):
    """S = Current stock value
    L = lower bound
    U = upper bound
    T = time left, should be between 0 and 2
    S = Volatility, as a percentage
    """
    assert L < U
    # assert 0 < sigma < 1
    if T == 0:
        # Set it to some super small value
        T = 0.00001
    # assert 0 < T and T <= 2
    # Risk free rate
    r = 0.05
    if S < ((L + U) / 2):
        d1 = (math.log(S / L) + (r - 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    else:
        d1 = (math.log(U / S) + (r - 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    option_price = math.exp(-r * T) * (norm.cdf(d1))
    return option_price


def compute_std_from_barrier_option(S: float, L: float, U: float, T: float, P: Price):
    """
    Given a price, computes the standard deviation
    for the given option as a percentage

    S = Current stock value
    L = lower bound
    U = upper bound
    T = time left, should be between 0 and 2
    P = price of the contract

    NOTE: there is a small risk here. There are often multiple
    solutions to a problem. You may have to constrain the range
    to get the right solution
    """
    result = basinhopping(
        lambda std: abs(double_no_touch_option_price(S, L, U, T, std) - P),
        0.05,
        stepsize=0.001,
        minimizer_kwargs={"bounds": [(0, None)]},
    )
    return result.x
