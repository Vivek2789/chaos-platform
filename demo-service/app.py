from flask import Flask
import random
import time
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST


LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["endpoint"],
   buckets=[0.01, 0.025, 0.05, 0.1, 0.15, 0.18, 0.2, 0.25, 0.3, 0.4, 0.8, 1.6, 3.2]
)

REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["endpoint", "status"],
)

app = Flask(__name__)


@app.route("/hello")
def hello():

    start_time = time.perf_counter()
    status = 200
    body = "hello world"
    
    REQUESTS.labels(endpoint="/hello", status=str(status)).inc()
    duration = time.perf_counter() - start_time
    LATENCY.labels(endpoint="/hello").observe(duration)
    return body, status 

@app.route("/work")
def work():
    delay = random.uniform(0.1, 0.2)
    start_time = time.perf_counter()
    time.sleep(delay)

    if random.random() < 0.05:
        status = 500
        body = "error"
    else:
        status = 200
        body = "done"

    REQUESTS.labels(endpoint="/work", status=str(status)).inc()
    duration = time.perf_counter() - start_time
    LATENCY.labels(endpoint="/work").observe(duration)
    return body, status 

@app.route("/metrics")
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)