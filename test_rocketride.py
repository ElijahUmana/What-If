"""Test RocketRide engine connection and pipeline execution.

Run: PYTHONPATH=. python test_rocketride.py

Requires the RocketRide engine running on ws://localhost:5565.
Start it with: docker run --platform linux/amd64 -p 5565:5565 ghcr.io/rocketride-org/rocketride-engine:latest
"""

import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


async def main():
    from rocketride import RocketRideClient

    uri = os.environ.get("ROCKETRIDE_ENGINE_URI", "ws://localhost:5565")
    key = os.environ.get("ROCKETRIDE_API_KEY", "")

    print(f"Connecting to RocketRide engine at {uri}...")
    client = RocketRideClient(uri=uri)

    try:
        await client.connect(key)
        print("Connected!")
    except Exception as e:
        print(f"FAILED to connect: {e}")
        print("\nMake sure the engine is running:")
        print("  docker run --platform linux/amd64 -p 5565:5565 -e ROCKETRIDE_GEMINI_KEY=$GEMINI_API_KEY -e ROCKETRIDE_GMI_KEY=$GMI_API_KEY ghcr.io/rocketride-org/rocketride-engine:latest")
        sys.exit(1)

    # Test: load the director pipeline
    pipe_path = str(Path(__file__).parent / "pipelines" / "whatif-director.pipe")
    print(f"\nLoading pipeline: {pipe_path}")
    try:
        token = await client.use(filepath=pipe_path)
        print(f"Pipeline loaded, token: {token}")
    except Exception as e:
        print(f"FAILED to load pipeline: {e}")
        await client.disconnect()
        sys.exit(1)

    # Test: send a query
    print("\nSending test query...")
    try:
        result = await client.send(
            token,
            "What if the striker had passed instead of shooting?",
            "query.txt",
            "text/plain",
        )
        print(f"Result: {result}")
    except Exception as e:
        print(f"Query failed: {e}")

    # Check task status
    try:
        status = await client.get_task_status(token)
        print(f"Task status: {status}")
    except Exception as e:
        print(f"Status check failed: {e}")

    await client.disconnect()
    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
