import json
import os
import string
import sys
from time import sleep

import requests

# Add root to sys.path to allow importing shared_lib
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from shared_lib.system import get_identifier
from shared_lib.network import get_public_ip
from shared_lib.xray import register_warp, generate_vmess_link
from shared_lib.config import load_env
from shared_lib.logger import log
from shared_lib.paths import (
    ACME_SH_PATH,
    INBOUNDS_JSON,
    XRAY_ACCESS_LOG,
    XRAY_ERROR_LOG,
)

# Load configuration from env_file
env_config = load_env()
is_debug_enabled = env_config.get("DEBUG", "false").lower() == "true"
log.debug("Loaded env_config", hypothesisId="A", keys=list(env_config.keys()))

config_id = get_identifier()
log.debug("Identifier", hypothesisId="A", id=config_id)

config_uuid = os.popen(f"xray uuid -i {config_id}").read().replace("\n", "").strip()

cf_api_token = env_config.get("CF_API_TOKEN")
cf_zone_id = env_config.get("CF_ZONE_ID")
nginx_path = env_config.get("NGINX_PATH")
xray_inbounds = env_config.get(
    "XRAY_INBOUNDS",
    "vmess-ws-cdn,vless-tcp-tls-direct,vless-hu-tls-direct,vless-hu-tls-cdn,vless-xhttp-quic-direct,vless-xhttp-quic-cdn",
).split(",")

log.debug(
    "CF Config",
    hypothesisId="A",
    has_token=bool(cf_api_token),
    has_zone=bool(cf_zone_id),
)

domain = None
subdomain = None
direct_subdomain = None
cert_public = ""
cert_private = ""
initialized = False

server_ip_raw = get_public_ip()
if isinstance(server_ip_raw, dict):
    server_ip = server_ip_raw["ip"]
else:
    server_ip = str(server_ip_raw) if server_ip_raw else "0.0.0.0"
log.debug("Server IP", hypothesisId="B", ip=server_ip)


def get_domain():
    global domain
    url = f"https://api.cloudflare.com/client/v4/zones/{cf_zone_id}"
    headers = {
        "Authorization": f"Bearer {cf_api_token}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.get(url, headers=headers)
        log.debug(
            "get_domain response",
            hypothesisId="C",
            status=response.status_code,
            body=response.text[:200],
        )
        if response.status_code == 200:
            domain = response.json()["result"]["name"]
            log.info(
                f"The domain name associated with zone ID {cf_zone_id} is: {domain}",
                hypothesisId="C",
            )
        else:
            log.error(
                f"Failed to retrieve domain name. Status code: {response.status_code}",
                hypothesisId="C",
            )
    except Exception as e:
        log.debug("get_domain error", hypothesisId="C", error=str(e))


def create_cf_records():
    log.debug("Starting create_cf_records", hypothesisId="D")

    def dns_record_already_exist(record_name):
        url = f"https://api.cloudflare.com/client/v4/zones/{cf_zone_id}/dns_records?type=A&name={record_name}.{domain}"
        headers = {
            "Authorization": f"Bearer {cf_api_token}",
            "Content-Type": "application/json",
        }
        try:
            response = requests.get(url, headers=headers)
            log.debug(
                f"Check DNS {record_name}",
                hypothesisId="D",
                status=response.status_code,
            )
            if response.status_code == 200:
                dns_records = response.json()["result"]
                return bool(dns_records)
        except Exception as e:
            log.debug(f"Check DNS error {record_name}", hypothesisId="D", error=str(e))
        return None

    def create_dns_record(name, proxied):
        endpoint = (
            f"https://api.cloudflare.com/client/v4/zones/{cf_zone_id}/dns_records"
        )
        if dns_record_already_exist(name):
            return name
        data = {
            "type": "A",
            "name": name,
            "content": server_ip,
            "ttl": 1,
            "proxied": proxied,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cf_api_token}",
        }
        try:
            response = requests.post(endpoint, json=data, headers=headers)
            log.debug(
                "Create DNS result",
                hypothesisId="D",
                name=name,
                status=response.status_code,
                body=response.text[:200],
            )
            if response.status_code == 200:
                return name
        except Exception as e:
            log.debug(f"Create DNS error {name}", hypothesisId="D", error=str(e))
        return None

    server_ip_str = str(server_ip)
    name = get_identifier() + "-" + server_ip_str.replace(".", "")
    res1 = create_dns_record(name + "-direct", False)
    res2 = create_dns_record(name, True)
    return name if res1 and res2 else None


