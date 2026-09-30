# One client: 1,000 concurrent calls using async invocation (spawn, then get).
# Async inputs have a higher rate limit and a larger queue than `.remote()` inputs.
#   python spawn/caller.py
import asyncio
import random
import time

import modal

worker = modal.Cls.from_name("demo-spawn", "Worker")()


async def call(seconds: float) -> float:
    fc = await worker.work.spawn.aio(seconds)
    return await fc.get.aio()


async def main():
    tasks = [random.uniform(1, 10) for _ in range(1000)]
    t0 = time.monotonic()
    results = await asyncio.gather(*(call(s) for s in tasks))
    print(f"{len(results)} calls in {time.monotonic() - t0:.1f}s")


asyncio.run(main())
