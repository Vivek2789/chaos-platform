import os
import requests 
import time
from datetime import datetime

TARGET_URL = os.environ.get("TARGET_URL", "http://demo-service:8080/work")
RATE = float(os.environ.get("RATE", "10"))

while True:
    request_start_time = time.perf_counter()
    now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    try:
        response = requests.get(TARGET_URL, timeout=2)
        print(f"[{now}] Status Code: {response.status_code}", flush=True)
    except requests.exceptions.RequestException as e:
       print(f"{now} ERROR {type(e).__name__}", flush=True)
    duration = time.perf_counter() - request_start_time
    if duration < 1.0 / RATE:
        time.sleep(1.0 / RATE - duration)
