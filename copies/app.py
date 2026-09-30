# Deploy one copy per client; each copy's Function has its own input limits.
#   for i in 0 1 2 3 4 5 6 7; do modal deploy --name demo-copy-$i copies/app.py; done
import asyncio

import modal

app = modal.App("demo-copy")


@app.cls(min_containers=1, max_containers=16)
@modal.concurrent(max_inputs=500)
class Worker:
    @modal.method()
    async def work(self, seconds: float) -> float:
        await asyncio.sleep(seconds)  # stands in for 1-10 s of real work
        return seconds
