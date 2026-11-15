import argparse
import json
import math
import signal
import socket
import sqlite3
import sys
import time
from collections.abc import Iterator
from contextlib import nullcontext
from dataclasses import asdict
from pathlib import Path
from threading import Event
from typing import Any

from warnbridge.config import Config, load_config
from warnbridge.inputs.discovery import discover, inspect_device, open_receiver, select_device
from warnbridge.inputs.hdhomerun import KEEPALIVE_PORT, ReceiverStalled, Tuner, TunerError
from warnbridge.inputs.health import ReceiverMonitor
from warnbridge.inputs.streams import Chunk, Journal, file_chunks, journal_chunks, udp_chunks
from warnbridge.pipeline import Ingestor


def tuner_argument(value: str) -> int | None:
    if value == "auto":
        return None
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("tuner must be 'auto' or a number from 0 to 31") from None
    if not 0 <= number < 32:
        raise argparse.ArgumentTypeError("tuner must be 'auto' or a number from 0 to 31")
    return number


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="WarnBridge offline-first WARN receiver")
    commands = root.add_subparsers(dest="command", required=True)
    for name in (
        "decode",
        "replay",
        "listen",
        "capture",
        "udp",
        "discover",
        "serve",
        "doctor",
        "import-web",
    ):
        cmd = commands.add_parser(
            name,
            help={
                "listen": "discover/connect, lease an unlocked tuner and output live message JSONL",
                "capture": "alias for listen (raw recording is off by default)",
                "discover": "read-only native discovery or direct-IP tuner inspection",
            }.get(name),
        )
        cmd.add_argument("--config", help="TOML configuration")
        if name in ("discover", "listen", "capture", "doctor"):
            cmd.add_argument("--host", help="device IPv4; bypass broadcast discovery")
            cmd.add_argument(
                "--tuner",
                type=tuner_argument,
                default=argparse.SUPPRESS,
                help="tuner index or 'auto'; auto leases the first unlocked tuner",
            )
        if name in ("decode", "replay"):
            cmd.add_argument("input", help="TS file, or '-' for stdin (arrival times unknown)")
            cmd.add_argument("--out", help="output directory: summary.json and warnbridge.db")
            if name == "replay":
                cmd.add_argument("--journal", action="store_true", help="read arrival JSONL")
        if name in ("listen", "capture", "udp"):
            cmd.add_argument("--duration", type=float, help="optional seconds; Ctrl-C also stops")
            cmd.add_argument("--udp-bind", help="local listening IPv4 (default 0.0.0.0)")
            cmd.add_argument("--udp-port", type=int, help="UDP port (default 5000)")
            cmd.add_argument(
                "--record-raw",
                action=argparse.BooleanOptionalAction,
                default=None,
                help="opt in to bounded raw arrival journals (default off)",
            )
        if name in ("listen", "capture"):
            cmd.add_argument("--channel", help="physical RF channel, e.g. 7 or auto:7")
            cmd.add_argument(
                "--return-ip", help="IPv4 reachable by the receiver; default local route"
            )
            cmd.add_argument(
                "--full-multiplex",
                action=argparse.BooleanOptionalAction,
                default=None,
                help="diagnostic only; routine reception filters PID 0x0911",
            )
        if name == "doctor":
            cmd.add_argument("--receiver", action="store_true", help="read-only tuner queries")
        if name == "import-web":
            cmd.add_argument("input", help="saved JSON; no network requests")
    return root


def configure(args: argparse.Namespace) -> Config:
    config = load_config(args.config)
    for argument, field in (
        ("host", "receiver_host"),
        ("tuner", "tuner"),
        ("channel", "channel"),
        ("return_ip", "return_ip"),
        ("udp_bind", "udp_bind"),
        ("udp_port", "udp_port"),
        ("record_raw", "record_raw"),
        ("full_multiplex", "full_multiplex"),
    ):
        if hasattr(args, argument) and (getattr(args, argument) is not None or argument == "tuner"):
            setattr(config, field, getattr(args, argument))
    if config.channel and config.channel.isdigit():
        config.channel = f"auto:{config.channel}"
    config.__post_init__()
    return config


def json_line(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=True), flush=True)


