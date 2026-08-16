#!/usr/bin/env python3
"""Get one ship position: try AISStream first, then fall back to cache.

Usage:
    python ship_position.py "DISNEY DREAM"
    python ship_position.py 311042900
"""

import argparse
import asyncio
import json
import os
import sys
import tempfile
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


def resolve_ship(query, ships):
    q = query.strip()
    if q.isdigit():
        for name, mmsi in ships.items():
            if mmsi == q:
                return name, mmsi
        return q, q

    for name, mmsi in ships.items():
        if name.casefold() == q.casefold():
            return name, mmsi

    raise SystemExit(f"Unknown ship {query!r}; add it to {SHIPS_FILE}")


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


def read_cache(mmsi):
    path = CACHE_DIR / f"{mmsi}.json"
    try:
        with path.open() as f:
            return json.load(f)
    except FileNotFoundError:
        return None


async def get_live(api_key, name, mmsi, timeout):
    subscription = {
        "APIKey": api_key,
        "BoundingBoxes": WORLD_BBOX,
        "FiltersShipMMSI": [mmsi],
        "FilterMessageTypes": POSITION_TYPES,
    }

    try:
        async with websockets.connect(AIS_URL, open_timeout=10) as ws:
            await ws.send(json.dumps(subscription))
            deadline = asyncio.get_running_loop().time() + timeout

            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    return None

                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except asyncio.TimeoutError:
                    return None

                msg = json.loads(raw)
                if "error" in msg:
                    print(f"AISStream error: {msg['error']}", file=sys.stderr)
                    return None

                message_type = msg.get("MessageType")
                if message_type not in POSITION_TYPES:
                    continue

                meta = msg.get("MetaData") or msg.get("Metadata") or {}
                body = msg.get("Message", {}).get(message_type, {})
                got_mmsi = str(meta.get("MMSI") or body.get("UserID") or "")
                if got_mmsi != mmsi:
                    continue

                record = clean_position(name, mmsi, msg)
                if record is not None:
                    return record

    except Exception as e:
        print(f"Live AIS unavailable: {e}", file=sys.stderr)
        return None


def print_result(record, retrieval):
    result = dict(record)
    result["retrieval"] = retrieval
    print(json.dumps(result, indent=2, sort_keys=True))


async def async_main(args):
    ships = load_ships()
    name, mmsi = resolve_ship(args.ship, ships)

    api_key = os.environ.get("AISSTREAM_API_KEY")
    live = None
    if api_key:
        live = await get_live(api_key, name, mmsi, args.timeout)
    else:
        print("AISSTREAM_API_KEY is not set; using cache only", file=sys.stderr)

    if live is not None:
        write_cache(live)
        # Read back so the returned object includes cached_at_utc too.
        cached_live = read_cache(mmsi) or live
        print_result(cached_live, "live")
        return 0

    cached = read_cache(mmsi)
    if cached is not None:
        print_result(cached, "cache")
        return 0

    print(f"No live AIS report and no cache exists for {name} ({mmsi})", file=sys.stderr)
    return 2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("ship", help="ship name from ships.json, or an MMSI")
    parser.add_argument(
        "--timeout", type=float, default=60,
        help="seconds to wait for live AIS before using cache (default: 60)",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(async_main(args)))


if __name__ == "__main__":
    main()
