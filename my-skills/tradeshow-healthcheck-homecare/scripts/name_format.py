"""How a business's name is printed to the PROSPECT (Welton, 2026-10-19).

The teaser is the one piece a prospect reads, and a badly printed name is the single most likely
thing to make an owner decide a machine wrote it. Measured over the 43 saved teasers on 10-19:
9 printed the name wrong:
    "research on Joseph J.Pula Funeral Home and Cremation Services, Inc.. A few things"
    "research on Wellovah Home Health Care, LLC.. A few things"
    "research on Help at Home Senior Care (3 Locations - CA + NV). A few things"
    "research on Community Hospice (Ashland KY & Ironton OH). A few things"

FORMAT ONLY, NEVER WORDS. A listing that spells the name "Engram Funeral Hme" is evidence the brief
reports; this module never corrects a word, it only fixes spacing and punctuation and removes the
notes a rep types into the name field ("(3 Locations)", " - 3 Locations AZ").
NOT handled, on purpose: a bare trailing state ("Blue Rose Legacy Care AZ"), because telling a
typed note from a real word there is a guess.
"""
import re

_STATES = ("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ "
           "NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC").split()

# A note in brackets that a rep typed: it carries a location count, a digit or a state code.
_NOTE_IN_BRACKETS = re.compile(r"\s*\((?=[^)]*(?:\blocations?\b|\d|\b(?:%s)\b))[^)]*\)" % "|".join(_STATES))
_NOTE_AFTER_DASH = re.compile(r"\s+[-–]\s+\d+\s+locations?\b.*$", re.IGNORECASE)


def for_prospect(name):
    """The name as the prospect should see it: spacing and punctuation fixed, typed notes removed."""
    s = " ".join(str(name or "").split())
    s = _NOTE_IN_BRACKETS.sub("", s)
    s = _NOTE_AFTER_DASH.sub("", s)
    s = re.sub(r"\b([A-Z])\.(?=[A-Z][a-z])", r"\1. ", s)       # "J.Pula" -> "J. Pula"
    s = re.sub(r"\s+([,.;:])", r"\1", s)                        # "Care , LLC" -> "Care, LLC"
    s = re.sub(r",(?=[A-Za-z])", ", ", s)                       # "Care,LLC" -> "Care, LLC"
    s = re.sub(r"([.,;:])\1+", r"\1", s)                        # "Inc.." -> "Inc."
    s = re.sub(r"[\s,;:\-–]+$", "", s)                     # trailing comma, colon, dash
    return s.strip()


def end_sentence(name):
    """The name closing a sentence, without a second full stop ("Inc." stays "Inc.")."""
    return name if name.endswith((".", "!", "?")) else name + "."
