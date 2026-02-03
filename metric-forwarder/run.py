import os
import sys
from time import sleep

# Add root to sys.path to allow importing shared_lib
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from shared_lib.logger import log

log.info("initial 30 seconds wait...", hypothesisId="INIT")
# sleep(30)

METRIC_PUSH_METHOD = os.environ.get("METRIC_PUSH_METHOD", "pushgateway")

if METRIC_PUSH_METHOD == "pushgateway":
    from pushgateway import run_jobs

    run_jobs()

else:
    # grafana_agent method
    from grafana_agent import start

    start()

while True:
    log.info("entering endless loop.", hypothesisId="LOOP")
    sleep(1000)
