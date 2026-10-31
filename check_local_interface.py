#!/usr/bin/env python3
"""Local Linux interface Nagios check with SNMP-compatible counter perfdata."""
import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import re
import sys
import time

METRICS = {
    "in_octet": "rx_bytes", "out_octet": "tx_bytes",
    "in_error": "rx_errors", "out_error": "tx_errors",
    "in_discard": "rx_dropped", "out_discard": "tx_dropped",
}
OK, WARNING, CRITICAL, UNKNOWN = range(4)


def run():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("interface")
    p.add_argument("--state-dir", default="/var/lib/nagios4/local-interfaces")
    p.add_argument("--sysfs", default="/sys/class/net", help=argparse.SUPPRESS)
    p.add_argument("--warning", type=float, default=10, help="error/discard events per minute")
    p.add_argument("--critical", type=float, default=20, help="error/discard events per minute")
    args = p.parse_args()
    name = args.interface
    if not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,32}", name) or name in (".", ".."):
        raise ValueError("invalid interface name")
    if not (math.isfinite(args.warning) and math.isfinite(args.critical) and
            0 <= args.warning <= args.critical):
        raise ValueError("invalid thresholds")
    root = Path(args.sysfs) / name
    if not root.is_dir():
        raise FileNotFoundError("interface not found: " + name)
    link = (root / "operstate").read_text().strip()
    try:
        speed_mbps = int((root / "speed").read_text().strip())
        speed_bps = speed_mbps * 1000000 if speed_mbps > 0 else 0
    except (OSError, ValueError):
        speed_bps = 0
    counters = {metric: int((root / "statistics" / path).read_text().strip())
                for metric, path in METRICS.items()}
    if any(n < 0 for n in counters.values()):
        raise ValueError("negative kernel counter")
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    now = time.monotonic()
    state_dir = Path(args.state_dir)
    state_dir.mkdir(mode=0o750, parents=True, exist_ok=True)
    # The state directory must be owned by the nagios user and not writable by others.
    state = state_dir / (name + ".json")
    lock = state_dir / (name + ".lock")
    with lock.open("a+") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            previous = json.loads(state.read_text())
        except (OSError, ValueError, TypeError):
            previous = None
        baseline = (not isinstance(previous, dict) or
                    previous.get("boot") != boot or
                    not isinstance(previous.get("counters"), dict) or
                    not isinstance(previous.get("at"), (int, float)) or
                    previous["at"] >= now or
                    any(counters[k] < previous["counters"].get(k, -1)
                        for k in counters))
        rates = {}
        if not baseline:
            elapsed = now - previous["at"]
            rates = {k: (counters[k] - previous["counters"][k]) / elapsed
                     for k in counters}
        next_state = {"boot": boot, "at": now, "counters": counters}
        temporary = state_dir / (name + ".json.tmp." + str(os.getpid()))
        try:
            with temporary.open("x") as fh:
                json.dump(next_state, fh)
                fh.write("\n")
            os.replace(temporary, state)
        finally:
            temporary.unlink(missing_ok=True)
    perf_order = ("in_octet", "out_octet", "in_error", "in_discard",
                  "out_error", "out_discard")
    perf = " ".join(f"'{name}_{k}'={counters[k]}c" for k in perf_order)
    if speed_bps:
        perf += f" '{name}_speed_bps'={speed_bps}"
    if link != "up":
        status, message = CRITICAL, f"{name}:DOWN (link={link}):(0 UP): CRITICAL"
    elif baseline:
        status, message = OK, f"{name}:UP (baseline initialized):(1 UP): OK"
    else:
        inbound, outbound = rates["in_octet"], rates["out_octet"]
        event_rates = {k: rates[k] * 60 for k in
                       ("in_error", "out_error", "in_discard", "out_discard")}
        # Match check_int: inbound discards are graphed but do not alert.
        peak = max(event_rates[k] for k in ("in_error", "out_error", "out_discard"))
        status = CRITICAL if peak >= args.critical else WARNING if peak >= args.warning else OK
        label = ["OK", "WARNING", "CRITICAL"][status]
        message = (f"{name}:UP (in={inbound / 1000:.1f}KBps/out={outbound / 1000:.1f}KBps/"
                   f"errors-in={event_rates['in_error']:.1f}/"
                   f"errors-out={event_rates['out_error']:.1f}/"
                   f"discard-in={event_rates['in_discard']:.1f}/"
                   f"discard-out={event_rates['out_discard']:.1f}):(1 UP): {label}")
    print(f"{message} | {perf}")
    return status


if __name__ == "__main__":
    try:
        sys.exit(run())
    except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError) as exc:
        print(f"UNKNOWN - local interface: {type(exc).__name__}: {exc}")
        sys.exit(UNKNOWN)