def _live_once(
    args: argparse.Namespace,
    config: Config,
    stop: Event,
    duration: float | None,
    received: Event,
) -> int:
    """One lease and decoder lifetime; storage and bind failures remain fatal."""
    deadline = None if duration is None else time.monotonic() + duration
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind((config.udp_bind, config.udp_port))  # bind before any tuner mutation
        source = "live_udp" if args.command == "udp" else "live_hdhomerun"
        ingestor = Ingestor(
            config,
            source,
            "pending tuner selection"
            if args.command != "udp"
            else f"udp:{config.udp_bind}:{config.udp_port}",
            emit=json_line,
        )

        def expired() -> bool:
            return stop.is_set() or (deadline is not None and time.monotonic() >= deadline)

        def controlled_chunks() -> Iterator[Chunk]:
            if expired():
                return
            owner = nullcontext(None) if args.command == "udp" else open_receiver(config)
            with owner as tuner:
                active = tuner.config if tuner else config
                if expired():
                    return
                if tuner:
                    identity = f"{active.receiver_host}:tuner{active.tuner}"
                    with ingestor.store.db:
                        ingestor.store.db.execute(
                            "UPDATE sessions SET identity=? WHERE id=?",
                            (identity, ingestor.sid),
                        )
                    snapshot = tuner.inspect()
                    ingestor.store.health_event(
                        ingestor.sid, "owned_stream_started", json.dumps(snapshot)
                    )
                    status = {
                        "type": "receiver",
                        "host": active.receiver_host,
                        "tuner": active.tuner,
                        "channel": active.channel,
                        "pid": active.pid,
                        "return_ip": active.return_ip,
                        "udp_port": active.udp_port,
                        "raw_recording": config.record_raw,
                        "keepalive_port": KEEPALIVE_PORT,
                        "status": snapshot,
                    }
                    json_line(status)
                    stream_label = (
                        "full multiplex" if active.full_multiplex else f"PID 0x{active.pid:04X}"
                    )
                    print(
                        f"Listening on {active.return_ip}:{active.udp_port}, "
                        f"tuner {active.tuner}, {active.channel}, {stream_label}",
                        file=sys.stderr,
                        flush=True,
                    )
                monitor_context = (
                    ReceiverMonitor(lambda: tuner.command("get", "status"), config.rf_poll_interval)
                    if tuner
                    else nullcontext(None)
                )
                with monitor_context as monitor:

                    def persist_sample() -> None:
                        sample = monitor.latest() if monitor else None
                        if sample is not None:
                            ingestor.store.record_receiver_status(
                                ingestor.sid,
                                str(active.receiver_host),
                                int(active.tuner or 0),
                                sample.checked_at,
                                sample.raw_status,
                                sample.error,
                            )

                    def keepalive() -> None:
                        if tuner is not None:
                            tuner.send_keepalive(sock)

                    def receive() -> Iterator[Chunk]:
                        remaining = (
                            None if deadline is None else max(0.0, deadline - time.monotonic())
                        )
                        try:
                            yield from udp_chunks(
                                sock,
                                stop,
                                expected_host=active.receiver_host,
                                duration=remaining,
                                keepalive=keepalive if tuner is not None else None,
                            )
                        except OSError as exc:
                            if tuner is None:
                                raise
                            # Classify only socket I/O here, never archive/quota/bind errors.
                            raise TunerError(
                                f"receiver UDP I/O failed: {type(exc).__name__}"
                            ) from None

                    try:
                        last_data = last_warn_pid = time.monotonic()
                        warned = False
                        for chunk in receive():
                            if expired():
                                return
                            persist_sample()
                            now = time.monotonic()
                            if chunk.data and not chunk.error:
                                last_data, warned = now, False
                                # udp_chunks already checked sender, packet alignment and sync.
                                # Other PIDs (including null padding) cannot hide a lost WARN feed.
                                if any(
                                    not chunk.data[i + 1] & 0x80  # transport error indicator
                                    and not chunk.data[i + 3] & 0xC0  # scrambling
                                    and chunk.data[i + 3] & 0x10  # payload present
                                    and ((chunk.data[i + 1] & 0x1F) << 8) | chunk.data[i + 2]
                                    == config.pid
                                    for i in range(0, len(chunk.data) - 187, 188)
                                ):
                                    last_warn_pid = now
                                    received.set()
                            if not warned and now - last_data >= config.no_data_warning:
                                detail = (
                                    "No UDP TS data received: check RF lock, PID, "
                                    "and return IP/port. "
                                    "In WSL, check Windows/Hyper-V inbound filtering "
                                    "and inter-VLAN UDP routing; direct-IP control alone "
                                    "does not prove UDP works."
                                )
                                print(detail, file=sys.stderr, flush=True)
                                ingestor.store.health_event(ingestor.sid, "no_udp_data", detail)
                                warned = True
                            # Retain this chunk's evidence before unwinding a stalled session.
                            yield chunk
                            if (
                                tuner is not None
                                and now - last_warn_pid >= config.receiver_stall_timeout
                            ):
                                detail = (
                                    f"No PID 0x{config.pid:04X} transport packets for "
                                    f"{config.receiver_stall_timeout:g}s; reconnecting receiver"
                                )
                                ingestor.store.health_event(
                                    ingestor.sid, "receiver_stalled", detail
                                )
                                raise ReceiverStalled(detail)
                    finally:
                        persist_sample()

        # Each retry gets a separate journal/session/decoder and a fresh UDP socket.
        # Incomplete assemblies are finalized before any new lease can be acquired.
        journal = (
            Journal(config.capture_dir, config.capture_segment_bytes, config.capture_segments)
            if config.record_raw
            else None
        )
        summary = ingestor.process(controlled_chunks(), journal)
        json_line({"type": "summary", "session_id": ingestor.sid, "counts": summary})
        return int(ingestor.decoder.failed)