if cf_api_token and cf_zone_id:
    get_domain()
    if domain:
        a_record = create_cf_records()
        if a_record:
            subdomain = f"{a_record}.{domain}"
            direct_subdomain = f"{a_record}-direct.{domain}"
            log.debug(
                "Subdomains set",
                hypothesisId="E",
                sub=subdomain,
                direct=direct_subdomain,
            )

            ssl_provider = env_config.get("SSL_PROVIDER", "letsencrypt")
            ssl_provider_server = (
                "--server letsencrypt"
                if ssl_provider == "letsencrypt"
                else "--server zerossl"
            )

            # Use string path for acme.sh commands to avoid shell issues
            acme_bin = f"{ACME_SH_PATH}/acme.sh"

            def run_acme(cmd_args):
                full_cmd = (
                    f"CF_Token={cf_api_token} {acme_bin} {cmd_args} --log /dev/null"
                )
                exit_code = os.system(full_cmd)
                if exit_code != 0:
                    log.error(
                        "acme.sh command failed", exit_code=exit_code, cmd=cmd_args
                    )
                    return False
                return True

            cert_path = ACME_SH_PATH / f"{direct_subdomain}_ecc" / "fullchain.cer"
            if cert_path.exists():
                log.debug("Cert exists, renewing", hypothesisId="F")
                run_acme(
                    f"{ssl_provider_server} --renew --dns dns_cf -d {direct_subdomain}"
                )
            else:
                log.debug("Cert missing, issuing", hypothesisId="F")
                if run_acme("--register-account -m my@example.com"):
                    run_acme(
                        f"{ssl_provider_server} --issue --dns dns_cf -d {direct_subdomain}"
                    )

            try:
                with open(cert_path, "r") as file:
                    cert_public = file.read()
                    cert_public = json.dumps(cert_public)[1:-1]
                with open(
                    ACME_SH_PATH
                    / f"{direct_subdomain}_ecc"
                    / f"{direct_subdomain}.key",
                    "r",
                ) as file:
                    cert_private = file.read()
                    cert_private = json.dumps(cert_private)[1:-1]
                log.debug("Certs loaded successfully", hypothesisId="F")
            except Exception as e:
                log.debug("Cert load error", hypothesisId="F", error=str(e))
    else:
        log.debug("Domain not found, skipping records", hypothesisId="C")
    initialized = True
else:
    log.debug("CF tokens missing, skipping setup", hypothesisId="A")
    initialized = True

cf_clean_ip_domain = env_config.get("CF_CLEAN_IP_DOMAIN", "npmjs.com")

with open(INBOUNDS_JSON) as f:
    inbound_template = string.Template(f.read())
    all_inbounds = json.loads(
        inbound_template.substitute(
            {
                "config_id": config_id,
                "config_uuid": config_uuid,
                "cf_clean_ip_domain": cf_clean_ip_domain,
                "nginx_path": nginx_path,
                "server_ip": server_ip,
                "direct_subdomain": direct_subdomain,
                "subdomain": subdomain,
                "cert_public": cert_public,
                "cert_private": cert_private,
            }
        )
    )
    configured_inbounds = [
        inbound for inbound in all_inbounds if inbound.get("name") in xray_inbounds
    ]
    for inbound in configured_inbounds:
        if isinstance(inbound.get("link"), dict):
            inbound["link"] = generate_vmess_link(inbound["link"])


def get_config_links():
    configs = []
    if subdomain:
        configs.extend(
            [
                inbound.get("link", "")
                for inbound in configured_inbounds
                if inbound.get("cloudflare", False)
            ]
        )
        configs.extend(
            [
                inbound.get("link", "")
                for inbound in configured_inbounds
                if inbound.get("cloudflare", False) is False
            ]
        )
    return configs


inbounds = [
    {
        "listen": "0.0.0.0",
        "port": 54321,
        "protocol": "dokodemo-door",
        "settings": {"address": "127.0.0.1"},
        "tag": "doko",
    }
]
if cf_api_token and cf_zone_id:
    inbounds.extend(
        [
            inbound["inbound"]
            for inbound in configured_inbounds
            if inbound.get("cloudflare", False) is True and "inbound" in inbound
        ]
    )

inbounds.extend(
    [
        inbound["inbound"]
        for inbound in configured_inbounds
        if inbound.get("cloudflare", False) is False and "inbound" in inbound
    ]
)

