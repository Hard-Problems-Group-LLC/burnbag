"""Parse human duration text without choosing calendar or elapsed-time semantics.

``parse_duration`` returns nonnegative Decimal totals keyed by canonical unit.
Callers decide how months and years relate to their time-range endpoints. The
parser has no clock, filesystem, locale, or optional-package dependencies.
"""

from __future__ import annotations

from decimal import Decimal, localcontext
import re
from typing import Dict, List


MAX_DURATION_LENGTH = 1024

_UNIT_NAMES = {
    "seconds": ("s", "sec", "secs", "second", "seconds"),
    "minutes": ("m", "min", "mins", "minute", "minutes"),
    "hours": ("h", "hr", "hrs", "hour", "hours"),
    "days": ("d", "day", "days"),
    "weeks": ("w", "wk", "wks", "week", "weeks"),
    "months": ("mo", "mos", "mon", "mons", "month", "months"),
    "years": ("y", "yr", "yrs", "year", "years"),
    "decades": ("dec", "decs", "decade", "decades"),
    "centuries": ("c", "cent", "cents", "century", "centuries"),
    "millennia": ("mil", "mils", "millennium", "millennia", "millenniums",
                  "millenium", "millenia", "milleniums"),
}
_UNITS = {alias: unit for unit, aliases in _UNIT_NAMES.items() for alias in aliases}
_SMALL = dict(zip(
    ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
     "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
     "sixteen", "seventeen", "eighteen", "nineteen"), range(20)))
_TENS = dict(zip(
    ("twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"),
    range(20, 100, 10)))
_SCALES = {
    "thousand": 10 ** 3, "million": 10 ** 6, "billion": 10 ** 9,
    "trillion": 10 ** 12, "quadrillion": 10 ** 15, "quintillion": 10 ** 18,
}
_NUMBER = re.compile(r"(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)\Z")
_TOKEN = re.compile(r"[0-9]+(?:\.[0-9]+)?|\.[0-9]+|[a-z]+|[-,]")
_CLOCK = re.compile(r"([0-9]+):([0-9]{1,2})(?::([0-9]{1,2}))?(\.[0-9]+)?\Z")


def _under_hundred(words: List[str]) -> int:
    if len(words) == 1 and words[0] in _SMALL:
        return _SMALL[words[0]]
    if words and words[0] in _TENS:
        if len(words) == 1:
            return _TENS[words[0]]
        if len(words) == 2 and 1 <= _SMALL.get(words[1], -1) <= 9:
            return _TENS[words[0]] + _SMALL[words[1]]
    raise ValueError("Invalid English quantity; use a number such as 'twenty-five' or '125'.")


def _under_thousand(words: List[str]) -> int:
    if len(words) >= 2 and words[1] == "hundred" and 1 <= _SMALL.get(words[0], -1) <= 9:
        value = _SMALL[words[0]] * 100
        tail = words[2:]
        if not tail:
            return value
        if tail[0] == "and":
            tail = tail[1:]
        remainder = _under_hundred(tail)
        if remainder == 0:
            raise ValueError("Invalid English quantity after 'hundred'; omit a zero remainder.")
        return value + remainder
    return _under_hundred(words)


def _english_integer(tokens: List[str]) -> int:
    """Accept descending scales and conventional hundreds/tens grammar."""
    words = []
    for index, token in enumerate(tokens):
        if token == "-":
            if (index == 0 or index + 1 == len(tokens) or tokens[index - 1] not in _TENS
                    or not 1 <= _SMALL.get(tokens[index + 1], -1) <= 9):
                raise ValueError("Hyphens in English quantities must join tens and ones, as in 'twenty-five'.")
        else:
            words.append(token)
    total, previous_scale, begin = 0, None, 0
    for index, word in enumerate(words):
        if word not in _SCALES:
            continue
        scale = _SCALES[word]
        if previous_scale is not None and scale >= previous_scale:
            raise ValueError("English number scales must descend, as in 'one million two thousand'.")
        amount = _under_thousand(words[begin:index])
        if amount == 0:
            raise ValueError("English number scales need a positive quantity before them.")
        total += amount * scale
        previous_scale, begin = scale, index + 1
    tail = words[begin:]
    if previous_scale is not None and not tail:
        return total
    if previous_scale is not None and tail and tail[0] == "and":
        tail = tail[1:]
    remainder = _under_thousand(tail)
    if previous_scale is not None and remainder == 0:
        raise ValueError("Invalid English quantity after a number scale; omit a zero remainder.")
    return total + remainder


