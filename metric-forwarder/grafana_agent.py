import os
import sys
from common import generate_config

# Add root to sys.path to allow importing shared_lib
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from shared_lib.system import exec_command
from shared_lib.logger import log


def start():
    generate_config()
    exec_command(["cat", "config.yaml"], capture_output=True)
    log.info("running grafana-agent", hypothesisId="GRAFANA")
    exec_command(["grafana-agent", "--config.file=config.yaml"])
