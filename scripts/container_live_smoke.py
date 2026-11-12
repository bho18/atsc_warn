"""Test the live Compose layout with synthetic loopback UDP, never a physical tuner.

Requires a locally built warnbridge:live-local image and the local Docker socket.
Creates/removes only its own uniquely named containers and synthetic test volume.
"""

import http.client
import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from tests.fixtures.golden import heartbeat

ROOT = Path(__file__).resolve().parent.parent


def free_port(kind):
    with socket.socket(socket.AF_INET, kind) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    environment = os.environ.copy()
    for name in (
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_TLS",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
    ):
        environment.pop(name, None)
    project = "warnbridge-live-test-" + uuid4().hex[:10]
    docker = ["docker", "--host=unix:///var/run/docker.sock"]

    def run(arguments, check=True):
        return subprocess.run(
            docker + arguments,
            cwd=ROOT,
            env=environment,
            check=check,
            capture_output=True,
            text=True,
            timeout=90,
        )

    run(["info", "--format", "{{.ServerVersion}}"])
    web_port, udp_port = free_port(socket.SOCK_STREAM), free_port(socket.SOCK_DGRAM)
    with tempfile.TemporaryDirectory(prefix="warnbridge-live-test-") as directory:
        config = Path(directory) / "synthetic.toml"
        config.write_text(
            f'database="/data/warnbridge.db"\ncapture_dir="/data/captures"\n'
            f'bind="127.0.0.1"\nport={web_port}\nudp_bind="127.0.0.1"\n'
            f'udp_port={udp_port}\nweb_allowed_networks=["127.0.0.1/32"]\n'
            "record_raw=false\n"
        )
        config.chmod(0o644)
        override = Path(directory) / "compose-test.json"
        health = {"interval": "1s", "start_period": "1s", "timeout": "3s"}
        override.write_text(
            json.dumps(
                {
                    "services": {
                        "web": {"healthcheck": health},
                        "receiver": {
                            "command": ["udp", "--config", "/app/config/live.toml"],
                            "healthcheck": health,
                        },
                    }
                }
            )
        )
        environment["WARNBRIDGE_LIVE_CONFIG"] = str(config)
        compose = [
            "compose",
            "-p",
            project,
            "-f",
            str(ROOT / "compose.live.yaml"),
            "-f",
            str(override),
        ]

        def request(path, source="127.0.0.1", headers=None):
            connection = http.client.HTTPConnection(
                "127.0.0.1", web_port, timeout=2, source_address=(source, 0)
            )
            try:
                connection.request("GET", path, headers=headers or {})
                response = connection.getresponse()
                return response.status, response.read()
            finally:
                connection.close()

        try:
            run([*compose, "config", "--quiet"])
            run([*compose, "up", "-d", "--no-build", "--pull", "never"])
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                try:
                    if request("/api/v1/health")[0] == 200:
                        break
                except OSError:
                    pass
                time.sleep(0.1)
            else:
                raise AssertionError("Web container never became ready")
            # Confirm Uvicorn uses actual socket peers, not trusted-looking HTTP headers.
            assert (
                request("/api/v1/health", "127.0.0.2", {"X-Forwarded-For": "127.0.0.1"})[0] == 403
            )
            assert request("/assets/map.js", "127.0.0.2")[0] == 403
            assert request("/api/v1/health", headers={"X-Forwarded-For": "203.0.113.10"})[0] == 200
            assert request("/assets/vendor/leaflet/leaflet.js")[0] == 200
            assert request("/assets/maps/reference.geojson")[0] == 200
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
                non_warn = bytearray(heartbeat())
                non_warn[2] = 0x12
                while time.monotonic() < deadline:
                    sender.sendto(bytes(non_warn) + heartbeat(), ("127.0.0.1", udp_port))
                    time.sleep(0.1)
                    state = json.loads(request("/api/v1/health")[1])
                    if state["connection"]["state"] == "recent":
                        break
                else:
                    raise AssertionError("Loopback receiver did not process heartbeat")
            metrics = json.loads(request("/api/v1/metrics")[1])
            assert metrics["messages"] == 1 and metrics["deliveries"] == 1
            for service in ("web", "receiver"):
                cid = run([*compose, "ps", "-q", service]).stdout.strip()
                info = json.loads(run(["inspect", cid]).stdout)[0]
                assert info["Config"]["User"] == "10001:10001"
                assert info["HostConfig"]["NetworkMode"] == "host"
                assert info["HostConfig"]["ReadonlyRootfs"]
                assert not info["HostConfig"]["Privileged"]
                assert "ALL" in info["HostConfig"]["CapDrop"]
                assert any(
                    "no-new-privileges" in value for value in info["HostConfig"]["SecurityOpt"]
                )
                config_mount = next(
                    m for m in info["Mounts"] if m["Destination"] == "/app/config/live.toml"
                )
                assert not config_mount["RW"]
                health_deadline = time.monotonic() + 10
                while info["State"]["Health"]["Status"] != "healthy":
                    assert time.monotonic() < health_deadline, info["State"]["Health"]
                    time.sleep(0.1)
                    info = json.loads(run(["inspect", cid]).stdout)[0]
                assert not info["HostConfig"]["PortBindings"]
                assert all(m["Destination"] != "/var/run/docker.sock" for m in info["Mounts"])
            receiver = run([*compose, "ps", "-q", "receiver"]).stdout.strip()
            run(
                [
                    "exec",
                    receiver,
                    "python",
                    "-c",
                    "from pathlib import Path; assert not Path('/data/captures').exists()",
                ]
            )
            native = run(["exec", receiver, "dpkg-query", "-W", "hdhomerun-config"]).stdout.strip()
            run([*compose, "restart", "web"])
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                try:
                    if json.loads(request("/api/v1/metrics")[1])["deliveries"] == 1:
                        break
                except OSError:
                    pass
                time.sleep(0.1)
            else:
                raise AssertionError("Archive did not survive web restart")
            run([*compose, "stop", "receiver"])
            assert json.loads(request("/api/v1/health")[1])["connection"]["state"] == "stopped"
            logs = run([*compose, "logs", "--no-color"]).stdout
            assert "Traceback" not in logs
            print(
                f"Live Compose passed: {native}; loopback reception, private peer checks, "
                "read-only/non-root containers, persistence and graceful stop."
            )
        except BaseException:
            logs = run([*compose, "logs", "--no-color"], check=False)
            print(logs.stdout[-8000:])
            raise
        finally:
            # This unique project contains only this script's synthetic fixtures.
            run([*compose, "down", "--volumes", "--remove-orphans"], check=False)


if __name__ == "__main__":
    main()
