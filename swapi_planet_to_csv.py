#!/usr/bin/env python3
"""
Fetch https://swapi.dev/api/planets/3/ and write the JSON fields to a CSV file on the Desktop.
Produces: ~/Desktop/planet_3.csv
"""

import json
import csv
import sys
import os
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

API_URL = "https://swapi.dev/api/planets/3/"


def fetch_json(url: str) -> dict:
    req = Request(url, headers={"User-Agent": "python-urllib/3"})
    try:
        with urlopen(req, timeout=10) as resp:
            raw = resp.read()
            return json.loads(raw)
    except HTTPError as e:
        print(f"HTTP error: {e.code} - {e.reason}")
        raise
    except URLError as e:
        print(f"URL error: {e.reason}")
        raise
    except Exception as e:
        print(f"Unexpected error while fetching JSON: {e}")
        raise


def flatten_value(value):
    # Convert lists to a single string joined by '|' and leave scalars as strings
    if isinstance(value, list):
        return "|".join(map(str, value))
    if value is None:
        return ""
    return str(value)


def write_csv(data: dict, output_path: str) -> None:
    # Ensure directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Use the keys from the JSON as header in the order returned
    headers = list(data.keys())

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        row = [flatten_value(data.get(h, "")) for h in headers]
        writer.writerow(row)


def main():
    out_path = os.path.expanduser("~/Desktop/planet_3.csv")
    try:
        print(f"Fetching {API_URL}...")
        data = fetch_json(API_URL)
        print("Fetched JSON. Writing CSV to:", out_path)
        write_csv(data, out_path)
        print("Done.")
    except Exception as e:
        print("Failed:", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
