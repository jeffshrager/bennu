#!/usr/bin/env python3
"""Compute one ship-position TSV record for shipat.

Usage: shipat_record.py <ship> <lat> <lon>

Prints one tab-separated row: ship, lat, lon, current time (UTC, when
reported), local time at that lat/lon (nautical UTC-offset convention,
same rule as local_time.py: round(lon / 15), clamped to [-12, 14]).
"""

import sys
from datetime import datetime, timedelta, timezone

from local_time import utc_offset_hours

TIMESTAMP_FMT = "%Y-%m-%d %H:%M:%S"


def main():
    if len(sys.argv) != 4:
        raise SystemExit(f"Usage: {sys.argv[0]} <ship> <lat> <lon>")

    ship, lat_s, lon_s = sys.argv[1], sys.argv[2], sys.argv[3]
    lat, lon = float(lat_s), float(lon_s)

    if not (-90 <= lat <= 90):
        raise SystemExit(f"latitude {lat} out of range [-90, 90]")
    if not (-180 <= lon <= 180):
        raise SystemExit(f"longitude {lon} out of range [-180, 180]")

    reported = datetime.now(timezone.utc)
    offset = utc_offset_hours(lon)
    ship_local = reported + timedelta(hours=offset)
    sign = "+" if offset >= 0 else "-"

    print(
        "\t".join(
            [
                ship,
                f"{lat}",
                f"{lon}",
                f"{reported.strftime(TIMESTAMP_FMT)} UTC",
                f"{ship_local.strftime(TIMESTAMP_FMT)} (UTC{sign}{abs(offset)})",
            ]
        )
    )


if __name__ == "__main__":
    main()
