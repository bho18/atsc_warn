#!/usr/bin/env python3
"""Generate the ThinkCentre's live Docker config from local routing information.

Uses the Linux routing table only: no tuner query, probe packet or Docker mutation.
Run with Ubuntu's python3; no application venv or third-party dependencies required.
"""

import argparse
import ipaddress
import json
import subprocess
from pathlib import Path

PRIVATE = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def read_ip(*arguments):
    try:
        result = subprocess.run(
            ["ip", "-j", "-4", *arguments], check=True, capture_output=True, text=True, timeout=5
        )
        return json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise ValueError(
            "Cannot read local Linux network settings; install iproute2 or use "
            "--lan-ip with an address actually configured on this host"
        ) from exc


def private_address(value):
    address = ipaddress.IPv4Address(value)
    if not any(address in network for network in PRIVATE):
        raise ValueError(
            "LAN address must be an RFC1918 IPv4 address, not a wildcard/public address"
        )
    return address


def private_network(value):
    network = ipaddress.ip_network(value)
    if network.version != 4 or not any(network.subnet_of(n) for n in PRIVATE):
        raise ValueError("Allowed client networks must be RFC1918 IPv4 subnets")
    return str(network)


def detect_network(receiver, explicit_ip=None):
    interfaces = read_ip("address", "show")
    candidates = []
    for interface in interfaces:
        for address in interface.get("addr_info", []):
            if address.get("family") == "inet":
                candidates.append((address["local"], address["prefixlen"], interface["ifname"]))
    if explicit_ip:
        chosen = str(private_address(explicit_ip))
    else:
        routes = read_ip("route", "get", receiver)
        if len(routes) != 1 or not routes[0].get("prefsrc"):
            raise ValueError("No unambiguous local route; pass --lan-ip")
        chosen = str(private_address(routes[0]["prefsrc"]))
    matches = [(address, prefix, name) for address, prefix, name in candidates if address == chosen]
    if len(matches) != 1:
        raise ValueError("LAN address must identify exactly one configured host interface")
    address, prefix, interface = matches[0]
    if interface.startswith(("docker", "br-", "veth", "lo")):
        raise ValueError("Choose the host LAN interface address, not a Docker/loopback address")
    subnet = private_network(str(ipaddress.ip_network(f"{address}/{prefix}", strict=False)))
    return address, subnet


def render_config(address, networks, receiver, channel, port, udp_port, tuner=None):
    address = str(private_address(address))
    ipaddress.IPv4Address(receiver)
    if not 1 <= port <= 65535 or not 1 <= udp_port <= 65535:
        raise ValueError("Ports must be between 1 and 65535")
    if tuner is not None and not 0 <= tuner < 32:
        raise ValueError("Tuner must be between 0 and 31")
    if not channel or "\n" in channel:
        raise ValueError("Choose a physical RF channel")
    if channel.isdigit():
        channel = "auto:" + channel
    allowed = list(
        dict.fromkeys([f"{address}/32", "127.0.0.1/32", *map(private_network, networks)])
    )
    fields = {
        "database": "/data/warnbridge.db",
        "capture_dir": "/data/captures",
        "bind": address,
        "port": port,
        "timezone": "America/Chicago",
        "web_allowed_networks": allowed,
        "receiver_host": receiver,
        "channel": channel,
        "return_ip": address,
        "udp_bind": address,
        "udp_port": udp_port,
        "record_raw": False,
        "full_multiplex": False,
    }
    if tuner is not None:
        fields["tuner"] = tuner
    return (
        "# Local live Docker configuration; keep out of Git.\n"
        + "\n".join(f"{key} = {json.dumps(value)}" for key, value in fields.items())
        + "\n"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receiver", default="192.168.4.159", help="HDHomeRun IPv4")
    parser.add_argument("--channel", default="7", help="physical RF channel")
    parser.add_argument("--lan-ip", help="explicit host LAN IPv4 instead of route detection")
    parser.add_argument(
        "--allow-network",
        action="append",
        default=[],
        help="additional trusted RFC1918 client CIDR (repeat for routed VLANs)",
    )
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--udp-port", type=int, default=5000)
    parser.add_argument("--tuner", type=int, help="omit for safe idle-tuner selection")
    parser.add_argument("--output", type=Path, default=Path("config/local.docker.toml"))
    args = parser.parse_args()
    try:
        ipaddress.IPv4Address(args.receiver)
        address, subnet = detect_network(args.receiver, args.lan_ip)
        content = render_config(
            address,
            [subnet, *args.allow_network],
            args.receiver,
            args.channel,
            args.port,
            args.udp_port,
            args.tuner,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # Refuse accidental replacement of an installation's existing configuration.
        with args.output.open("x") as stream:
            stream.write(content)
        args.output.chmod(0o644)  # Readable by the unprivileged container UID; no secrets.
    except (ValueError, OSError) as exc:
        parser.exit(2, f"configure_docker: {exc}\n")
    print(f"Wrote {args.output}: web http://{address}:{args.port}, trusted subnet {subnet}.")
    print("Receiver and web share a persistent Docker volume. Raw recording is off.")
    print("Review the config, then run the read-only preflight:")
    print(
        "docker compose -f compose.live.yaml run --rm --no-deps receiver "
        "discover --config /app/config/live.toml"
    )
    print("Start: docker compose -f compose.live.yaml up -d --build")


if __name__ == "__main__":
    main()
