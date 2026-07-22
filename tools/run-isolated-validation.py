#!/usr/bin/env python3
"""Run one validation command in an isolated process group.

Some legacy VirtInfra validation modules start non-daemon background threads at
import time. Pytest can finish every assertion and print its final summary while
those inherited threads keep the interpreter alive. This runner streams output,
recognizes only an explicit final success marker, gives the process a short
normal-exit grace period, then terminates the whole process group when required.
"""
from __future__ import annotations

import argparse
import os
import re
import selectors
import signal
import subprocess
import sys
import time
from typing import Sequence

FAILURE_MARKERS = (
    " failed",
    "FAILED ",
    "ERROR ",
    "Traceback (most recent call last)",
    "INTERNALERROR",
)


def _terminate_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=2)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass


def _has_failure(output: str) -> bool:
    return any(marker in output for marker in FAILURE_MARKERS)


def run(command: Sequence[str], *, timeout: float, success_pattern: str, success_grace: float) -> int:
    process = subprocess.Popen(
        list(command),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        start_new_session=True,
    )
    assert process.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    success_re = re.compile(success_pattern, flags=re.MULTILINE)
    output_parts: list[str] = []
    success_seen_at: float | None = None
    forced_after_success = False
    timed_out = False

    while True:
        now = time.monotonic()
        if process.poll() is not None:
            remainder = process.stdout.read()
            if remainder:
                output_parts.append(remainder)
                sys.stdout.write(remainder)
                sys.stdout.flush()
            break
        if now >= deadline:
            timed_out = True
            _terminate_group(process)
            break
        if success_seen_at is not None and now - success_seen_at >= success_grace:
            forced_after_success = True
            _terminate_group(process)
            break

        wait_for = min(0.25, deadline - now)
        for key, _ in selector.select(wait_for):
            line = key.fileobj.readline()
            if not line:
                continue
            output_parts.append(line)
            sys.stdout.write(line)
            sys.stdout.flush()
            joined = "".join(output_parts)
            if success_seen_at is None and success_re.search(joined) and not _has_failure(joined):
                success_seen_at = time.monotonic()

    # Drain bytes emitted during termination.
    try:
        remainder = process.stdout.read()
    except Exception:
        remainder = ""
    if remainder:
        output_parts.append(remainder)
        sys.stdout.write(remainder)
        sys.stdout.flush()
    output = "".join(output_parts)
    selector.close()

    if forced_after_success and success_re.search(output) and not _has_failure(output):
        print(
            "WARN: assertions completed, but a legacy background thread kept the "
            "interpreter alive; the isolated process group was terminated.",
            file=sys.stderr,
        )
        return 0
    if timed_out:
        if success_re.search(output) and not _has_failure(output):
            print(
                "WARN: validation success marker was complete before timeout; "
                "the isolated process group was terminated.",
                file=sys.stderr,
            )
            return 0
        print(
            f"ERROR: validation timed out after {timeout:g}s before a complete success marker",
            file=sys.stderr,
        )
        return 124
    return int(process.returncode or 0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--success-grace", type=float, default=1.0)
    parser.add_argument("--success-pattern", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("a command is required after --")
    return run(
        command,
        timeout=max(1.0, args.timeout),
        success_pattern=args.success_pattern,
        success_grace=max(0.1, args.success_grace),
    )


if __name__ == "__main__":
    raise SystemExit(main())
