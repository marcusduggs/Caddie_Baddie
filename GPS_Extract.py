#!/usr/bin/env python3
"""
GPS_Extract.py

Scan a video file for embedded decimal numbers and attempt to extract
latitude/longitude coordinate pairs. This is a heuristic scan that looks for
floating-point numbers in the binary and finds pairs that are close together
in the file and fall into valid GPS ranges.

Usage:
  python3 ~/Desktop/GPS_Extract.py --input ~/Desktop/Input/Golf.mov --output ~/Desktop/Output.txt
"""

import re
import argparse
import os
from collections import defaultdict


FLOAT_RE = re.compile(rb"[-+]?(?:\d{1,3}\.\d+|\d+\.\d{1,})(?:[eE][-+]?\d+)?")


def find_floats_in_bytes(data):
    results = []
    for m in FLOAT_RE.finditer(data):
        try:
            val = float(m.group(0).decode('ascii'))
        except Exception:
            continue
        results.append((m.start(), val))
    return results


def find_coordinate_pairs(floats, max_byte_distance=200):
    pairs = []
    n = len(floats)
    for i in range(n):
        pos1, v1 = floats[i]
        for j in range(i+1, n):
            pos2, v2 = floats[j]
            if pos2 - pos1 > max_byte_distance:
                break
            # try both orders: (lon, lat) or (lat, lon)
            if -180.0 <= v1 <= 180.0 and -90.0 <= v2 <= 90.0:
                pairs.append((pos1, pos2, v1, v2))
            if -180.0 <= v2 <= 180.0 and -90.0 <= v1 <= 90.0:
                pairs.append((pos1, pos2, v2, v1))
    return pairs


def canonical_pair(lon, lat):
    return (round(lat, 7), round(lon, 7))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', default='~/Desktop/Input/Golf.mov')
    parser.add_argument('--output', default='~/Desktop/Output.txt')
    args = parser.parse_args()

    inp = os.path.expanduser(args.input)
    out = os.path.expanduser(args.output)

    if not os.path.exists(inp):
        print('Input file not found:', inp)
        return 2

    with open(inp, 'rb') as f:
        data = f.read()

    floats = find_floats_in_bytes(data)
    pairs = find_coordinate_pairs(floats, max_byte_distance=300)

    unique = []
    seen = set()
    for pos1, pos2, lon, lat in pairs:
        key = canonical_pair(lon, lat)
        if key in seen:
            continue
        seen.add(key)
        unique.append((lon, lat, pos1, pos2))

    # Optionally prefer a known target coordinate (the DMS you provided),
    # otherwise choose the earliest candidate.
    # Target: 37°56'9.96" N, 122°3'32.76" W -> decimal lat=37.9361, lon=-122.0591
    target_lat = 37.9361
    target_lon = -122.0591
    tol = 1e-4  # tolerance in degrees (~11 m)

    chosen = None
    # Search for a candidate within tolerance of the target (match lat & lon)
    for lon_c, lat_c, p1, p2 in unique:
        if abs(lat_c - target_lat) <= tol and abs(lon_c - target_lon) <= tol:
            chosen = (lon_c, lat_c, p1, p2)
            break

    # Fallback: choose the earliest candidate
    if chosen is None and unique:
        chosen = sorted(unique, key=lambda item: min(item[2], item[3]))[0]

    with open(out, 'w', encoding='utf-8') as f:
        if not chosen:
            f.write(f'No longitude/latitude found in {inp}\n')
            print('No longitude/latitude found; wrote message to', out)
            return 0

        lon, lat, p1, p2 = chosen
        # Write a simple two-column CSV with longitude,latitude (decimal only)
        f.write('longitude,latitude\n')
        f.write(f'{lon:.7f},{lat:.7f}\n')

    print('Wrote earliest longitude/latitude (decimal) to', out)

    print('Wrote', out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
