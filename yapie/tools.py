"""Plain helpers: periods and dates as people type them in chat."""
import re
from datetime import date, timedelta

MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MONTHS.update({"sept": 9, "january": 1, "february": 2, "march": 3, "april": 4, "june": 6, "july": 7, "august": 8,
               "september": 9, "october": 10, "november": 11, "december": 12})
FILLER = {"from", "to", "till", "until", "upto", "between", "and", "for", "of", "the", "in", "on", "as", "at", "please",
          "pdf", "excel", "xlsx", "xls", "sheet", "report", "send", "me", "give", "show", "-", "–", "~"}

PERIODS = [
    ("today", "Today"), ("yesterday", "Yesterday"), ("this_week", "This week"), ("last_week", "Last week"),
    ("this_month", "This month (to date)"), ("last_month", "Last month"), ("this_quarter", "This quarter"),
    ("last_quarter", "Last quarter"), ("this_year", "This year (to date)"), ("last_year", "Last year"),
    ("as_of_today", "As of today"),
]


def month_end(y, m):
    return (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))


def period_range(key, today, fy_start=None):
    """(from, to) for a named period. fy_start: first day of the current fiscal year, if known."""
    if key == "today":
        return today, today
    if key == "yesterday":
        d = today - timedelta(days=1)
        return d, d
    if key == "this_week":
        return today - timedelta(days=today.weekday()), today
    if key == "last_week":
        s = today - timedelta(days=today.weekday() + 7)
        return s, s + timedelta(days=6)
    if key == "this_month":
        return today.replace(day=1), today
    if key == "last_month":
        e = today.replace(day=1) - timedelta(days=1)
        return e.replace(day=1), e
    if key in ("this_quarter", "last_quarter"):
        q0 = (today.month - 1) // 3 * 3 + 1
        s = date(today.year, q0, 1)
        if key == "this_quarter":
            return s, today
        e = s - timedelta(days=1)
        return date(e.year, (e.month - 1) // 3 * 3 + 1, 1), e
    if key == "this_year":
        return (fy_start or date(today.year, 1, 1)), today
    if key == "last_year":
        if fy_start:
            s = fy_start.replace(year=fy_start.year - 1)
            return s, fy_start - timedelta(days=1)
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    return None, today  # as_of_today


_WORD_PERIODS = [
    ("this month", "this_month"), ("last month", "last_month"), ("previous month", "last_month"),
    ("this week", "this_week"), ("last week", "last_week"), ("this quarter", "this_quarter"),
    ("last quarter", "last_quarter"), ("this year", "this_year"), ("last year", "last_year"),
    ("ytd", "this_year"), ("mtd", "this_month"), ("yesterday", "yesterday"), ("today", "today"),
]
_D = r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})"
_ISO = r"(\d{4})-(\d{1,2})-(\d{1,2})"
_TXT = r"(\d{1,2})\s*(?:st|nd|rd|th)?\s+([a-z]{3,9})\.?(?:,?\s+(\d{4}))?"
_MON = r"\b([a-z]{3,9})\.?\s+(\d{4})\b"


def _year(y):
    y = int(y)
    return y + 2000 if y < 100 else y


def parse_period(text, today, fy_start=None):
    """Find dates/periods in `text`. Returns (date_from, date_to, period_key, rest_of_text).
    date_from/date_to are None when nothing was given."""
    t = " " + text.lower() + " "
    for words, key in _WORD_PERIODS:
        if re.search(r"\b" + re.escape(words) + r"\b", t):
            f, e = period_range(key, today, fy_start)
            return f, e, key, re.sub(r"\b" + re.escape(words) + r"\b", " ", t)
    found = []  # (position, date, is_whole_month_end)

    def take(m, d, month=False):
        found.append((m.start(), d, month))
        return " " * (m.end() - m.start())

    def iso(m):
        try:
            return take(m, date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            return m.group(0)

    def dmy(m):
        try:
            return take(m, date(_year(m.group(3)), int(m.group(2)), int(m.group(1))))
        except ValueError:
            return m.group(0)

    def txt(m):
        mon = MONTHS.get(m.group(2)[:3] if m.group(2)[:3] in MONTHS else m.group(2))
        if not mon:
            return m.group(0)
        try:
            return take(m, date(int(m.group(3)) if m.group(3) else today.year, mon, int(m.group(1))))
        except ValueError:
            return m.group(0)

    def mon(m):
        mo = MONTHS.get(m.group(1)) or MONTHS.get(m.group(1)[:3])
        if not mo:
            return m.group(0)
        y = int(m.group(2))
        found.append((m.start(), date(y, mo, 1), True))
        return " " * (m.end() - m.start())

    t = re.sub(_ISO, iso, t)
    t = re.sub(_D, dmy, t)
    t = re.sub(_TXT, txt, t)
    t = re.sub(_MON, mon, t)
    found.sort()
    if not found:
        # a bare year: "sales 2026" (to date, if it's this year)
        y = re.search(r"\b(19[89]\d|20\d\d)\b", t)
        if y:
            yr = int(y.group(1))
            return date(yr, 1, 1), min(date(yr, 12, 31), today) if yr == today.year else date(yr, 12, 31), None, t[:y.start()] + " " + t[y.end():]
        return None, None, None, t
    if len(found) == 1:
        _, d, whole = found[0]
        if whole:
            return d, min(month_end(d.year, d.month), today) if d <= today else month_end(d.year, d.month), None, t
        if re.search(r"\b(to|till|until|upto|as of|as at)\s*$", text.lower()[:max(0, found[0][0] - 1)]):
            return None, d, None, t
        return d, today, None, t
    (_, a, _wa), (_, b, wb) = found[0], found[-1]
    if wb:
        b = month_end(b.year, b.month)
    if b < a:
        a, b = b, a
    return a, b, None, t


def clean_words(text):
    words = [w for w in re.split(r"\s+", text.strip()) if w and w.lower() not in FILLER]
    return " ".join(words).strip(" ,.;:")


def fmt_money(v, cur=""):
    s = "{:,.2f}".format(v or 0)
    if s.endswith(".00"):
        s = s[:-3]
    return (cur + " " + s).strip() if cur else s


def fmt_date(d):
    return d.strftime("%d %b %Y") if d else ""
