import argparse
import asyncio
import json

import websockets


DEFAULT_URIS = (
    "ws://localhost:8000/api/ws/shots",
    "ws://localhost:8000/ws/shots",
)
MESSAGE_TIMEOUT_SECONDS = 5.0
MAX_MESSAGES_PER_URI = 3


async def monitor_uri(uri):
    print(f"Connecting to {uri}...")

    try:
        async with websockets.connect(uri) as websocket:
            print("Connected! Waiting for calibration/shots...")
            for _ in range(MAX_MESSAGES_PER_URI):
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=MESSAGE_TIMEOUT_SECONDS)
                except asyncio.TimeoutError:
                    print(f"No messages received from {uri} within {MESSAGE_TIMEOUT_SECONDS}s.")
                    break

                data = json.loads(message)
                status = data.get("status")
                if status:
                    details = [f"[Status] {status}"]
                    if "confidence" in data:
                        details.append(f"confidence={data['confidence']}")
                    if data.get("reason"):
                        details.append(f"reason={data['reason']}")
                    if data.get("bbox"):
                        details.append(f"bbox={data['bbox']}")
                    if data.get("elapsed_seconds") is not None:
                        details.append(f"elapsed_seconds={data['elapsed_seconds']}")
                    print(" ".join(details))
                    continue

                if data.get("event") == "shot":
                    print(
                        "[Shot] x={x} y={y} raw=({raw_x},{raw_y}) color={color} confidence={confidence}".format(
                            x=data.get("x"),
                            y=data.get("y"),
                            raw_x=data.get("raw_x"),
                            raw_y=data.get("raw_y"),
                            color=data.get("color"),
                            confidence=data.get("confidence"),
                        )
                    )
                else:
                    print(f"[Data Received]: {data}")
    except Exception as exc:
        print(f"Connection error for {uri}: {exc}")


async def monitor_shots(uris):
    for uri in uris:
        await monitor_uri(uri)


def parse_args():
    parser = argparse.ArgumentParser(description="Smoke-test the ShootOFF websocket API.")
    parser.add_argument(
        "--uri",
        action="append",
        dest="uris",
        help="WebSocket URI to monitor. Can be passed multiple times.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    uris = tuple(args.uris) if args.uris else DEFAULT_URIS
    asyncio.run(monitor_shots(uris))
