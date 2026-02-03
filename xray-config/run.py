import json
import os
import threading
import time
import sys
from flask import Flask, abort

# Add root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from config import config
from shared_lib.system import exec_command, get_machine_id, csv_to_dict
from shared_lib.logger import log
from shared_lib.network import get_public_ip
from shared_lib.xray import parse_config_link
from shared_lib.paths import CONFIGS_CSV, VALID_CSV, ACME_SH_PATH


class XrayService:
    def __init__(self):
        self.app = Flask(__name__)
        self.valid_configs = {}
        self.latest_metrics = ""
        self.instance_location_info = None
        self._setup_routes()

    def _setup_routes(self):
        @self.app.route("/config")
        def get_xray_config():
            return json.dumps(config.xray_config, indent=4)

        @self.app.route("/valid-configs")
        def valid_configs_route():
            return json.dumps(self.valid_configs, indent=4)

        @self.app.route("/subdomain")
        def export_certs():
            if not config.direct_subdomain:
                return "Not Ready", 503
            return config.direct_subdomain

        @self.app.route("/warps")
        def get_warps():
            if not config.warps_ready:
                abort(404)
            return json.dumps(config.warps, indent=4)

        @self.app.route("/wg-configs")
        def get_wg_configs():
            if not config.warps_ready:
                abort(404)
            return json.dumps(config.wg_configs, indent=4)

        @self.app.route("/metrics")
        def metrics():
            return self.latest_metrics

    def update_metrics(self, configs):
        if not self.instance_location_info:
            self.instance_location_info = get_public_ip(extra=True)

        if isinstance(self.instance_location_info, dict):
            instance_ip = self.instance_location_info.get("ip", "Unknown")
            instance_country = self.instance_location_info.get("country", "Unknown")
        else:
            instance_ip = (
                str(self.instance_location_info)
                if self.instance_location_info
                else "Unknown"
            )
            instance_country = "Unknown"

        metrics = []
        total_count = len(configs.values())
        failed_count = 0
        for config_link, value in configs.items():
            try:
                status = value[1]
                delay = value[5]

                config_info = parse_config_link(config_link)
                labels = [
                    f'config_link="{config_link}"',
                    f'machine_id="{get_machine_id()}"',
                    f'ip="{instance_ip}"',
                    f'country="{instance_country}"',
                    f'config_protocol="{config_info["protocol"]}"',
                    f'config_host="{config_info["host"]}"',
                    f'config_port="{config_info["port"]}"',
                    f'config_security="{config_info["security"]}"',
                    f'config_type="{config_info["type"]}"',
                ]
                inline_labels = ",".join(labels)
                t = f"vpn_config{{{inline_labels}}}"

                if status == "passed":
                    t += f" {delay}"
                else:
                    failed_count += 1
                    t += " -1"
                metrics.append(t)
            except Exception as e:
                log.error(
                    f"Error processing config link {config_link}: {e}",
                    hypothesisId="METRIC",
                )
                continue

        self.latest_metrics = (
            "# HELP vpn_config vpn config up(working) or down(not working).\n"
            "# TYPE vpn_config gauge\n" + "\n".join(metrics) + "\n"
        )

        if failed_count == total_count and total_count > 0:
            return False
        return True

    def background_job(self):
        log.info("start bg job", hypothesisId="BG")

        while True:
            if not config.initialized:
                time.sleep(5)
                continue

            config_links = config.get_config_links()
            if not config_links:
                log.info("No config links found, waiting...", hypothesisId="BG")
                time.sleep(60)
                continue

            valid_links = [
                link
                for link in config_links
                if link.startswith(("vmess://", "vless://"))
            ]

            if not valid_links:
                log.info(
                    "No valid vmess/vless links found, waiting...", hypothesisId="BG"
                )
                time.sleep(60)
                continue

            with open(CONFIGS_CSV, "w") as configs_csv:
                configs_csv.write("\n".join(valid_links))

            exec_command(["cat", str(CONFIGS_CSV)])

            log.info("start xray testing...", hypothesisId="BG")
            exec_command(
                [
                    "xray-knife",
                    "net",
                    "http",
                    "--thread",
                    "1",
                    "-d",
                    "30000",
                    "-r",
                    "-e",
                    "-p",
                    "-a",
                    "1000",
                    "-f",
                    str(CONFIGS_CSV),
                    "--type",
                    "csv",
                ]
            )

            self.valid_configs = csv_to_dict(str(VALID_CSV))
            log.debug(
                "Valid configs from CSV",
                hypothesisId="TEST",
                count=len(self.valid_configs),
                keys=list(self.valid_configs.keys()),
            )

            success = True
            if self.valid_configs:
                success = self.update_metrics(self.valid_configs)
            else:
                log.info(
                    "No valid configurations found after testing.", hypothesisId="BG"
                )
                success = False

            log.info(f"xray test done - success: {success}", hypothesisId="BG")

            if success:
                time.sleep(300)
            else:
                time.sleep(15)

    def cert_management_job(self):
        while True:
            if not config.initialized:
                time.sleep(5)
                continue

            if config.cf_api_token and config.direct_subdomain:
                exec_command(
                    [
                        str(ACME_SH_PATH / "acme.sh"),
                        "--renew",
                        "--dns",
                        "dns_cf",
                        "-d",
                        config.direct_subdomain,
                    ],
                    env={"CF_Token": config.cf_api_token or ""},
                )
                time.sleep(86400 * 30)
            else:
                time.sleep(60)

    def run(self):
        config.initialize()

        thread = threading.Thread(target=self.background_job)
        thread.daemon = True
        thread.start()

        cert_thread = threading.Thread(target=self.cert_management_job)
        cert_thread.daemon = True
        cert_thread.start()

        self.app.run(host="0.0.0.0", port=5000, debug=False)


if __name__ == "__main__":
    service = XrayService()
    service.run()
