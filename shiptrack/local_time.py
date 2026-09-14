#!/usr/bin/env python3
"""Convert a lat/long position to local time at that location.

Local time is derived from longitude alone: each 15 degrees of longitude is
one hour offset from UTC (the standard nautical time zone convention). This
ignores actual time zone boundaries, DST, and regional exceptions (e.g.
Arizona not observing DST).

Usage:
    python local_time.py <lat> <lon>
    python local_time.py 37.7749 -122.4194
"""

import argparse
from datetime import datetime, timedelta, timezone


def utc_offset_hours(lon):
    offset = round(lon / 15)
    return max(-12, min(14, offset))


def local_time_str(lat, lon, now=None):
    if not (-90 <= lat <= 90):
        raise ValueError(f"latitude {lat} out of range [-90, 90]")
    if not (-180 <= lon <= 180):
        raise ValueError(f"longitude {lon} out of range [-180, 180]")

    now = now or datetime.now(timezone.utc)
    offset = utc_offset_hours(lon)
    local = now + timedelta(hours=offset)
    return local.strftime("%H:%M:%S"), offset


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("lat", type=float, help="latitude in decimal degrees")
    parser.add_argument("lon", type=float, help="longitude in decimal degrees")
    args = parser.parse_args()

    time_str, offset = local_time_str(args.lat, args.lon)
    sign = "+" if offset >= 0 else "-"
    print(f"{time_str} (UTC{sign}{abs(offset)})")


if __name__ == "__main__":
    main()