def _clock_duration(text: str) -> Dict[str, Decimal]:
    match = _CLOCK.fullmatch(text)
    if not match:
        raise ValueError("Clock durations use MM:SS or HH:MM:SS, optionally with fractional seconds.")
    first, second, third, fraction = match.groups()
    if int(second) >= 60 or (third is not None and int(third) >= 60):
        raise ValueError("Clock duration minute and second fields after the first must be below 60.")
    if third is None:
        return {"minutes": Decimal(first), "seconds": Decimal(second + (fraction or ""))}
    return {"hours": Decimal(first), "minutes": Decimal(second),
            "seconds": Decimal(third + (fraction or ""))}


def parse_duration(text: str) -> Dict[str, Decimal]:
    """Return positive duration components or raise an actionable ``ValueError``.

    Units are case insensitive. Decimal digits, English integers, additive
    components, and MM:SS / HH:MM:SS are accepted. Quantities require units
    outside clock notation; signs, exponent notation, and non-finite values
    are rejected. ``m`` means minutes and ``mo`` means months. Zero components
    are omitted, and the complete duration must be positive. Input is bounded
    to 1024 characters; exact decimal values are preserved within that bound.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Duration must not be empty; try '5h', 'five hours', or '5:00:00'.")
    if len(text) > MAX_DURATION_LENGTH:
        raise ValueError(f"Duration is too long; use at most {MAX_DURATION_LENGTH} characters.")
    text = text.strip().lower()
    if ":" in text:
        result = _clock_duration(text)
    else:
        tokens = []
        end = 0
        for match in _TOKEN.finditer(text):
            if text[end:match.start()].strip():
                raise ValueError("Duration contains unsupported characters; use quantities and units, such as '1h 30m'.")
            tokens.append(match.group())
            end = match.end()
        if text[end:].strip():
            raise ValueError("Duration contains unsupported characters; use quantities and units, such as '1h 30m'.")
        result = {}
        position = 0
        # Addition must retain decimal digits even if a caller uses a smaller
        # process-wide Decimal context. Input length bounds arithmetic cost.
        with localcontext() as context:
            context.prec = MAX_DURATION_LENGTH * 2
            while position < len(tokens):
                begin = position
                while position < len(tokens) and tokens[position] not in _UNITS:
                    position += 1
                if position == len(tokens):
                    raise ValueError("Every duration quantity needs a unit; use seconds, minutes, hours, days, weeks, months, years, decades, centuries, or millennia.")
                quantity = tokens[begin:position]
                if not quantity:
                    raise ValueError("Each duration unit needs a quantity, as in 'five hours'.")
                if len(quantity) == 1 and _NUMBER.fullmatch(quantity[0]):
                    value = Decimal(quantity[0])
                else:
                    value = Decimal(_english_integer(quantity))
                unit = _UNITS[tokens[position]]
                result[unit] = result.get(unit, Decimal(0)) + value
                position += 1
                if position < len(tokens) and tokens[position] == ",":
                    position += 1
                if position < len(tokens) and tokens[position] == "and":
                    position += 1
                if position == len(tokens) and tokens[-1] in (",", "and"):
                    raise ValueError("Duration must end with a unit, not a separator.")
    result = {unit: amount for unit, amount in result.items() if amount != 0}
    if not result:
        raise ValueError("Duration must be greater than zero.")
    return result
