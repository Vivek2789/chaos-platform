# Chaos Testing Platform

A learning project: run controlled failure experiments against a demo service and measure how the system behaves and recovers.

**Engineering problems:** safe failure injection, experiment scheduling, recovery measurement, service-level objectives (SLOs), and observability.

**Stack:** Python (Flask), Docker, Docker Compose, Prometheus, Grafana

**Reference:** [litmuschaos/litmus](https://github.com/litmuschaos/litmus)

---

## Architecture

```
┌──────────────┐   requests    ┌──────────────┐
│ Load         │ ────────────► │ demo-service │ ◄── chaos controller
│ generator    │               │  /hello      │     (kills container,
└──────────────┘               │  /work       │      injects latency)
                               │  /metrics    │
                               └──────┬───────┘
                                      │ scrape every 5s
                               ┌──────▼───────┐       ┌──────────┐
                               │  Prometheus  │ ────► │ Grafana  │
                               └──────────────┘       └──────────┘
```

**The experiment loop:** measure baseline → inject fault → observe → remove fault → measure recovery → compare against the SLO.

---

## Progress

| Milestone | What it builds | Status |
|---|---|---|
| 1 | Demo service that reports its own metrics | ✅ Done |
| 2 | Dockerfile + Docker Compose with Prometheus | ✅ Done |
| 3 | Load generator + Grafana dashboard | 🟡 Next |
| 4 | First fault: kill the container | ⬜ |
| 5 | Second fault: latency injection (Toxiproxy) | ⬜ |
| 6 | Platform: YAML experiments, auto-abort, reports | ⬜ |

---

## Project structure

```
chaos-platform/
├── demo-service/
│   ├── app.py              # Flask app with /hello, /work, /metrics
│   ├── Dockerfile          # recipe for the app image
│   └── requirements.txt    # Python dependencies
├── prometheus/
│   └── prometheus.yml      # what to scrape, how often
├── docker-compose.yml      # runs all services together
└── .gitignore
```

## How to run

```bash
docker compose up --build
```

| URL | What it is |
|---|---|
| http://localhost:8080/hello | fast endpoint, always succeeds |
| http://localhost:8080/work | 0.1–0.2s random delay, fails ~5% of the time |
| http://localhost:8080/metrics | raw metrics in Prometheus format |
| http://localhost:9090 | Prometheus UI (Status → Targets, Query) |

Generate traffic:

```bash
for i in {1..100}; do curl -s -o /dev/null localhost:8080/work; done
```

Measure latency and status from the client side:

```bash
for i in {1..100}; do curl -s -o /dev/null -w "%{http_code} %{time_total}\n" localhost:8080/work; done | sort
```

---

## What I learned

### Milestone 1: Metrics

**Metrics.** A service keeps running numbers about itself and shows them on `/metrics`. Prometheus visits that page on a schedule (**scraping**) and stores each value with a timestamp, building a history.

**Counter.** A number that only goes up, like an odometer. What matters is how fast it grows, not the total.

**Labels.** Split one metric into categories, e.g. `{endpoint="/work", status="500"}`. Each unique label combination is a separate time series.
- **High cardinality** is dangerous: never use labels with unbounded values (like `user_id`).
- Labels must be strings: `status=str(status)`.
- A label combination only appears on `/metrics` after it is used once.

**Histogram.** Records durations into **buckets** instead of storing every value, so percentiles can be estimated cheaply.
- Buckets are **cumulative**: each counts everything *at or below* its mark (`le` = "less than or equal"). Find a slice by subtracting neighbors.
- `_count` = number of observations, `_sum` = total time, `+Inf` bucket = everything (added automatically).
- Custom `buckets=[...]` **replace** the defaults entirely.
- **Design buckets for your questions:** marks close together in the normal range, roughly doubling above it to see slowdowns. If every request lands in one bucket, the ruler is too blurry to measure anything.

My buckets: `[0.01, 0.025, 0.05, 0.1, 0.15, 0.18, 0.2, 0.25, 0.3, 0.4, 0.8, 1.6, 3.2]`
(`0.25` added for accurate p99 near the normal range; `0.3` added at the SLO threshold. See Milestone 2.)

**Averages hide pain.** 99 requests at 0.1s + 1 at 10s averages 0.199s, which looks healthy while one user waited 10 seconds. Use **percentiles (p95/p99)** instead.

**SLO (Service Level Objective).** A latency target paired with a percentile, e.g. "99% of `/work` requests finish under 300ms." Base it on normal behavior. Chaos experiments check whether the SLO held during a fault.

**Count every request, including failures.** If the counter only runs on the success path, an outage shows 0 requests and 0 errors, and the dashboard looks calm while everything is broken. Bad monitoring is worse than none.

**Single exit point.** Decide `status` once, then count, record latency, and return in one place. Writing the status code twice (label and response) lets them silently drift apart.

**Fail-fast vs. fail-slow.**
- Fail-fast (instant crash/rejection): error rate rises, latency stays normal.
- Fail-slow (timeouts): error rate **and** latency rise. Slow failures tie up workers and can cause **cascading failures**.

**Where you measure matters.** The in-app histogram measures time inside the function (server side). curl measures the full trip (client side). Latency injected in the network won't show up in the app's own histogram.

**`time.sleep()` is a minimum, not exact.** The OS scheduler adds small delays (jitter), which is why some 0.1–0.2s requests measured just over 0.2s.

**Randomness needs volume.** A 5% failure chance gives 3–7 errors per 100 requests; more requests bring it closer to 5% (law of large numbers). Chaos tests need steady load so signals aren't lost in noise.

### Milestone 2: Docker, Compose, Prometheus

**Image vs. container.** An image is a packaged, read-only template (app + Python + packages). A container is a running instance of it.

**Dockerfile instructions.**

| Instruction | Meaning |
|---|---|
| `FROM python:3.13-slim` | start from an image that already has Python |
| `WORKDIR /app` | working folder inside the image |
| `COPY <from> <to>` | copy files from the build context into the image |
| `RUN ...` | runs **once, at build time** (e.g. `pip install`) |
| `EXPOSE 8080` | documents the port (doesn't open it) |
| `CMD [...]` | runs **every time a container starts** |

**Layer caching.** Docker reuses unchanged layers and rebuilds from the first changed one. Put rarely changing steps (installing requirements) **before** frequently changing ones (copying `app.py`).

**Copy only what you need.** `COPY app.py .` instead of `COPY . .` keeps secrets like `.env` out of images. Trade-off: new files need their own `COPY` line (or the container fails with `ModuleNotFoundError`). `.dockerignore` only works in the build context root.

**Port mapping.** `-p 9000:8080` means `<Mac port>:<container port>`.

**`0.0.0.0` vs `127.0.0.1`.** Each container has its own private `localhost`.
- Listening on `127.0.0.1` inside a container rejects traffic forwarded from the Mac (`Connection reset by peer`).
- Listening on `0.0.0.0` accepts connections on every network interface.
- As a *destination*, `0.0.0.0` and `localhost` both mean "myself." The server says where it listens; the client says who it calls.

**404 vs. connection error.** A 404 means the server answered (code problem). Connection refused/reset means the server was never reached (networking problem).

**Docker Compose.** Describes the whole system in one file. Services on the same Compose network reach each other **by service name** via Docker's built-in DNS (`demo-service:8080`).
- `ports:` is only for traffic from the Mac into a container. Container-to-container traffic doesn't need it.
- Service names should use lowercase letters, numbers, and hyphens.
- Avoid `:latest` in real projects; pin versions so builds are reproducible.

**Volumes.** Link a file from the Mac into a container at run time (no rebuild needed to change it), unlike `COPY` which bakes it in at build time.
- ⚠️ If the host path doesn't exist, Docker creates an **empty directory** with that name. Error: "Are you trying to mount a directory onto a file?" Check filenames character by character (`.yml` ≠ `.yaml`).

**Prometheus config.**
```yaml
global:
  scrape_interval: 5s
scrape_configs:
  - job_name: demo-service
    static_configs:
      - targets: ["demo-service:8080"]
```
- Prometheus adds `/metrics` automatically, plus `job` and `instance` labels to every metric.
- **Scrape interval trade-off:** an outage shorter than the interval can fall between scrapes and be missed. Shorter intervals cost more requests and storage. Restarts still leave evidence (counter resets, `process_start_time_seconds`, client-side errors), so use several signals.

**PromQL basics.**

| Query | Meaning |
|---|---|
| `up` | 1 if the last scrape succeeded, 0 if it failed |
| `http_requests_total` | raw counter (only climbs; hard to read changes) |
| `rate(http_requests_total[1m])` | requests per second, averaged over the last minute |
| `sum(rate(http_requests_total{status="500"}[1m])) / sum(rate(http_requests_total[1m]))` | error rate (fraction 0–1) |

- `rate()` turns an odometer into a speedometer.
- **Range rule of thumb:** at least **4× the scrape interval** (5s → `[20s]`+). Too short = noisy, with gaps; too long = slow to react and can hide short outages.
- `rate()` treats any counter decrease as a **reset** and compensates, which is why counters must only go up.

**p99 latency query.**
```
histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket{endpoint="/work"}[1m])))
```
Read it from the inside out:
1. bucket counters for `/work`
2. `rate()` so only recent requests count
3. `sum by (le)` merges extra labels (like `instance`) but keeps buckets separate
4. `histogram_quantile(0.99, ...)` estimates the value 99% of requests are below (`0.5` = median)

### Percentiles, buckets, and SLOs in practice

**p99 is measured, not set.** Three separate things:

| | What it is | Where it lives |
|---|---|---|
| 0.1–0.2s delay | how the app behaves | `app.py` |
| Buckets | how finely we measure | `app.py` (`Histogram`) |
| p99 ≈ 0.2s | the measured result | PromQL query |
| p99 < 0.3s | the target (SLO) | experiment definitions (Milestone 6) |

Thermometer analogy: actual temperature, the markings, the reading, and "I want it below 30 degrees."

**Coarse buckets inflate percentiles.** `histogram_quantile` assumes requests are spread **evenly inside a bucket**. With marks at 0.2 and 0.4, the ~4% of requests just over 0.2s (really ~0.205s) were treated as spread across 0.2–0.4, so p99 showed **~0.35s**. Adding a `0.25` mark dropped it to **~0.20–0.25s**, close to reality. Same app, same traffic; only the ruler changed.

**Put a bucket mark exactly at each SLO threshold.** Without a `0.3` mark, a p99 inside 0.25–0.4 can't be reliably judged above or below 0.3. With it, the SLO becomes an exact **count** instead of an estimate:
```
rate(http_request_duration_seconds_bucket{le="0.3"}[1m])
/
rate(http_request_duration_seconds_count[1m])
```
If this is ≥ 0.99, the SLO holds.

**Changing buckets on a running system** causes a short messy period: right after a restart, the query window mixes old and new bucket layouts, and Prometheus warns that it fixed the input "for monotonicity." It clears after one window length. Change buckets rarely and deliberately.

### Reading graphs

- **Prometheus UI shows UTC** by default (New York is 4 hours behind during daylight saving time).
- **"No data" is not zero.** With no traffic, error rate is 0 ÷ 0 and p99 has nothing to measure. Stacked mode draws these gaps along the bottom; Unstacked shows them more honestly.
- **Warm-up:** a `rate(...[1m])` graph needs about a minute of steady traffic before it settles near the true value.
- **Edge spikes:** when traffic stops, the window empties, so a few errors weigh heavily (my error rate jumped to 0.08 at the end of a burst).
- **Wiggles** around the true value come from randomness in small samples. My error rate hovered at 0.05–0.065 around the expected 0.05.
- **Bursty traffic makes baselines unreliable.** Chaos experiments need steady load, so a change in the line comes from the fault, not from traffic starting or stopping.

---

## Debugging lessons

- **Code on disk ≠ running process.** Python reads the file once at startup. Edit → save → **restart** → test.
- **Compare predictions to data.** Metrics showed `/hello` failing and taking 0.15s, which exposed copy-pasted logic and a stale running process.
- **Read the end of long error messages first.** The useful line is usually last.

## Dev environment notes (macOS)

- Docker Desktop must be **running** for `docker` to work: the CLI is only the client; the engine runs inside Docker Desktop.
- Personal and work Git identities are separated with `includeIf "gitdir:~/personal/"` in `~/.gitconfig`, and personal pushes use a dedicated SSH key via `core.sshCommand`.
- GitHub identifies you by **which SSH key you present**; a key can belong to only one account.
- Never paste tokens or private keys anywhere. If one leaks, revoke it immediately.

---

## Next steps

- [x] Run the error-rate query and compare with the expected ~5%
- [x] Query p99 latency with `histogram_quantile()`
- [ ] Experiment: remove `demo-service` `ports:` and check whether Prometheus still scrapes it
- [ ] Experiment: set the target to `0.0.0.0:8080` and read the Targets error
- [ ] Milestone 3: load generator as a Compose service (steady traffic)
- [ ] Milestone 3: Grafana dashboard with request rate, error rate, and p99