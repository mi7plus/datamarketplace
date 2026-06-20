# app/pii.py
#
# Lightweight PII detection for ingest (S4). Scans cell values for emails, phone
# numbers, national-ID-shaped strings, and Luhn-valid payment cards. High-risk
# uploads (payment cards, national IDs, or a high density of contact PII) are
# flagged/quarantined for review rather than auto-listed.
#
# This is a heuristic screen, not a compliance guarantee — it errs toward flagging.

import re

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")          # US SSN shape
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\s().\-]?){9,14}\d(?!\d)")
_CARD_CANDIDATE_RE = re.compile(r"\b(?:\d[ \-]?){13,19}\b")

# Scan caps so a huge upload can't make ingest expensive.
_MAX_ROWS = 1000
_MAX_CELL_LEN = 200


def _luhn_ok(digits: str) -> bool:
    if not (13 <= len(digits) <= 19):
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = ord(ch) - 48
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _looks_like_phone(s: str) -> bool:
    digits = re.sub(r"\D", "", s)
    return 10 <= len(digits) <= 15


def scan_pii_rows(rows: list[dict]) -> dict:
    """
    Return {emails, phones, national_ids, payment_cards, risk} for a bounded scan
    of the parsed rows. risk is 'none' | 'low' | 'high'.
    """
    emails = phones = national_ids = cards = 0

    for row in rows[:_MAX_ROWS]:
        for val in row.values():
            if not isinstance(val, str) or not val:
                continue
            s = val[:_MAX_CELL_LEN]

            emails += len(_EMAIL_RE.findall(s))
            national_ids += len(_SSN_RE.findall(s))

            for cand in _CARD_CANDIDATE_RE.findall(s):
                if _luhn_ok(re.sub(r"\D", "", cand)):
                    cards += 1

            # Count a phone only if the cell looks like one (avoid ID/code noise)
            if _PHONE_RE.search(s) and _looks_like_phone(s):
                phones += 1

    scanned = min(len(rows), _MAX_ROWS)
    contact_density = (emails + phones) / scanned if scanned else 0.0

    # High risk: any payment card or national ID, or pervasive contact PII.
    if cards > 0 or national_ids > 0 or contact_density >= 0.5:
        risk = "high"
    elif emails or phones:
        risk = "low"
    else:
        risk = "none"

    return {
        "emails": emails,
        "phones": phones,
        "national_ids": national_ids,
        "payment_cards": cards,
        "rows_scanned": scanned,
        "risk": risk,
    }
