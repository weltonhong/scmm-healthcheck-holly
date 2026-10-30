"""Booth state check: the state the rep chose must match the business's own Google listing.

Welton, 2026-10-20. The La Paloma Funeral Services sheet (Las Vegas, Nevada)
was measured in New York: the State dropdown came preset to NY, the rep left
it, and every search was pinned to New York towns called Las Vegas, Henderson
and Boulder City. The town lookup's own state guard (10-13) could not help:
it checks a town against the state the rep picked, and the rep had picked NY.

So before any search is spent, the app looks the business up on Google (the
same Places lookup the scan makes for its listing section) with the name, the
home city and the chosen state, and reads the state off each listing whose
name is the business's:

  STATE_OK           a listing with the business's name sits in the chosen state
  STATE_MISMATCH     listings with the business's name came back, and NONE is in
                     the chosen state: the scan is REFUSED, naming what Google shows
  STATE_UNCONFIRMED  no listing with the business's name came back, or Google could
                     not be asked: nothing contradicts the rep's choice, so the scan
                     runs and its listing section reads couldn't-check as before

Why UNCONFIRMED runs rather than refuses: a business with no Google listing is
a real booth visitor (and a strong prospect), and refusing it would leave the
owner with no sheet. The state was still chosen by the rep (there is no preset
any more), and each town is still checked against it by the town lookup.

Identical copies live in all five booth tools' scripts/ folders;
tradeshow-healthcheck-homecare/scripts/test_booth_state_check.py fails if they
drift apart.
"""
import re
import sys
from pathlib import Path

STATE_OK = "ok"
STATE_MISMATCH = "mismatch"
STATE_UNCONFIRMED = "unconfirmed"

_INTEL_DIR = Path(__file__).resolve().parents[2] / "quick-intel" / "scripts"

# "5450 N Stephanie St, Las Vegas, NV 89122, USA" -> NV. Also "..., NV, USA".
_ADDRESS_STATE = re.compile(r",\s*([A-Z]{2})(?:\s+\d{5}(?:-\d{4})?)?,\s*USA\s*$")


def address_state(address):
    """Two-letter state from a Google formatted address, or None."""
    m = _ADDRESS_STATE.search(address or "")
    return m.group(1) if m else None


def _intel():
    if str(_INTEL_DIR) not in sys.path:
        sys.path.insert(0, str(_INTEL_DIR))
    import google_intel
    return google_intel


def town_lookup(city, state):
    """((lat, lng), how, record) for the town the rep typed, or (None, why, record): town_place.resolve, the lookup
    the map and organic searches use too (remembered, then Google Places, then OpenStreetMap's
    google_serp_rank.geocode_city_osm as before; Welton 2026-10-30). The record says which service answered,
    whether the town was pinned, cached or failed, and what each service said."""
    import town_place
    at, rec = town_place.resolve(city, state)
    if not at:
        return None, "the town lookup placed nothing for %s, %s (%s)" % (city, state, town_place.why(rec)), rec
    if rec["result"] == "cached":
        how = "%s, remembered on %s (%s, %s)" % (_SOURCE[rec["source"]], rec["cached_in"], city, state)
    else:
        how = "%s (%s, %s)" % (_SOURCE[rec["source"]], city, state)
    return tuple(at), how, rec


_SOURCE = {"google places": "Google Places, the town's own listing",
           "openstreetmap nominatim": "the booth's town lookup"}


def town_pin(city, state, locate=None):
    """The pin record for the town the rep typed (google_intel.pin_note): pinned, with the place and where it came
    from, or not pinned, with why. `locate` is town_lookup in the app and the command line; it is passed in, never
    defaulted, so no test reaches the lookup by accident (Welton 2026-10-29: pin the booth's Places searches)."""
    gi = _intel()
    if locate is None:
        return gi.pin_note(None, "no town lookup on this path")
    try:
        got = locate(city, state)
    except Exception as e:
        return gi.pin_note(None, "the town lookup failed (%s)" % type(e).__name__)
    pin = gi.pin_note(got[0], got[1])
    if len(got) > 2:
        pin["lookup"] = got[2]      # which service answered, pinned / cached / failed, and what each said
    return pin


def check_listing_state(business, city, state, api_key, search=None, locate=None, pin_out=None):
    """Return (verdict, listings): the lookup's places whose name is the business's, each with its "state".

    The same places are what the rep is asked to confirm (scripts/listing_confirm.py), so the
    app makes this one lookup per scan. The search is pinned to the town when `locate` places it
    (town_pin); the pin record goes into `pin_out` and from there to the scan, which reuses it.
    """
    gi = _intel()
    search = search or gi.places_search
    pin = town_pin(city, state, locate)
    if pin_out is not None:
        pin_out.clear()
        pin_out.update(pin)
    places = search("%s %s %s" % (business, city, state), api_key, max_results=3,
                    **({"at": tuple(pin["at"])} if pin["pinned"] else {}))
    if not isinstance(places, list):
        return STATE_UNCONFIRMED, []
    own = [dict(p, state=address_state(p.get("address")))
           for p in places if gi.is_same_business(business, p.get("name", ""))]
    own = [o for o in own if o["state"]]
    if not own:
        return STATE_UNCONFIRMED, []
    if any(o["state"] == state for o in own):
        return STATE_OK, own
    return STATE_MISMATCH, own


def mismatch_message(business, state, listings):
    """What the rep reads when the scan is refused."""
    where = "; ".join(o["address"] for o in listings[:2])
    found = sorted({o["state"] for o in listings})
    return ("Google lists %s in %s (%s), not %s. Choose %s as the state and run it again. "
            "The scan did not run, so nothing was measured in the wrong place."
            % (business, " / ".join(found), where, state, " or ".join(found)))
