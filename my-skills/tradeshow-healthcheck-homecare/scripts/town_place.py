"""Where the town the rep typed is: remembered, then Google Places, then OpenStreetMap as before (Welton 2026-10-30).

Why. On 2026-10-30 the booth's town lookup (OpenStreetMap's Nominatim, google_serp_rank.geocode_city_osm) placed
nothing for Las Vegas NV, Ozark MO and Tampa FL on four of the seven live apps, from the first lookup each app made,
while the same request from the office placed all three. Those scans went out unpinned and every map and organic cell
read "couldn't check". The lookup threw away whatever it was told, so nobody could say why (receipt
ops/receipts/20261030T183500_booth-town-lookup-fails-on-server.txt).

The order, for a town and its state:
  1. remembered on this server (a file in the temp folder, shared by the app and its search processes);
  2. remembered in the office archive (weltonhong/booth-sheets-archive, town_cache/<ST>/<town>.json), so a town any
     booth app has placed once is placed again after a restart, and one bad day cannot break it;
  3. Google Places: the town's own listing, a locality in the typed state (google_intel._town_point, the lookup the
     scan already uses for "nearby"; it worked on the failing apps that day);
  4. OpenStreetMap, exactly as before (google_serp_rank.geocode_city_osm, unchanged when Google cannot be reached).
A town is remembered only when 3 or 4 placed it. A town's coordinates do not change.

Every answer comes back with a record: which service answered, whether the result was pinned (asked now), cached
(remembered) or failed, and each attempt with its status and reply. The scan keeps it in results.json, under
places_pin -> town -> lookup.

Two settings keep tests off the network (fix-hierarchy.md, isolate a test by sink): BOOTH_TOWN_CACHE (the file for
step 1) and BOOTH_TOWN_LOOKUP_NETWORK=off (steps 2 and 3 are not asked; step 4 is whatever the caller passes in).
tradeshow-healthcheck-homecare/scripts/conftest.py sets both for every booth test.

Byte-identical in all five booth tools' scripts/ folders; test_booth_town_place.py fails if they drift apart.
"""
import datetime
import json
import os
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
INTEL_DIR = HERE.parents[1] / "quick-intel" / "scripts"

GOOGLE = "google places"
OSM = "openstreetmap nominatim"
ARCHIVE_DIR = "town_cache"
ARCHIVE_TIMEOUT = 8


def cache_file():
    return Path(os.environ.get("BOOTH_TOWN_CACHE") or Path(tempfile.gettempdir()) / "booth_town_cache.json")


def network_on():
    return os.environ.get("BOOTH_TOWN_LOOKUP_NETWORK", "").lower() != "off"


def town_key(city, state):
    return "%s|%s" % (re.sub(r"\s+", " ", (city or "").strip()).lower(), (state or "").strip().upper())


def split_town(text):
    """("Las Vegas", "NV") from "Las Vegas NV", the form the search scripts are given; no state: (text, "")."""
    parts = (text or "").replace(",", " ").split()
    if len(parts) >= 2 and re.fullmatch(r"[A-Za-z]{2}", parts[-1]):
        return " ".join(parts[:-1]), parts[-1].upper()
    return " ".join(parts), ""


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _valid(entry, key):
    try:
        return (entry["key"] == key and entry["source"] in (GOOGLE, OSM)
                and len(entry["at"]) == 2 and all(isinstance(x, (int, float)) for x in entry["at"]))
    except (KeyError, TypeError):
        return False


# ----------------------------- 1. remembered on this server -----------------------------

