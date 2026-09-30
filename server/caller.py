# One client: 1,000 concurrent HTTP requests to the Server.
#   python server/caller.py
import asyncio
import random
import time

import aiohttp
import modal

url = modal.Server.from_name("demo-server", "WorkerServer").get_url()


async def call(session: aiohttp.ClientSession, seconds: float) -> float:
    for attempt in range(5):
        async with session.post("/work", json={"seconds": seconds}) as r:
            if r.status != 503:  # 503 means no container was ready; retry it
                r.raise_for_status()
                return (await r.json())["seconds"]
        await asyncio.sleep(0.2 * 2**attempt)
    raise RuntimeError("503 after 5 attempts")


async def main():
    tasks = [random.uniform(1, 10) for _ in range(1000)]
    connector = aiohttp.TCPConnector(limit=1000)
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(base_url=url, connector=connector, timeout=timeout) as session:
        t0 = time.monotonic()
        results = await asyncio.gather(*(call(session, s) for s in tasks))
    print(f"{len(results)} calls in {time.monotonic() - t0:.1f}s")


asyncio.run(main())
