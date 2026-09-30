# Same Function as a plain `.remote()` deployment; only the caller's invocation differs.
#   modal deploy spawn/app.py
import asyncio

import modal

app = modal.App("demo-spawn")


@app.cls(min_containers=1, max_containers=16)
@modal.concurrent(max_inputs=500)
class Worker:
    @modal.method()
    async def work(self, seconds: float) -> float:
        await asyncio.sleep(seconds)  # stands in for 1-10 s of real work
        return seconds
