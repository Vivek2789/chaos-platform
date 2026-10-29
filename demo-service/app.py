from flask import Flask
import random
import time
from prometheus_client import Counter

REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["endpoint", "status"],
)

app = Flask(__name__)


@app.route("/hello")
def hello():
    return "hello"

@app.route("/work")
def work():
    delay = random.uniform(0.1,0.2)
    time.sleep(delay)
    if random.random() < 0.05:
        REQUESTS.labels(endpoint="/work", status="500").inc()
        return "error", 500
    REQUESTS.labels(endpoint="/work", status="200").inc()
    return "done"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)