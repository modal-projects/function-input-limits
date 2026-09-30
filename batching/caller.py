# One client: 1,000 tasks sent as chunks of 32, so 32 inputs instead of 1,000.
#   python batching/caller.py
import asyncio
import random
import time

import modal

worker = modal.Cls.from_name("demo-batch", "Worker")()


async def main():
    tasks = [random.uniform(1, 10) for _ in range(1000)]
    chunks = [tasks[i : i + 32] for i in range(0, len(tasks), 32)]
    t0 = time.monotonic()
    results = await asyncio.gather(*(worker.work_many.remote.aio(c) for c in chunks))
    print(f"{sum(map(len, results))} tasks in {len(chunks)} calls in {time.monotonic() - t0:.1f}s")


asyncio.run(main())
