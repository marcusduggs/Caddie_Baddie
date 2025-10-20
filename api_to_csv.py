#!/usr/bin/env python3
"""
api_to_csv.py

Fetch JSON from a provided API URL and write it to a CSV file.

Usage examples:
  python3 ~/Desktop/api_to_csv.py --url https://swapi.dev/api/planets/3/ --output ~/Desktop/planet_3.csv
  python3 ~/Desktop/api_to_csv.py --url https://swapi.dev/api/planets/ --output ~/Desktop/planets.csv

Behavior:
- If the top-level JSON is an object (dict), it writes one row with that object's fields.
- If the top-level JSON is a list, it writes one row per list item and unions the set of keys for the header.
- Nested objects are flattened with dot notation (e.g., details.size -> details.size).
- Lists of primitives are joined with '|' by default. Lists of objects are JSON-stringified per cell.
"""

import argparse
import csv
import json
import os
import sys
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


def fetch_json(url: str, timeout: int = 10):
    req = Request(url, headers={"User-Agent": "api-to-csv/1.0 (https://example)"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw)
    except HTTPError as e:
        print(f"HTTP error: {e.code} - {e.reason}")
        raise
    except URLError as e:
        print(f"URL error: {e.reason}")
        raise
    except Exception as e:
        print(f"Failed to fetch or parse JSON: {e}")
        raise


def is_primitive(v):
    return v is None or isinstance(v, (str, int, float, bool))


def flatten(obj, parent_key="", sep="."):
    """Flatten a nested dict into a dict with dot-notated keys.

    Lists of primitives are joined with '|' and lists of objects are JSON-encoded.
    """
    items = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            items.update(flatten(v, new_key, sep=sep))
    elif isinstance(obj, list):
        # If list of primitives, join
        if all(is_primitive(x) for x in obj):
            items[parent_key] = "|".join("" if x is None else str(x) for x in obj)
        else:
            # For lists containing dicts or mixed types, store JSON string
            items[parent_key] = json.dumps(obj, ensure_ascii=False)
    else:
        items[parent_key] = "" if obj is None else str(obj)
    return items


def write_csv_from_list_of_dicts(list_of_dicts, out_path):
    # Collect all keys
    keys = set()
    for d in list_of_dicts:
        keys.update(d.keys())
    keys = sorted(keys)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(keys)
        for d in list_of_dicts:
            row = [d.get(k, "") for k in keys]
            writer.writerow(row)


def main():
    parser = argparse.ArgumentParser(description="Fetch JSON from an API and write to CSV")
    parser.add_argument("--url", required=True, help="API URL that returns JSON")
    parser.add_argument("--output", default="~/Desktop/api_output.csv", help="Output CSV path (default: ~/Desktop/api_output.csv)")
    parser.add_argument("--sep", default='.', help="Key separator for flattened fields (default: '.')")
    args = parser.parse_args()

    url = args.url
    out_path = os.path.expanduser(args.output)

    try:
        print(f"Fetching: {url}")
        data = fetch_json(url)
    except Exception as e:
        print("Error fetching JSON:", e)
        sys.exit(1)

    # Normalize to list of flattened dicts
    rows = []
    if isinstance(data, list):
        for item in data:
            rows.append(flatten(item, parent_key="", sep=args.sep))
    elif isinstance(data, dict):
        # If the dict contains a top-level 'results' key (common in paginated APIs), use that list
        if "results" in data and isinstance(data["results"], list):
            for item in data["results"]:
                rows.append(flatten(item, parent_key="", sep=args.sep))
        else:
            rows.append(flatten(data, parent_key="", sep=args.sep))
    else:
        print("Unexpected JSON top-level type: ", type(data))
        sys.exit(1)

    if not rows:
        print("No rows to write.")
        sys.exit(1)

    try:
        write_csv_from_list_of_dicts(rows, out_path)
        print(f"Wrote CSV to: {out_path}")
    except Exception as e:
        print("Failed to write CSV:", e)
        sys.exit(1)


if __name__ == '__main__':
    main()
