#!/usr/bin/env python3
"""
fetch_planet3.py

Fetch https://swapi.dev/api/planets/3/ and save the result as CSV to ~/Desktop/planet_3_auto.csv
"""
import json
import csv
import os
from urllib.request import Request, urlopen

API_URL = "https://swapi.dev/api/planets/3/"
OUT_PATH = os.path.expanduser("~/Desktop/planet_3_auto.csv")


def fetch_json(url: str, timeout: int = 10):
    req = Request(url, headers={"User-Agent": "fetch-planet3-script/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def flatten(obj, parent_key="", sep="."):
    items = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            items.update(flatten(v, new_key, sep=sep))
    elif isinstance(obj, list):
        # join list of primitives, otherwise JSON encode
        if all(v is None or isinstance(v, (str, int, float, bool)) for v in obj):
            items[parent_key] = "|".join("" if v is None else str(v) for v in obj)
        else:
            items[parent_key] = json.dumps(obj, ensure_ascii=False)
    else:
        items[parent_key] = "" if obj is None else str(obj)
    return items


def write_csv(data: dict, out_path: str):
    flat = flatten(data)
    keys = list(flat.keys())
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(keys)
        writer.writerow([flat.get(k, "") for k in keys])


if __name__ == '__main__':
    print(f"Fetching {API_URL}...")
    data = fetch_json(API_URL)
    print(f"Writing CSV to {OUT_PATH}...")
    write_csv(data, OUT_PATH)
    print("Done.")
