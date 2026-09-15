# Historical duration ranges

Status: implemented; phase `1000`, local slices `1000`–`4000`.

`burnbag --graph --last DURATION` renders history from the selected duration
ago through the current time captured once for the invocation. This is a
read-only query with the same graph, summary, source merging and bounded
collector flush behavior as explicit historical bounds. See
[continuous history](continuous-history.md) for those contracts.

`--last` requires `--graph` and cannot be combined with either `--from` or
`--to`. Omitting all three range options continues to select the last 24
hours. `--no-plot` retains the summary for the selected interval.

## Accepted forms

Each of the following selects five hours:

```bash
burnbag --graph --last 5h
burnbag --graph --last 5H
burnbag --graph --last "5 h"
burnbag --graph --last "5 H"
burnbag --graph --last "5 hours"
burnbag --graph --last "five hours"
burnbag --graph --last 5:00:00
burnbag --graph --last 05:00:00
```

Quote any duration containing spaces so that the shell passes it as one
argument. Unit names, aliases and English number words are case-insensitive.
Numeric quantities may contain decimal fractions, such as `1.5h`, `.5h` or
`0.25 seconds`; exponent notation and fractions such as `1/2h` are not
accepted. English quantities use integers, such as `five hours`,
`twenty-one minutes`, `one hundred and five seconds` or
`one thousand two hundred days`. English number scales from thousand through
quintillion must descend and each needs a positive leading quantity.
Compounds add their components: `1h30m` and `one hour and thirty minutes`
both select 90 minutes. Whitespace, commas and `and` can separate complete
components. Zero components are allowed within a positive total.

Two colon-separated fields mean **minutes:seconds**, so `5:00` selects five
minutes. Three fields mean **hours:minutes:seconds**. Leading zeroes are
allowed. The first field is an unbounded nonnegative integer; subsequent
fields have one or two integer digits and must be less than 60. The final
seconds field may also have a decimal fraction. No internal spaces or unit
suffixes are accepted in clock notation.

## Units

Full singular and plural names are accepted for seconds, minutes, hours,
days, weeks, months, years, decades, centuries and millennia. `millenia` is
accepted as a spelling variant. `m` means minutes; `mo` means months.

| Unit | Additional accepted aliases | Arithmetic |
| --- | --- | --- |
| Second | `s`, `sec`, `secs` | One elapsed second |
| Minute | `m`, `min`, `mins` | 60 elapsed seconds |
| Hour | `h`, `hr`, `hrs` | 60 elapsed minutes |
| Day | `d` | 24 elapsed hours |
| Week | `w`, `wk`, `wks` | Seven elapsed days |
| Month | `mo`, `mos`, `mon`, `mons` | One calendar month |
| Year | `y`, `yr`, `yrs` | 12 calendar months |
| Decade | `dec`, `decs` | 120 calendar months |
| Century | `c`, `cent`, `cents` | 1,200 calendar months |
| Millennium | `mil`, `mils`, `millenniums`, `millenium`, `millenia`, `milleniums` | 12,000 calendar months |

## Calendar arithmetic

Months and larger units use calendar subtraction in the host's local
timezone. Add every calendar component into a total number of months. That
total must be an integer: `1.5 years` is valid and selects 18 calendar
months; `1.5 months` is invalid. Then subtract those months once from the
captured end, preserving the time of day and clamping an unavailable date
to the target month's final day. For example:

- One month before March 31 is February 28, or February 29 in a leap year.
- One year before February 29, 2024 is February 28, 2023.
- Two months before March 31 is January 31; there is no intermediate
  February clamp.

After calendar subtraction, subtract seconds through weeks as elapsed time.
Component order in the input does not affect this arithmetic. In particular,
a day means 24 elapsed hours even across daylight-saving transitions, while
a calendar month preserves the local time of day.

If the calendar target is an ambiguous or nonexistent local time at a
daylight-saving transition, reject it with an actionable diagnostic. The
operator can select the intended interval with explicit `--from` and `--to`
offsets; the parser must not guess an offset or silently move the local time.

## Validation and limits

The total duration must be positive, finite and large enough to produce a
distinct start at the supported clock resolution. Duration input is limited
to 1,024 characters. Reject empty strings, bare
quantities without units, signed quantities, unsupported words, unconsumed
text, malformed colon fields, fractional total calendar months and invalid
calendar targets with a concise usage error and exit status 2. Invalid input
does not begin an operational session or create a history
database. Service availability warnings retain their usual top and bottom
placement even when duration validation fails.

Accepting centuries and millennia does not promise unlimited calendar range.
If subtracting an otherwise valid duration would exceed the supported
calendar years 1 through 9999, reject it explicitly instead of clipping,
wrapping, or displaying a traceback. A long valid range with no stored
observations remains an ordinary empty historical result.
