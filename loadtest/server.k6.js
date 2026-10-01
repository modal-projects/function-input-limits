// Load test for server/ with k6, as a check that the Python client is not the bottleneck.
//   k6 run -e URL=https://...modal.direct -e VUS=8000 loadtest/server.k6.js
// Each virtual user loops like one concurrent call: POST a 1-10 s task, wait, repeat.
import http from "k6/http";
import { Counter, Trend } from "k6/metrics";

const VUS = Number(__ENV.VUS || 2000);
const WARMUP_S = Number(__ENV.WARMUP ?? 20);

export const options = {
  discardResponseBodies: false,
  scenarios: {
    // Start users over RAMP seconds (0 = all at once), then hold for the rest of the run.
    closed: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: `${Number(__ENV.RAMP || 10)}s`, target: VUS },
        { duration: `${120 - Number(__ENV.RAMP || 10)}s`, target: VUS },
      ],
    },
  },
  summaryTrendStats: ["p(50)", "p(90)", "p(99)", "max"],
  // Always-true thresholds, so the summary breaks failures down by status (0 = no HTTP response).
  thresholds: Object.fromEntries(["0", "429", "502", "503", "504"].map((s) => [`failed{status:${s}}`, ["count>=0"]])),
};

const overhead = new Trend("overhead_s");
const completed = new Counter("completed_after_warmup");
const failed = new Counter("failed");
const start = Date.now();

export default function () {
  const seconds = 1 + Math.random() * 9;
  const t0 = Date.now();
  const res = http.post(`${__ENV.URL}/work`, JSON.stringify({ seconds }), {
    headers: { "Content-Type": "application/json" },
    timeout: "60s",
  });
  if (res.status !== 200) {
    failed.add(1, { status: String(res.status) });
    if (res.status === 0 && Math.random() < 0.01) console.warn(res.error);
    return;
  }
  if ((t0 - start) / 1000 > WARMUP_S) {
    completed.add(1);
    overhead.add((Date.now() - t0) / 1000 - seconds);
  }
}
