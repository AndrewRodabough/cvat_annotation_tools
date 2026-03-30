import re


def time_to_seconds(value: str) -> float:
    v = value.strip()
    if not v:
        raise ValueError("Empty timestamp")

    if re.fullmatch(r"\d+(\.\d+)?", v):
        return float(v)

    parts = v.split(":")
    if len(parts) > 3:
        raise ValueError(f"Invalid timestamp: {value}")

    parts_f = [float(p) for p in parts]
    if len(parts_f) == 3:
        h, m, s = parts_f
    elif len(parts_f) == 2:
        h = 0.0
        m, s = parts_f
    else:
        h = 0.0
        m = 0.0
        s = parts_f[0]

    return h * 3600.0 + m * 60.0 + s


def parse_ranges(raw: str) -> list[tuple[float, float]]:
    raw = raw.strip()
    if not raw:
        return []

    ranges: list[tuple[float, float]] = []
    for token in raw.split(","):
        piece = token.strip()
        if not piece:
            continue
        if "-" not in piece:
            raise ValueError(
                "Each range must look like start-end, e.g. 00:00:05-00:00:12"
            )
        start_s, end_s = piece.split("-", 1)
        start = time_to_seconds(start_s)
        end = time_to_seconds(end_s)
        if end <= start:
            raise ValueError(f"Range end must be greater than start: {piece}")
        ranges.append((start, end))

    return sorted(ranges, key=lambda x: x[0])


def finalize_ranges(ranges: list[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    if not ranges:
        return []

    normalized = []
    for start_s, end_s in ranges:
        if duration > 0:
            start_s = max(0.0, min(start_s, duration))
            end_s = max(0.0, min(end_s, duration))
        if end_s > start_s:
            normalized.append((start_s, end_s))

    normalized.sort(key=lambda x: x[0])

    merged: list[tuple[float, float]] = []
    for start_s, end_s in normalized:
        if not merged or start_s > merged[-1][1]:
            merged.append((start_s, end_s))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end_s))
    return merged


def ask_ranges_text(
    video_path: str,
    duration: float,
    prompt_input: callable,
) -> list[tuple[float, float]]:
    print("\n" + "=" * 80)
    print(f"Video: {video_path}")
    if duration > 0:
        print(f"Duration: {duration:.2f}s")
    print(
        "Enter keep-ranges as comma-separated start-end pairs. "
        "Examples: 5-15, 00:01:10-00:01:20, 75.5-81.2"
    )
    print("Leave blank to keep the full video.")

    raw = prompt_input("Keep ranges: ")
    ranges = parse_ranges(raw)
    return finalize_ranges(ranges, duration)


def print_ranges(ranges: list[tuple[float, float]]) -> None:
    if not ranges:
        print("Ranges: full video")
        return
    print("Ranges:")
    for idx, (start_s, end_s) in enumerate(ranges, start=1):
        print(f"  {idx}. {start_s:.3f}s -> {end_s:.3f}s")