def _read_local():
    try:
        d = json.loads(cache_file().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _write_local(entry):
    try:
        d = _read_local()
        d[entry["key"]] = entry
        path = cache_file()
        tmp = path.with_name("%s.%d.tmp" % (path.name, os.getpid()))
        tmp.write_text(json.dumps(d), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        pass


# ----------------------------- 2. remembered in the office archive -----------------------------

def _archive():
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    import sheet_archive
    return sheet_archive


def archive_path(city, state):
    slug = re.sub(r"[^a-z0-9]+", "-", (city or "").lower()).strip("-") or "unnamed"
    return "%s/%s/%s.json" % (ARCHIVE_DIR, (state or "").upper(), slug)


def _archive_get(city, state, note):
    note.update(service="office archive cache")
    sa = _archive()
    token = os.environ.get(sa.TOKEN_ENV, "")
    if not token:
        note["status"] = "not asked (no archive token)"
        return None
    import requests
    path = archive_path(city, state)
    note["asked"] = path
    try:
        r = requests.get(sa.API % (sa.ARCHIVE_REPO, path), timeout=ARCHIVE_TIMEOUT,
                         headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github.raw"})
    except Exception as e:
        note.update(status=None, error="%s: %s" % (type(e).__name__, e))
        return None
    note["status"] = r.status_code
    if r.status_code != 200:
        note["reply"] = r.text[:300]
        return None
    try:
        return r.json()
    except Exception as e:
        note["error"] = "not JSON: %s" % e
        return None


def _archive_put(entry):
    """Remember a placed town in the office archive. Never raises; a failure only costs the next server a lookup."""
    try:
        sa = _archive()
        token = os.environ.get(sa.TOKEN_ENV, "")
        if not token:
            return
        import base64
        import requests
        requests.put(sa.API % (sa.ARCHIVE_REPO, archive_path(entry["city"], entry["state"])), timeout=ARCHIVE_TIMEOUT,
                     headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"},
                     json={"message": "Town placed: %s, %s (%s)" % (entry["city"], entry["state"], entry["source"]),
                           "content": base64.b64encode(json.dumps(entry, indent=1).encode("utf-8")).decode("ascii")})
    except Exception:
        pass


# ----------------------------- 3. Google Places -----------------------------

def _intel():
    if str(INTEL_DIR) not in sys.path:
        sys.path.insert(0, str(INTEL_DIR))
    import google_intel
    return google_intel


def _google(city, state, note):
    """(lat, lng) of the town's own listing on Google, or None; what Google said goes into `note`."""
    note.update(service=GOOGLE)
    gi = _intel()
    key = os.environ.get("GOOGLE_API_KEY", "")
    if not key:
        note["status"] = "not asked (no Google key)"
        return None
    saved, gi._RAW = gi._RAW, []
    try:
        place = gi._town_point(city, state, key)
    except Exception as e:
        place = None
        note["error"] = "%s: %s" % (type(e).__name__, e)
    finally:
        raw, gi._RAW = gi._RAW, saved
    last = raw[-1] if raw else {}
    note["asked"] = (last.get("sent") or {}).get("textQuery")
    if "answer" in last:
        note["status"] = 200
        note["reply"] = [[p.get("displayName", {}).get("text"), p.get("formattedAddress"), (p.get("types") or [])[:3],
                          p.get("location")] for p in (last["answer"] or {}).get("places", [])][:5]
    elif last.get("error"):
        m = re.search(r"HTTP Error (\d+)", last["error"])
        note.update(status=int(m.group(1)) if m else None, error=last["error"][:300])
    if place:
        note["placed"] = [place.get("name"), place.get("address")]
        loc = place.get("location") or {}
        return [loc["latitude"], loc["longitude"]]
    return None


# ----------------------------- the lookup -----------------------------

def _osm_default(text, note):
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    import google_serp_rank
    return google_serp_rank.geocode_city_osm(text, note=note)


def resolve(city, state, osm=None):
    """((lat, lng), record) or (None, record). `osm(text, note)` is the old lookup, step 4."""
    osm = osm or _osm_default
    key = town_key(city, state)
    rec = {"town": "%s, %s" % (city, state) if state else city, "attempts": []}

    def done(at, result, source, **extra):
        rec.update(result=result, source=source, at=list(at) if at else None, **extra)
        return (tuple(at) if at else None), rec

    def remember(at, source):
        entry = {"key": key, "city": city, "state": state.upper(), "at": list(at), "source": source,
                 "placed_at": _now()}
        _write_local(entry)
        if network_on():
            _archive_put(entry)

    if state:
        hit = _read_local().get(key)
        if _valid(hit, key):
            return done(hit["at"], "cached", hit["source"], cached_in="this server", placed_at=hit.get("placed_at"))
        if network_on():
            note = {}
            rec["attempts"].append(note)
            hit = _archive_get(city, state, note)
            if _valid(hit, key):
                _write_local(hit)
                return done(hit["at"], "cached", hit["source"], cached_in="the office archive",
                            placed_at=hit.get("placed_at"))
            note = {}
            rec["attempts"].append(note)
            at = _google(city, state, note)
            if at:
                remember(at, GOOGLE)
                return done(at, "pinned", GOOGLE)
        else:
            rec["attempts"].append({"service": "office archive cache and " + GOOGLE,
                                    "status": "not asked (BOOTH_TOWN_LOOKUP_NETWORK=off)"})
    note = {"service": OSM}
    rec["attempts"].append(note)
    try:
        at = osm(("%s %s" % (city, state)) if state else city, note)
    except Exception as e:
        at = None
        note["error"] = "%s: %s" % (type(e).__name__, e)
    if at:
        if state:
            remember(at, OSM)
        return done(at, "pinned", OSM)
    return done(None, "failed", None)


def why(rec):
    """One line: what each service said, for the scan record and the search error."""
    out = []
    for a in rec.get("attempts") or []:
        said = a.get("error") or (("HTTP %s" % a["status"]) if isinstance(a.get("status"), int) else a.get("status"))
        if a.get("status") == 200 and not a.get("error"):
            said = "HTTP 200, no %s in the answer" % ("town in that state" if a.get("service") == GOOGLE else "match")
        out.append("%s: %s" % (a.get("service"), said or "no answer"))
    return "; ".join(out)
