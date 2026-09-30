# One input carries a list of tasks, run concurrently inside the container.
#   modal deploy batching/app.py
#
# The sleep costs no CPU, so one container can hold many chunks. For CPU-bound work,
# size each chunk to the container's cores and set `max_inputs=1`, so one chunk fills
# one container.
import asyncio

import modal

app = modal.App("demo-batch")


@app.cls(min_containers=1, max_containers=16)
@modal.concurrent(max_inputs=50)
class Worker:
    @modal.method()
    async def work_many(self, seconds: list[float]) -> list[float]:
        async def one(s: float) -> float:
            await asyncio.sleep(s)  # stands in for 1-10 s of real work
            return s

        return list(await asyncio.gather(*(one(s) for s in seconds)))
