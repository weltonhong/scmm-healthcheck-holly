"""
Quick Intel - Google Places API lookup

Returns review count, rating, business status for the target business
AND top competitors in one shot. Two API calls total.

Usage:
    python google_intel.py --business "Tewksbury Funeral Home" \
        --city "Tewksbury" --state "MA" --vertical "funeral home"

Output: JSON to stdout with target + competitor data.
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
import urllib.error


PLACES_API_URL = "https://places.googleapis.com/v1/places:searchText"

FIELD_MASK = (
    "places.displayName,"
    "places.formattedAddress,"
    "places.rating,"
    "places.userRatingCount,"
    "places.businessStatus,"
    "places.googleMapsUri,"
    "places.websiteUri"
)


def get_api_key():
    """Get Google API key from environment."""
    key = os.environ.get("GOOGLE_API_KEY", "")
    if not key:
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 "[System.Environment]::GetEnvironmentVariable('GOOGLE_API_KEY', 'User')"],
                capture_output=True, text=True, timeout=5
            )
            key = result.stdout.strip()
        except Exception:
            pass
    return key


def places_search(query, api_key, max_results=5):
    """Run a Places API text search. Returns list of place dicts."""
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
    }
    body = json.dumps({
        "textQuery": query,
        "maxResultCount": max_results,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            PLACES_API_URL, data=body, headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}

    results = []
    for place in data.get("places", []):
        results.append({
            "name": place.get("displayName", {}).get("text", ""),
            "address": place.get("formattedAddress", ""),
            "rating": place.get("rating"),
            "review_count": place.get("userRatingCount"),
            "status": place.get("businessStatus", ""),
            "maps_url": place.get("googleMapsUri", ""),
            "website": place.get("websiteUri", ""),
        })
    return results


def main():
    parser = argparse.ArgumentParser(description="Quick Intel Google lookup")
    parser.add_argument("--business", required=True, help="Business name")
    parser.add_argument("--city", required=True, help="City")
    parser.add_argument("--state", required=True, help="State abbreviation")
    parser.add_argument("--vertical", default="funeral home", help="Business vertical")
    args = parser.parse_args()

    api_key = get_api_key()
    if not api_key:
        print(json.dumps({"error": "GOOGLE_API_KEY not found"}))
        sys.exit(1)

    # Search 1: Target business (exact name + location)
    target_query = f"{args.business} {args.city} {args.state}"
    target_results = places_search(target_query, api_key, max_results=3)

    # Search 2: Competitors (vertical + city)
    competitor_query = f"{args.vertical} {args.city} {args.state}"
    competitor_results = places_search(competitor_query, api_key, max_results=10)

    # Identify target in results
    target = None
    if isinstance(target_results, list) and target_results:
        target = target_results[0]

    # Filter competitors (exclude target business)
    competitors = []
    if isinstance(competitor_results, list):
        target_name_lower = args.business.lower() if args.business else ""
        for c in competitor_results:
            if target_name_lower and target_name_lower in c.get("name", "").lower():
                # If target shows up in competitor search, use that data (may have more fields)
                if target and not target.get("review_count") and c.get("review_count"):
                    target = c
                continue
            competitors.append(c)

    output = {
        "target": target if isinstance(target, dict) else {"error": str(target_results)},
        "competitors": competitors[:5],
        "query_target": target_query,
        "query_competitors": competitor_query,
    }

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
