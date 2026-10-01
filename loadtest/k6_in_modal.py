# Run the k6 Server load test from a Modal container, so the load generator sits next to the proxy.
#   modal run loadtest/k6_in_modal.py --vus 8000 --ramp 0
import subprocess
from pathlib import Path

import modal

image = modal.Image.debian_slim().dockerfile_commands(["COPY --from=grafana/k6:latest /usr/bin/k6 /usr/bin/k6"])
app = modal.App("demo-k6", image=image)
script = Path(__file__).with_name("server.k6.js")


@app.function(cpu=8, memory=8192, timeout=600, region="us-east")
def k6(js: str, url: str, vus: int, ramp: int, warmup: int) -> str:
    Path("/tmp/server.k6.js").write_text(js)
    env = [f"URL={url}", f"VUS={vus}", f"RAMP={ramp}", f"WARMUP={warmup}"]
    cmd = ["k6", "run", "-q", *[a for e in env for a in ("-e", e)], "/tmp/server.k6.js"]
    return subprocess.run(cmd, capture_output=True, text=True).stdout


@app.local_entrypoint()
def main(vus: int = 8000, ramp: int = 0, warmup: int = 0):
    url = modal.Server.from_name("demo-server", "WorkerServer").get_url()
    print(k6.remote(script.read_text(), url, vus, ramp, warmup))
