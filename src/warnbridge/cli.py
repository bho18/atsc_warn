import argparse
import json
import signal
import socket
import sqlite3
import sys
from contextlib import nullcontext
from pathlib import Path
from threading import Event
from typing import Any

from warnbridge.config import load_config
from warnbridge.inputs.hdhomerun import Tuner, TunerError
from warnbridge.inputs.streams import Journal, file_chunks, journal_chunks, udp_chunks
from warnbridge.pipeline import Ingestor


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="WarnBridge experimental offline-first WARN receiver"
    )
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("decode", "replay", "capture", "udp", "serve", "doctor", "import-web"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--config", help="TOML config; defaults are offline and loopback-only")
        if name in ("decode", "replay"):
            cmd.add_argument("input", help="TS file, or '-' for stdin (no inferred arrival times)")
            cmd.add_argument("--out", help="output directory: summary.json and warnbridge.db")
            if name == "replay":
                cmd.add_argument(
                    "--journal", action="store_true", help="read arrival JSONL file/directory"
                )
        if name in ("capture", "udp"):
            cmd.add_argument(
                "--duration", type=float, help="optional seconds; Ctrl-C/SIGTERM also stop"
            )
        if name == "doctor":
            cmd.add_argument(
                "--receiver", action="store_true", help="explicit read-only tuner queries"
            )
        if name == "import-web":
            cmd.add_argument("input", help="saved JSON; no network requests")
    return root


def run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if args.command == "serve":
        import uvicorn

        from warnbridge.api.app import create_app

        uvicorn.run(create_app(config), host=config.bind, port=config.port, workers=1)
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
    if args.command in ("decode", "replay"):
        if args.out:
            destination = Path(args.out)
            destination.mkdir(parents=True, exist_ok=True)
            config.database = str(destination / "warnbridge.db")
        source = "replay" if args.command == "replay" else "stdin" if args.input == "-" else "file"
        if getattr(args, "journal", False):
            summary = Ingestor(config, source, args.input).process(journal_chunks(Path(args.input)))
        else:
            with (
                nullcontext(sys.stdin.buffer) if args.input == "-" else open(args.input, "rb") as f
            ):
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
    if args.duration is not None and args.duration <= 0:
        raise ValueError("duration must be positive")
    stop = Event()
    previous = {
        sig: signal.signal(sig, lambda *_: stop.set()) for sig in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind((config.udp_bind, config.udp_port))  # bind before touching hardware
            source = "live_hdhomerun" if args.command == "capture" else "live_udp"
            identity = f"{config.receiver_host or 'udp'}:tuner{config.tuner}"
            ingestor = Ingestor(config, source, identity)

            def controlled_chunks() -> Any:
                owner = Tuner(config) if args.command == "capture" else nullcontext()
                with owner:
                    if args.command == "capture":
                        ingestor.store.health_event(ingestor.sid, "owned_stream_started", identity)
                    yield from udp_chunks(
                        sock, stop, expected_host=config.receiver_host, duration=args.duration
                    )

            summary = ingestor.process(
                controlled_chunks(),
                Journal(config.capture_dir, config.capture_segment_bytes, config.capture_segments),
            )
        print(json.dumps(summary, indent=2))
        return 0
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main() -> None:
    try:
        code = run(parser().parse_args())
    except (ValueError, OSError, TunerError, sqlite3.Error) as exc:
        print(f"warnbridge: {exc}", file=sys.stderr)
        code = 2
    except KeyboardInterrupt:
        code = 130
    sys.exit(code)
