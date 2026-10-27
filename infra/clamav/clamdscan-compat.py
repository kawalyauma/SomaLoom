#!/usr/bin/env python3
"""Small ClamD local-socket client for the Telegram importer container."""
import socket
import sys

SOCKET = "/tmp/clamd.sock"


def command(value: str) -> str:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(180)
        client.connect(SOCKET)
        client.sendall(b"z" + value.encode("utf-8", "surrogateescape") + b"\0")
        chunks = bytearray()
        while not chunks.endswith(b"\0"):
            chunk = client.recv(4096)
            if not chunk:
                break
            chunks.extend(chunk)
    return chunks.rstrip(b"\0").decode("utf-8", "replace")


def main(args: list[str]) -> int:
    if args == ["--ping"]:
        return 0 if command("PING") == "PONG" else 2
    if len(args) != 1:
        print("Expected a file path or --ping", file=sys.stderr)
        return 2
    result = command("SCAN " + args[0])
    if result.endswith(": OK"):
        return 0
    if result.endswith(" FOUND"):
        print(result, file=sys.stderr)
        return 1
    print(result or "ClamAV returned no scan result", file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (OSError, TimeoutError) as exc:
        print("ClamAV scanner unavailable (" + type(exc).__name__ + ")", file=sys.stderr)
        raise SystemExit(2) from None
