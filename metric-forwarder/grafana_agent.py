import os
import sys
from common import generate_config

# Add root to sys.path to allow importing shared_lib
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from shared_lib.logger import log


def start():
    generate_config()
    os.system("cat config.yaml")
    log.info("running grafana-agent", hypothesisId="GRAFANA")
    os.system("grafana-agent --config.file=config.yaml")
