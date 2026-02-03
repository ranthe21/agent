import requests
from typing import Dict, Union

from shared_lib.logger import log


def get_public_ip(extra: bool = False) -> Union[str, Dict[str, str]]:
    """Fetches the public IP and optionally country info from multiple providers."""
    providers = [
        {"url": "http://ip-api.com/json", "ip_key": "query", "country_key": "country"},
        {
            "url": "https://reallyfreegeoip.org/json/",
            "ip_key": "ip",
            "country_key": "country_name",
        },
        {"url": "https://ipinfo.io/json", "ip_key": "ip", "country_key": "country"},
    ]

    for provider in providers:
        try:
            response = requests.get(provider["url"], timeout=5)
            if response.status_code == 200:
                data = response.json()
                ip = data.get(provider["ip_key"])
                if not ip:
                    continue

                log.debug(
                    "Public IP retrieved",
                    hypothesisId="NET",
                    provider=provider["url"],
                    ip=ip,
                )

                if extra:
                    return {
                        "ip": ip,
                        "country": data.get(provider["country_key"], "Unknown"),
                    }
                return ip
        except Exception as e:
            log.debug(
                "Provider failed",
                hypothesisId="NET",
                provider=provider["url"],
                error=str(e),
            )
            continue

    log.debug("All IP providers failed", hypothesisId="NET")
    if extra:
        return {"ip": "Unknown", "country": "Unknown"}
    return "Unknown"
