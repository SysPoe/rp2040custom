#!/usr/bin/env python3
"""
Analyze Hantek/OpenHantek CSV captures of DMX/RS-485.

Examples:
  python tools/analyze_hantek_dmx.py test1 --signal math
  python tools/analyze_hantek_dmx.py capture.csv --signal ch2-ch1 --expected-static 70 --zero-ranges 4-10

For byte decoding, capture at a high sample rate. 12 MS/s is good. 500 kS/s is
useful for break/frame timing, but not enough to reliably decode 4 us DMX bits.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import math
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DMX_BAUD = 250_000.0
DMX_BIT_S = 1.0 / DMX_BAUD
DMX_SLOT_BITS = 11
DMX_SLOT_S = DMX_BIT_S * DMX_SLOT_BITS
DMX_SLOTS = 513
DMX_BREAK_MIN_S = 88e-6
DMX_MAB_MIN_S = 8e-6
GOOD_DECODE_DT_S = 1e-6


@dataclass
class Run:
    high: bool
    start: int
    end: int

    def duration_s(self, t: list[float]) -> float:
        return t[self.end] - t[self.start]


@dataclass
class Frame:
    break_run: Run
    start_time: float | None
    mab_s: float | None
    slots: list[int]
    slot_errors: list[str]
    mismatches: list[str]


def percentile(values: list[float], p: float) -> float:
    if not values:
        raise ValueError("empty signal")
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * p)))
    return ordered[idx]


def read_csv(path: Path) -> tuple[list[str], list[float], list[list[float]]]:
    with path.open(newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows: list[list[float]] = []
        for line_no, row in enumerate(reader, start=2):
            if not row or all(not cell.strip() for cell in row):
                continue
            try:
                rows.append([float(cell) for cell in row[: len(header)]])
            except ValueError as exc:
                raise SystemExit(f"{path}:{line_no}: could not parse numeric CSV row: {row}") from exc

    if len(header) < 2:
        raise SystemExit("CSV needs at least time plus one voltage column")
    if len(rows) < 10:
        raise SystemExit("CSV has too few samples")

    columns = list(zip(*rows))
    t = list(columns[0])
    signals = [list(col) for col in columns[1:]]
    return header, t, signals


def find_column(header: list[str], needle: str) -> int | None:
    n = needle.lower()
    for idx, name in enumerate(header):
        compact = name.lower().replace(" ", "")
        if n in compact:
            return idx
    return None


def select_signal(header: list[str], signals: list[list[float]], mode: str) -> tuple[str, list[float]]:
    voltage_headers = header[1:]

    def col(name: str) -> tuple[str, list[float]]:
        idx = find_column(header, name)
        if idx is None or idx == 0:
            raise SystemExit(f"Could not find column matching {name!r}; columns are: {header}")
        return header[idx], signals[idx - 1]

    mode = mode.lower()
    if mode == "auto":
        math_col = find_column(header, "math")
        ch1_col = find_column(header, "ch1")
        ch2_col = find_column(header, "ch2")
        if math_col is not None and math_col > 0:
            return header[math_col], signals[math_col - 1]
        if ch1_col is not None and ch2_col is not None and ch1_col > 0 and ch2_col > 0:
            a = signals[ch1_col - 1]
            b = signals[ch2_col - 1]
            return f"{header[ch2_col]} - {header[ch1_col]}", [bb - aa for aa, bb in zip(a, b)]
        return voltage_headers[0], signals[0]

    if mode == "math":
        return col("math")
    if mode in ("ch1", "ch2"):
        return col(mode)
    if mode in ("ch1-ch2", "ch2-ch1"):
        ch1_name, ch1 = col("ch1")
        ch2_name, ch2 = col("ch2")
        if mode == "ch1-ch2":
            return f"{ch1_name} - {ch2_name}", [a - b for a, b in zip(ch1, ch2)]
        return f"{ch2_name} - {ch1_name}", [b - a for a, b in zip(ch1, ch2)]

    idx = find_column(header, mode)
    if idx is None or idx == 0:
        raise SystemExit(f"Could not find signal {mode!r}; columns are: {header}")
    return header[idx], signals[idx - 1]


def median_dt(t: list[float]) -> float:
    dts = [b - a for a, b in zip(t, t[1:]) if b > a]
    return statistics.median(dts)


def build_runs(t: list[float], v: list[float], threshold: float, invert: bool) -> list[Run]:
    def bit(x: float) -> bool:
        high = x > threshold
        return not high if invert else high

    runs: list[Run] = []
    state = bit(v[0])
    start = 0
    for i, value in enumerate(v[1:], start=1):
        next_state = bit(value)
        if next_state != state:
            runs.append(Run(state, start, i - 1))
            state = next_state
            start = i
    runs.append(Run(state, start, len(v) - 1))
    return runs


def candidate_score(t: list[float], runs: list[Run]) -> tuple[int, float]:
    plausible = 0
    implausible = 0
    for idx, run in enumerate(runs):
        if run.high or run.duration_s(t) < DMX_BREAK_MIN_S:
            continue
        start_s, mab_s = find_next_start(t, runs, idx)
        if start_s is not None and mab_s is not None and DMX_MAB_MIN_S <= mab_s <= 80e-6:
            plausible += 1
        else:
            implausible += 1
    idle = sum(run.duration_s(t) for run in runs if run.high and run.duration_s(t) > 500e-6)
    return plausible, -implausible, idle


def choose_polarity(t: list[float], v: list[float], threshold: float, requested: str) -> tuple[bool, list[Run], str]:
    if requested == "normal":
        return False, build_runs(t, v, threshold, False), "normal"
    if requested == "invert":
        return True, build_runs(t, v, threshold, True), "inverted"

    normal = build_runs(t, v, threshold, False)
    inverted = build_runs(t, v, threshold, True)
    normal_score = candidate_score(t, normal)
    inverted_score = candidate_score(t, inverted)
    if inverted_score > normal_score:
        return True, inverted, "auto: inverted"
    return False, normal, "auto: normal"


def sample_logic(t: list[float], v: list[float], threshold: float, invert: bool, at_s: float, half_window_s: float) -> bool:
    left = bisect.bisect_left(t, at_s - half_window_s)
    right = bisect.bisect_right(t, at_s + half_window_s)
    if right <= left:
        idx = min(len(t) - 1, max(0, bisect.bisect_left(t, at_s)))
        high = v[idx] > threshold
        return not high if invert else high
    highs = 0
    total = 0
    for x in v[left:right]:
        high = x > threshold
        highs += int(not high if invert else high)
        total += 1
    return highs * 2 >= total


def find_next_start(t: list[float], runs: list[Run], break_idx: int) -> tuple[float | None, float | None]:
    break_run = runs[break_idx]
    break_end_s = t[break_run.end]
    for run in runs[break_idx + 1 :]:
        if not run.high:
            start_s = t[run.start]
            return start_s, start_s - break_end_s
    return None, None


def decode_slot(
    t: list[float],
    v: list[float],
    threshold: float,
    invert: bool,
    start_s: float,
    sample_window_s: float,
) -> tuple[int, list[str]]:
    errors: list[str] = []
    start_bit = sample_logic(t, v, threshold, invert, start_s + 0.5 * DMX_BIT_S, sample_window_s)
    if start_bit:
        errors.append("start bit high")

    value = 0
    for bit in range(8):
        if sample_logic(t, v, threshold, invert, start_s + (1.5 + bit) * DMX_BIT_S, sample_window_s):
            value |= 1 << bit

    stop1 = sample_logic(t, v, threshold, invert, start_s + 9.5 * DMX_BIT_S, sample_window_s)
    stop2 = sample_logic(t, v, threshold, invert, start_s + 10.5 * DMX_BIT_S, sample_window_s)
    if not stop1:
        errors.append("stop bit 1 low")
    if not stop2:
        errors.append("stop bit 2 low")
    return value, errors


def parse_ranges(text: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    if not text:
        return ranges
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo_s, hi_s = part.split("-", 1)
            lo, hi = int(lo_s), int(hi_s)
        else:
            lo = hi = int(part)
        if lo < 1 or hi > 512 or hi < lo:
            raise SystemExit(f"Bad DMX channel range: {part!r}")
        ranges.append((lo, hi))
    return ranges


def expected_value(slot: int, static: int | None, zero_ranges: list[tuple[int, int]]) -> int | None:
    if slot == 0:
        return 0
    if static is None:
        return None
    channel = slot
    for lo, hi in zero_ranges:
        if lo <= channel <= hi:
            return 0
    return static


def analyze_frames(
    t: list[float],
    v: list[float],
    threshold: float,
    invert: bool,
    runs: list[Run],
    dt_s: float,
    expected_static: int | None,
    zero_ranges: list[tuple[int, int]],
) -> list[Frame]:
    frames: list[Frame] = []
    break_indices = [i for i, run in enumerate(runs) if not run.high and run.duration_s(t) >= DMX_BREAK_MIN_S]
    decode_ok = dt_s <= GOOD_DECODE_DT_S
    sample_window_s = max(dt_s * 2.0, 0.25e-6)

    for break_pos, break_idx in enumerate(break_indices):
        start_s, mab_s = find_next_start(t, runs, break_idx)
        frame = Frame(runs[break_idx], start_s, mab_s, [], [], [])
        if not decode_ok or start_s is None:
            frames.append(frame)
            continue

        next_break_s = t[runs[break_indices[break_pos + 1]].start] if break_pos + 1 < len(break_indices) else t[-1]
        available_slots = max(0, min(DMX_SLOTS, int((next_break_s - start_s) / DMX_SLOT_S)))
        for slot in range(available_slots):
            slot_start = start_s + slot * DMX_SLOT_S
            if slot_start + DMX_SLOT_S > t[-1]:
                break
            value, errors = decode_slot(t, v, threshold, invert, slot_start, sample_window_s)
            frame.slots.append(value)
            for error in errors:
                frame.slot_errors.append(f"slot {slot}: {error}")

            expected = expected_value(slot, expected_static, zero_ranges)
            if expected is not None and value != expected:
                label = "start code" if slot == 0 else f"ch {slot}"
                frame.mismatches.append(f"{label}: got {value}, expected {expected}")

        frames.append(frame)
    return frames


def fmt_us(seconds: float | None) -> str:
    if seconds is None:
        return "n/a"
    return f"{seconds * 1e6:.1f} us"


def print_frame_report(t: list[float], frames: list[Frame], max_items: int) -> int:
    issue_count = 0
    if not frames:
        print("No DMX breaks found. Polarity may be wrong, capture may be too short, or the signal is not DMX-like.")
        return 1

    print(f"Frames found: {len(frames)}")
    prev_slots: list[int] | None = None
    for idx, frame in enumerate(frames, start=1):
        break_s = frame.break_run.duration_s(t)
        warnings: list[str] = []
        if break_s < DMX_BREAK_MIN_S:
            warnings.append("break too short")
        if frame.mab_s is not None and frame.mab_s < DMX_MAB_MIN_S:
            warnings.append("MAB too short")
        if frame.slot_errors:
            warnings.append(f"{len(frame.slot_errors)} serial framing errors")
        if frame.mismatches:
            warnings.append(f"{len(frame.mismatches)} expected-value mismatches")

        if prev_slots is not None and frame.slots:
            diffs = []
            for slot, (a, b) in enumerate(zip(prev_slots, frame.slots)):
                if a != b:
                    label = "start code" if slot == 0 else f"ch {slot}"
                    diffs.append(f"{label}: prev {a}, now {b}")
            if diffs:
                warnings.append(f"{len(diffs)} frame-to-frame changes")
                if len(diffs) <= max_items:
                    frame.mismatches.extend(diffs)
                else:
                    frame.mismatches.extend(diffs[:max_items])

        if warnings:
            issue_count += 1

        print(
            f"Frame {idx}: break={fmt_us(break_s)}, MAB={fmt_us(frame.mab_s)}, "
            f"decoded_slots={len(frame.slots)}"
            + (f", issues={'; '.join(warnings)}" if warnings else "")
        )

        for line in frame.slot_errors[:max_items]:
            print(f"  framing: {line}")
        if len(frame.slot_errors) > max_items:
            print(f"  framing: ... {len(frame.slot_errors) - max_items} more")

        for line in frame.mismatches[:max_items]:
            print(f"  mismatch: {line}")
        if len(frame.mismatches) > max_items:
            print(f"  mismatch: ... {len(frame.mismatches) - max_items} more")

        if frame.slots:
            preview = ", ".join(str(x) for x in frame.slots[:16])
            print(f"  first slots: {preview}")
            prev_slots = frame.slots

    return issue_count


def main(argv: Iterable[str]) -> int:
    parser = argparse.ArgumentParser(description="Analyze Hantek/OpenHantek CSV captures of DMX/RS-485.")
    parser.add_argument("csv", type=Path, help="Hantek/OpenHantek CSV export")
    parser.add_argument(
        "--signal",
        default="auto",
        help="Signal column/expression: auto, math, ch1, ch2, ch1-ch2, ch2-ch1, or a header substring",
    )
    parser.add_argument(
        "--polarity",
        choices=("auto", "normal", "invert"),
        default="auto",
        help="Invert logical signal if needed so idle/stop is high and break/start are low",
    )
    parser.add_argument("--expected-static", type=int, help="Expected value for all non-excluded DMX channels")
    parser.add_argument(
        "--zero-ranges",
        default="",
        help="Comma-separated DMX channel ranges expected to be zero, e.g. 4-10,20",
    )
    parser.add_argument("--max-items", type=int, default=20, help="Maximum detailed mismatches/errors to print per frame")
    args = parser.parse_args(list(argv))

    header, t, signals = read_csv(args.csv)
    signal_name, v = select_signal(header, signals, args.signal)
    if len(t) != len(v):
        raise SystemExit("time and signal length mismatch")
    if args.expected_static is not None and not 0 <= args.expected_static <= 255:
        raise SystemExit("--expected-static must be 0..255")

    dt_s = median_dt(t)
    low = percentile(v, 0.05)
    high = percentile(v, 0.95)
    threshold = (low + high) / 2.0
    invert, runs, polarity_label = choose_polarity(t, v, threshold, args.polarity)
    zero_ranges = parse_ranges(args.zero_ranges)
    frames = analyze_frames(t, v, threshold, invert, runs, dt_s, args.expected_static, zero_ranges)

    print(f"File: {args.csv}")
    print(f"Columns: {header}")
    print(f"Signal: {signal_name}")
    print(f"Samples: {len(t)}, duration: {t[-1] - t[0]:.6f} s, sample dt: {dt_s * 1e6:.3f} us")
    print(f"Signal levels: p05={low:.4g} V, p95={high:.4g} V, threshold={threshold:.4g} V")
    print(f"Polarity: {polarity_label}")
    if dt_s > GOOD_DECODE_DT_S:
        print(
            f"WARNING: sample dt is {dt_s * 1e6:.2f} us. This is too slow for reliable byte decode; "
            "break/frame timing is still useful."
        )

    issue_count = print_frame_report(t, frames, args.max_items)
    return 1 if issue_count else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
