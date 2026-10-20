"""The rep confirms the business's own Google listing at the booth: "Is this your address?" (Welton, 2026-10-20).

Before this, the sheet took the business's review count, rating, website and map identity from Google's
FIRST answer to its name, whoever that was. Now, before the scan, the app shows the address Google has
for the business (the same lookup the state check already makes, scripts/state_check.py) and asks the
question the rep can turn and ask the owner, who knows their own address:

    Is this your address?            (one listing)
    Which one is your address?       (several: La Paloma has two)

  Yes / the address           that listing is used for the reviews, the website and the map matching
  No / None of these          the scan runs; nothing is taken from Google's guess
  no answer in WAIT_SECONDS   the same as No (Welton: "the sheet should never guess because nobody
                              clicked"; a rep at a booth gets pulled away)
  no listing found            the same as No, without asking

Not confirmed means: the reviews read "Couldn't check (Google listing not confirmed)" (never someone
else's numbers, never a zero),
no review gap, no reviews grade, the website reads "Couldn't check", and map cards are matched without
a listing id (scripts/map_identity.py: "couldn't confirm" where only the name points at them).

Identical copies live in all five booth tools' scripts/ folders;
tradeshow-healthcheck-homecare/scripts/test_booth_listing_confirm.py fails if they drift apart.
"""
import os

WAIT_SECONDS = 30

SAID_NO = "the owner said the address Google has is not theirs"
NO_ANSWER = "nobody confirmed the address Google has for them"
NOT_FOUND = "Google has no listing under their name in this state"


def wait_seconds():
    """How long the question waits before the scan runs without an answer.

    BOOTH_CONFIRM_SECONDS=0 is for the screen tests only: no timer, the app stops and waits for the
    click (test_booth_listing_confirm.py). The deployed apps never set it.
    """
    try:
        return max(0, int(os.environ.get("BOOTH_CONFIRM_SECONDS", WAIT_SECONDS)))
    except ValueError:
        return WAIT_SECONDS


def not_confirmed(why):
    """The listing to scan with when the rep did not confirm one."""
    return {"error": why, "unconfirmed": True}


def known(target):
    """True only for a real listing: one the rep confirmed, or (outside the booth app) the lookup's own."""
    target = target or {}
    return bool(target.get("name")) and not target.get("error")


def reason(target):
    """What the sheet prints where the listing's numbers would be.

    The same short words whatever the cause: the owner reads this sheet. Why it was not confirmed
    (said no, nobody answered, none found) stays in the saved results, target["error"].
    """
    return "Couldn't check (Google listing not confirmed)" if (target or {}).get("unconfirmed") else "Couldn't check"


def apply(intel, listing):
    """The Google section after the rep's answer: the confirmed listing, or nothing from Google's guess."""
    intel = dict(intel or {})
    intel["target"] = dict(listing or not_confirmed(NO_ANSWER))
    intel["listing_confirmed"] = known(intel["target"])
    return intel