xray_config = {
    "log": {
        "access": str(XRAY_ACCESS_LOG),
        "error": str(XRAY_ERROR_LOG),
        "loglevel": "debug" if is_debug_enabled else "warning",
        "dnsLog": is_debug_enabled,
    },
    "routing": {
        "domainStrategy": "AsIs",
        "rules": [
            {"inboundTag": ["doko"], "outboundTag": "api"},
            {
                "outboundTag": "blocked",
                "ip": [
                    "geoip:private",
                    "ext:geoip_IR.dat:ir",
                    "ext:geoip_IR.dat:phishing",
                    "ext:geoip_IR.dat:malware",
                ],
            },
            {"outboundTag": "blocked", "protocol": ["bittorrent"]},
            {
                "outboundTag": "blocked",
                "domain": [
                    "geosite:private",
                    "regexp:.*\\.ir$",
                    "regexp:.*\\.xn--mgba3a4f16a$",
                    "ext:geosite_IR.dat:ir",
                    "ext:geosite_IR.dat:category-ads-all",
                    "ext:geosite_IR.dat:malware",
                    "ext:geosite_IR.dat:phishing",
                    "ext:geosite_IR.dat:cryptominers",
                ],
            },
        ],
    },
    "dns": None,
    "inbounds": inbounds,
    "outbounds": [],
    "transport": None,
    "policy": {
        "levels": {"0": {"statsUserDownlink": True, "statsUserUplink": True}},
        "system": {"statsInboundDownlink": True, "statsInboundUplink": True},
    },
    "api": {
        "tag": "api",
        "services": ["HandlerService", "LoggerService", "StatsService"],
    },
    "stats": {},
    "reverse": None,
    "fakeDns": None,
}

CUSTOM_DNS = env_config.get("CUSTOM_DNS", "default")
if CUSTOM_DNS != "default":
    dns_server = None
    if CUSTOM_DNS == "cf":
        dns_server = "https+local://security.cloudflare-dns.com/dns-query"
    elif CUSTOM_DNS == "controld":
        dns_server = "https+local://freedns.controld.com/no-ads-dating-drugs-gambling-malware-typo"
    elif CUSTOM_DNS.startswith("https+local://") or CUSTOM_DNS.startswith(
        "quic+local://"
    ):
        dns_server = CUSTOM_DNS
    if dns_server:
        xray_config["dns"] = {"servers": [dns_server], "queryStrategy": "UseIPv4"}

warps_ready = False
wg_configs = {}
if env_config.get("XRAY_OUTBOUND") == "warp":
    warps = []
    warps.append(register_warp())
    sleep(2)
    warps.append(register_warp())
    sleep(2)
    warps.append(register_warp())
    warps_ready = True

    # Generate WireGuard config content for each interface
    for i, warp in enumerate(warps):
        addresses = ", ".join(warp["addresses"]) if warp.get("addresses") else ""
        wg_configs[f"wg{i}"] = f"""[Interface]
PrivateKey = {warp["privatekey"]}
Address = {addresses}
DNS = 1.1.1.1
MTU = 1280
Table = off

[Peer]
PublicKey = {warp["pubkey"]}
AllowedIPs = 0.0.0.0/0
Endpoint = engage.cloudflareclient.com:2408
"""

    # add new routing rules at the beginning of the rules list
    xray_config["routing"]["rules"].insert(
        0,
        {
            "inboundTag": [
                "vmess-ws-cdn",
                "vless-tcp-tls-direct",
                "vless-hu-tls-direct",
                "vless-hu-tls-cdn",
                "vless-xhttp-quic-direct",
                "vless-xhttp-quic-cdn",
            ],
            "balancerTag": "balancer1",
        },
    )

    # add warp balancer object
    xray_config["routing"]["domainStrategy"] = "IPOnDemand"
    xray_config["routing"]["balancers"] = [
        {
            "tag": "balancer1",
            "selector": ["warp0", "warp1", "warp2"],
            "strategy": {"type": "roundRobin"},
        }
    ]

    # define warp outbounds
    for i, warp in enumerate(warps):
        xray_config["outbounds"].append(
            {
                "tag": f"warp{i}",
                "protocol": "freedom",
                "settings": {"domainStrategy": "UseIPv4"},
                "streamSettings": {
                    "sockopt": {"tcpFastOpen": True, "interface": f"wg{i}"}
                },
            }
        )

    # ensure direct is after warp outbounds
    xray_config["outbounds"].append(
        {
            "tag": "direct",
            "protocol": "freedom",
            "settings": {"domainStrategy": "UseIPv4"},
        }
    )
else:
    # If warp is not enabled, add direct outbound here
    xray_config["outbounds"].append(
        {
            "tag": "direct",
            "protocol": "freedom",
            "settings": {"domainStrategy": "UseIPv4"},
        }
    )

xray_config["outbounds"] += [
    {"tag": "blocked", "protocol": "blackhole", "settings": {}}
]
