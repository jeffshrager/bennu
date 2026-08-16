import asyncio
import json
import os
import websockets

#MMSI = "311042900"       # Disney Dream
#MMSI = "311001098"       # Disney Wish
MMSI = "636020723"       # Rome Trader
API_KEY = os.environ["AISSTREAM_API_KEY"]

async def main():
    uri = "wss://stream.aisstream.io/v0/stream"

    async with websockets.connect(uri) as ws:
        subscription = {
            "APIKey": API_KEY,
            "BoundingBoxes": [[[-90, -180], [90, 180]]],
            "FiltersShipMMSI": [MMSI],
            "FilterMessageTypes": ["PositionReport"],
        }

        await ws.send(json.dumps(subscription))

        async for raw in ws:
            msg = json.loads(raw)

            if msg["MessageType"] != "PositionReport":
                continue

            p = msg["Message"]["PositionReport"]

            print(
                f"lat={p['Latitude']:.5f} "
                f"lon={p['Longitude']:.5f} "
                f"speed={p['Sog']:.1f} knots "
                f"course={p['Cog']:.1f} deg "
                f"heading={p['TrueHeading']} deg"
            )

asyncio.run(main())
