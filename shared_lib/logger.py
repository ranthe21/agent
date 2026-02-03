import structlog
import logging
import os
from typing import List
from shared_lib.paths import DEBUG_LOG, ENV_FILE

# Setup handlers
handlers: List[logging.Handler] = [logging.StreamHandler()]
if os.path.isfile(str(DEBUG_LOG)):
    handlers.append(logging.FileHandler(str(DEBUG_LOG)))


def _is_debug_enabled():
    """Check if debug is enabled in environment or env_file without circular imports."""
    # 1. Check environment
    if os.environ.get("DEBUG", "").lower() == "true":
        return True

    # 2. Check env_file manually
    if os.path.exists(str(ENV_FILE)):
        try:
            with open(str(ENV_FILE), "r") as f:
                for line in f:
                    if line.strip().startswith("DEBUG="):
                        return line.split("=", 1)[1].strip().lower() == "true"
        except Exception:
            pass
    return False


log_level = logging.DEBUG if _is_debug_enabled() else logging.INFO

# Configure standard logging for both file and stdout
logging.basicConfig(
    level=log_level,
    format="%(message)s",
    handlers=handlers,
)

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
)

log = structlog.get_logger()
