# One client: 1,000 concurrent calls to this client's own copy of the app.
#   CLIENT_IDX=3 python copies/caller.py
import asyncio
import os
import random
import time

import modal

idx = int(os.environ.get("CLIENT_IDX", "0"))
worker = modal.Cls.from_name(f"demo-copy-{idx}", "Worker")()


async def main():
    tasks = [random.uniform(1, 10) for _ in range(1000)]
    t0 = time.monotonic()
    results = await asyncio.gather(*(worker.work.remote.aio(s) for s in tasks))
    print(f"{len(results)} calls in {time.monotonic() - t0:.1f}s")


asyncio.run(main())
