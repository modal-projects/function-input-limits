# One client: 1,000 concurrent HTTP requests to the Server.
#   python server/caller.py
import asyncio
import random
import time

import httpx
import modal

url = modal.Server.from_name("demo-server", "WorkerServer").get_url()


async def call(client: httpx.AsyncClient, seconds: float) -> float:
    for attempt in range(5):
        r = await client.post("/work", json={"seconds": seconds})
        if r.status_code != 503:  # 503 means no container was ready; retry it
            r.raise_for_status()
            return r.json()["seconds"]
        await asyncio.sleep(0.2 * 2**attempt)
    raise RuntimeError("503 after 5 attempts")


async def main():
    tasks = [random.uniform(1, 10) for _ in range(1000)]
    limits = httpx.Limits(max_connections=1000)
    async with httpx.AsyncClient(base_url=url, timeout=60, limits=limits) as client:
        t0 = time.monotonic()
        results = await asyncio.gather(*(call(client, s) for s in tasks))
    print(f"{len(results)} calls in {time.monotonic() - t0:.1f}s")


asyncio.run(main())
