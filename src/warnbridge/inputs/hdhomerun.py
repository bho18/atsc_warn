"""Conservative direct-IP CLI adapter using SiliconDust keyed control writes.

See docs/sources.md for inspected upstream ref and lock semantics. Unlocked tuners
are available even when configured. No force unlock or shell commands.
"""

import secrets
import socket
import subprocess
from collections.abc import Callable
from types import TracebackType

from warnbridge.config import Config

Runner = Callable[[list[str]], str]
KEEPALIVE_PORT = 5004


class TunerError(RuntimeError):
    def __init__(self, message: str, *, uncertain: bool = False) -> None:
        super().__init__(message)
        self.uncertain = uncertain


class TunerBusy(TunerError):
    pass


def run_command(args: list[str]) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=8, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        # Do not leak command arguments: they include an owned lock token.
        raise TunerError(
            f"hdhomerun_config failed: {type(exc).__name__}",
            uncertain=isinstance(exc, subprocess.TimeoutExpired),
        ) from None
    if result.returncode != 0 or result.stdout.lstrip().upper().startswith("ERROR"):
        raise TunerError("hdhomerun_config rejected operation or device unavailable")
    return result.stdout.strip()


class Tuner:
    def __init__(self, config: Config, runner: Runner = run_command) -> None:
        if not config.receiver_host or config.tuner is None:
            raise ValueError("explicit receiver_host and tuner required")
        self.config, self.run = config, runner
        self.key = str(secrets.randbelow(0xFFFFFFFE) + 1)
        self.owned = False
        self.tuned = False
        self.streaming = False

    def command(
        self, operation: str, name: str, value: str | None = None, *, keyed: bool = False
    ) -> str:
        args = ["hdhomerun_config", str(self.config.receiver_host)]
        if keyed:
            args += ["key", self.key]
        args += [operation, f"/tuner{self.config.tuner}/{name}"]
        if value is not None:
            args.append(value)
        return self.run(args)

    def inspect(self) -> dict[str, str]:
        return {name: self.command("get", name) for name in ("status", "target", "lockkey")}

    @staticmethod
    def status_fields(status: str) -> dict[str, str]:
        return dict(part.split("=", 1) for part in status.split() if "=" in part)

    @staticmethod
    def unlocked(snapshot: dict[str, str]) -> bool:
        return snapshot.get("lockkey") == "none"

    def __enter__(self) -> "Tuner":
        self.config.require_receiver()
        if not self.unlocked(self.inspect()):
            raise TunerBusy("tuner busy: ownership lock present or unlocked state not established")
        # Device atomically refuses this unkeyed acquisition if a competing owner won.
        try:
            self.command("set", "lockkey", self.key)
        except TunerError as exc:
            if exc.uncertain:
                # The device may have accepted the key before the reply was lost.
                # Release only that key, never touch target/channel or force unlock.
                self.command("set", "lockkey", "none", keyed=True)
            elif not self.unlocked(self.inspect()):
                raise TunerBusy("tuner claimed by another client during lock acquisition") from None
            raise
        self.owned = True
        try:
            # The successful atomic acquisition, not an owner-IP read, establishes
            # ownership. All subsequent writes carry that key. Stop any old target
            # before retuning so the new stream cannot go to its former destination.
            self.streaming = True  # include ambiguous response/timeouts in cleanup
            self.command("set", "target", "none", keyed=True)
            self.tuned = True  # include ambiguous response/timeouts in cleanup
            self.command("set", "channel", str(self.config.channel), keyed=True)
            self.command(
                "set",
                "filter",
                "0x0000-0x1fff" if self.config.full_multiplex else f"0x{self.config.pid:04x}",
                keyed=True,
            )
            self.command(
                "set", "target", f"udp://{self.config.return_ip}:{self.config.udp_port}", keyed=True
            )
            return self
        except BaseException:
            self.close()
            raise

    def send_keepalive(self, sock: socket.socket) -> None:
        """Native video keepalive, using the bound receiving socket and owned key.

        SiliconDust's native client sends a big-endian uint32 to UDP 5004 every
        second. Using a different socket/source port would not establish the same
        return flow through stateful gateways. Never log the private lock token.
        """
        if not self.owned or not self.streaming:
            raise TunerError("video keepalive requires an active owned stream")
        sock.sendto(
            int(self.key).to_bytes(4, "big"), (str(self.config.receiver_host), KEEPALIVE_PORT)
        )

    def close(self) -> None:
        if not self.owned:
            return
        # Every mutation remains keyed, including cleanup. A foreign takeover causes
        # device refusal; do not then perform unkeyed resets or restore stale settings.
        try:
            if self.streaming:
                self.command("set", "target", "none", keyed=True)
            if self.tuned:
                self.command("set", "channel", "none", keyed=True)
            self.command("set", "lockkey", "none", keyed=True)
        finally:
            self.owned = False

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
