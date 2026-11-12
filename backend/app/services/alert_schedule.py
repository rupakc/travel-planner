"""Priority and adaptive intervals for the watch scheduler. Filled by Task 8."""

from datetime import date, timedelta


def priority(watch_kind: str, watch: dict, today: date) -> tuple:
    raise NotImplementedError


def next_interval(watch_kind: str, watch: dict, today: date) -> timedelta:
    raise NotImplementedError
