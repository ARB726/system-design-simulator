"""Closed-form M/M/c queueing results, used to validate the simulation engine."""
from __future__ import annotations


def erlang_c(c: int, a: float) -> float:
    """Probability an arriving request has to wait, for c servers and offered load a = lambda/mu."""
    if a >= c:
        return 1.0
    term, partial = 1.0, 1.0           # k = 0 term of sum_{k<c} a^k / k!
    for k in range(1, c):
        term *= a / k
        partial += term
    last = term * a / c                # a^c / c!
    top = last * c / (c - a)
    return top / (partial + top)


def mmc_mean_wait(lam: float, mu: float, c: int) -> float:
    """Mean time spent waiting in the queue (seconds)."""
    if lam >= c * mu:
        return float("inf")
    return erlang_c(c, lam / mu) / (c * mu - lam)


def mmc_mean_response(lam: float, mu: float, c: int) -> float:
    """Mean time in system = wait + service (seconds)."""
    return mmc_mean_wait(lam, mu, c) + 1.0 / mu