def live(args: argparse.Namespace, config: Config) -> int:
    if args.duration is not None and (not math.isfinite(args.duration) or args.duration <= 0):
        raise ValueError("duration must be finite and positive")
    if args.command != "udp" and not config.channel:
        raise ValueError("choose a physical RF channel with --channel 7 (or configure channel)")
    stop = Event()
    previous = {
        sig: signal.signal(sig, lambda *_: stop.set()) for sig in (signal.SIGINT, signal.SIGTERM)
    }
    deadline = None if args.duration is None else time.monotonic() + args.duration
    delay = config.receiver_retry_initial
    last_error: TunerError | None = None
    try:
        while not stop.is_set():
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                return 2 if last_error is not None else 0
            received = Event()
            try:
                return _live_once(args, config, stop, remaining, received)
            except TunerError as exc:
                if args.command == "udp":
                    raise
                last_error = exc
                for note in getattr(exc, "__notes__", []):
                    print(note, file=sys.stderr, flush=True)
                if stop.is_set():
                    return 0
                if received.is_set():
                    delay = config.receiver_retry_initial
                wait = delay if deadline is None else min(delay, deadline - time.monotonic())
                if wait <= 0:
                    return 2
                json_line({"type": "receiver_retry", "reason": str(exc), "retry_in_seconds": wait})
                print(
                    f"Receiver unavailable: {exc}; retrying in {wait:g}s",
                    file=sys.stderr,
                    flush=True,
                )
                if stop.wait(wait):
                    return 0
                delay = min(delay * 2, config.receiver_retry_max)
        return 0
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def run(args: argparse.Namespace) -> int:
    config = configure(args)
    if args.command == "discover":
        devices = [select_device(config)] if config.receiver_host else discover()
        print(
            json.dumps(
                {
                    "devices": [
                        {**asdict(d), "tuners": inspect_device(d, tuner=config.tuner)}
                        for d in devices
                    ]
                },
                indent=2,
            )
        )
        return 0 if devices else 1
    if args.command in ("listen", "capture", "udp"):
        return live(args, config)
    if args.command == "serve":
        import uvicorn

        from warnbridge.api.app import create_app

        # LAN restrictions use the actual socket peer, never client-supplied proxy headers.
        uvicorn.run(
            create_app(config), host=config.bind, port=config.port, workers=1, proxy_headers=False
        )
        return 0
    if args.command == "doctor":
        result: dict[str, Any] = {
            "python": sys.version.split()[0],
            "database": config.database,
            "mode": "read_only",
            "receiver": "not_contacted",
            "schema": "not_configured",
            "signature": "not_checked",
        }
        if args.receiver:
            result["receiver"] = Tuner(config).inspect()
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "import-web":
        from warnbridge.inputs.web import import_saved

        print(json.dumps(import_saved(Path(args.input), config.database)))
        return 0
    if args.out:
        destination = Path(args.out)
        destination.mkdir(parents=True, exist_ok=True)
        config.database = str(destination / "warnbridge.db")
    source = "replay" if args.command == "replay" else "stdin" if args.input == "-" else "file"
    if getattr(args, "journal", False):
        summary = Ingestor(config, source, args.input).process(journal_chunks(Path(args.input)))
    else:
        with nullcontext(sys.stdin.buffer) if args.input == "-" else open(args.input, "rb") as f:
            summary = Ingestor(config, source, args.input).process(file_chunks(f))
    print(json.dumps(summary, indent=2))
    if args.out:
        (Path(args.out) / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return int(
        bool(
            summary["rejected_packets"]
            or summary["rejected_messages"]
            or summary.get("input_errors")
        )
    )


def main() -> None:
    try:
        code = run(parser().parse_args())
    except (ValueError, OSError, TunerError, sqlite3.Error) as exc:
        print(f"warnbridge: {exc}", file=sys.stderr)
        for note in getattr(exc, "__notes__", []):
            print(f"warnbridge: {note}", file=sys.stderr)
        code = 2
    except KeyboardInterrupt:
        code = 130
    sys.exit(code)
