#!/usr/bin/env python3
"""Periodically collect AIS positions for configured ships and cache them.

Configuration:
  - AISSTREAM_API_KEY environment variable
  - ships.json next to this script, mapping ship name -> MMSI

Cache:
  - cache/<MMSI>.json, written atomically
"""

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import websockets

AIS_URL = "wss://stream.aisstream.io/v0/stream"
WORLD_BBOX = [[[-90, -180], [90, 180]]]
POSITION_TYPES = [
    "PositionReport",
    "StandardClassBPositionReport",
    "ExtendedClassBPositionReport",
    "LongRangeAisBroadcastMessage",
]

BASE_DIR = Path(__file__).resolve().parent
SHIPS_FILE = BASE_DIR / "ships.json"
CACHE_DIR = BASE_DIR / "cache"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def load_ships():
    with SHIPS_FILE.open() as f:
        ships = json.load(f)
    return {str(name): str(mmsi) for name, mmsi in ships.items()}


def clean_position(name, mmsi, msg):
    message_type = msg.get("MessageType")
    body = msg.get("Message", {}).get(message_type, {})
    meta = msg.get("MetaData") or msg.get("Metadata") or {}

    lat = body.get("Latitude")
    lon = body.get("Longitude")
    sog = body.get("Sog")
    cog = body.get("Cog")
    heading = body.get("TrueHeading")

    if lat is None or lon is None:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None

    # Standard AIS "not available" values.
    if sog is not None and sog >= 102.3:
        sog = None
    if cog is not None and cog >= 360:
        cog = None
    if heading is not None and heading >= 511:
        heading = None

    return {
        "name": name,
        "mmsi": str(mmsi),
        "latitude": lat,
        "longitude": lon,
        "speed_knots": sog,
        "course_deg": cog,
        "heading_deg": heading,
        "ais_time_utc": meta.get("time_utc"),
        "received_at_utc": utc_now(),
        "source": "aisstream.io",
        "message_type": message_type,
    }


def write_cache(record):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target = CACHE_DIR / f"{record['mmsi']}.json"
    record = dict(record)
    record["cached_at_utc"] = utc_now()

    fd, temp_name = tempfile.mkstemp(
        dir=CACHE_DIR, prefix=f".{record['mmsi']}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(record, f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


async def collect_once(api_key, ships, timeout):
    """Listen for up to timeout seconds and return newest record heard per MMSI."""
    mmsi_to_name = {mmsi: name for name, mmsi in ships.items()}
    wanted = set(mmsi_to_name)
    found = {}

    subscription = {
        "APIKey": api_key,
        "BoundingBoxes": WORLD_BBOX,
        "FiltersShipMMSI": list(wanted),
        "FilterMessageTypes": POSITION_TYPES,
    }

    try:
        async with websockets.connect(AIS_URL, open_timeout=10) as ws:
            # AISStream requires the subscription within 3 seconds of connection.
            await ws.send(json.dumps(subscription))
            deadline = asyncio.get_running_loop().time() + timeout

            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break

                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except asyncio.TimeoutError:
                    break

                msg = json.loads(raw)
                if "error" in msg:
                    raise RuntimeError(f"AISStream error: {msg['error']}")

                message_type = msg.get("MessageType")
                if message_type not in POSITION_TYPES:
                    continue

                meta = msg.get("MetaData") or msg.get("Metadata") or {}
                body = msg.get("Message", {}).get(message_type, {})
                mmsi = str(meta.get("MMSI") or body.get("UserID") or "")
                if mmsi not in wanted:
                    continue

                record = clean_position(mmsi_to_name[mmsi], mmsi, msg)
                if record is not None:
                    found[mmsi] = record

                # Once every tracked ship has reported, there is no reason to wait.
                if len(found) == len(wanted):
                    break

    except Exception as e:
        print(f"{utc_now()} AIS collection failed: {e}", file=sys.stderr)

    return found


async def run_forever(interval, timeout):
    api_key = os.environ.get("AISSTREAM_API_KEY")
    if not api_key:
        raise SystemExit("AISSTREAM_API_KEY is not set")

    while True:
        cycle_started = time.monotonic()

        try:
            ships = load_ships()
        except Exception as e:
            print(f"{utc_now()} could not load {SHIPS_FILE}: {e}", file=sys.stderr)
            ships = {}

        if ships:
            print(f"{utc_now()} checking {len(ships)} ship(s)...", flush=True)
            records = await collect_once(api_key, ships, timeout)

            for mmsi, record in records.items():
                write_cache(record)
                print(
                    f"{utc_now()} cached {record['name']} ({mmsi}) "
                    f"{record['latitude']:.5f},{record['longitude']:.5f}",
                    flush=True,
                )

            missing = [name for name, mmsi in ships.items() if mmsi not in records]
            if missing:
                print(
                    f"{utc_now()} no new data for: {', '.join(missing)}; "
                    "existing cache left untouched",
                    flush=True,
                )
        else:
            print(f"{utc_now()} no ships configured", file=sys.stderr, flush=True)

        elapsed = time.monotonic() - cycle_started
        await asyncio.sleep(max(0, interval - elapsed))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--interval", type=float, default=3600,
        help="seconds between start of collection cycles (default: 3600)",
    )
    parser.add_argument(
        "--timeout", type=float, default=60,
        help="seconds to wait for AIS reports per cycle (default: 60)",
    )
    args = parser.parse_args()
    asyncio.run(run_forever(args.interval, args.timeout))


if __name__ == "__main__":
    main()
