
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

from skyfield.api import Loader, wgs84


TLE_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=weather&FORMAT=tle"
DEFAULT_SATELLITE = "METEOR-M 2"
PROJECT_DIR = Path(__file__).resolve().parent

loader = Loader(str(PROJECT_DIR / "data"))
timescale = loader.timescale()


# --------------------------------------------------
# ARGUMENTS
# --------------------------------------------------

def add_observer_arguments(parser):
    parser.add_argument("--latitude", type=float, required=True)
    parser.add_argument("--longitude", type=float, required=True)
    parser.add_argument("--elevation-m", type=float, default=0.0)
    parser.add_argument("--satellite", default=DEFAULT_SATELLITE)
    parser.add_argument("--refresh-tle", action="store_true")


# --------------------------------------------------
# TIME FUNCTIONS
# --------------------------------------------------

def as_utc_datetime(skyfield_time):
    value = skyfield_time.utc_datetime()

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def utc_text(skyfield_time):
    return (
        as_utc_datetime(skyfield_time)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def parse_utc(value):
    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "Use UTC time such as 2026-10-31T12:00:00Z."
        ) from error

    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError(
            "Include Z or +00:00 in --time-utc."
        )

    return parsed.astimezone(timezone.utc)


# --------------------------------------------------
# SATELLITE FUNCTIONS
# --------------------------------------------------

def load_satellite(name, refresh_tle=False):
    satellites = loader.tle_file(
        TLE_URL,
        reload=refresh_tle
    )

    for satellite in satellites:
        if satellite.name.casefold() == name.casefold():
            return satellite

    names = ", ".join(s.name for s in satellites)

    raise ValueError(
        f"Satellite '{name}' was not found. "
        f"Available names: {names}"
    )


def build_observer(args):
    return wgs84.latlon(
        args.latitude,
        args.longitude,
        elevation_m=args.elevation_m
    )


def geometry(satellite, observer, time):
    """Return elevation, azimuth and range."""

    topocentric = (satellite - observer).at(time)
    altitude, azimuth, distance = topocentric.altaz()

    return (
        altitude.degrees,
        azimuth.degrees,
        distance.km
    )


# --------------------------------------------------
# POSITION COMMAND
# --------------------------------------------------

def show_position(args):
    satellite = load_satellite(
        args.satellite,
        args.refresh_tle
    )

    observer = build_observer(args)

    time = (
        timescale.from_datetime(args.time_utc)
        if args.time_utc
        else timescale.now()
    )

    altitude, azimuth, distance = geometry(
        satellite, observer, time
    )

    print(f"Satellite: {satellite.name}")
    print(f"Observer: {args.latitude}, {args.longitude}")
    print(f"Time UTC: {utc_text(time)}")
    print(f"Azimuth: {azimuth:.2f}°")
    print(f"Elevation: {altitude:.2f}°")
    print(f"Range: {distance:.1f} km")

    print(
        "Status: ABOVE horizon"
        if altitude >= 0
        else "Status: BELOW horizon"
    )


# --------------------------------------------------
# PASS PREDICTION
# --------------------------------------------------

def find_next_complete_pass(
    satellite,
    observer,
    start_time,
    end_time,
    minimum_elevation
):
    event_times, events = satellite.find_events(
        observer,
        start_time,
        end_time,
        altitude_degrees=minimum_elevation
    )

    rise_time = None

    for event_time, event in zip(event_times, events):

        if int(event) == 0:
            rise_time = event_time

        elif int(event) == 2 and rise_time is not None:
            return rise_time, event_time

    raise RuntimeError(
        f"No complete pass above {minimum_elevation}° found. "
        "Try a longer search window or lower elevation."
    )


# --------------------------------------------------
# PASS SAMPLING WITH PRE/POST BUFFER
# --------------------------------------------------

def sample_pass(
    satellite,
    observer,
    rise_time,
    set_time,
    sample_seconds: int,
    padding_seconds: int = 60
):
    """Sample a pass with additional pre-pass and post-pass data."""

    if sample_seconds <= 0:
        raise ValueError("Sample interval must be positive.")

    if padding_seconds < 0:
        raise ValueError("Padding cannot be negative.")

    start = as_utc_datetime(rise_time) - timedelta(
        seconds=padding_seconds
    )

    end = as_utc_datetime(set_time) + timedelta(
        seconds=padding_seconds
    )

    if end <= start:
        raise ValueError("Pass end time must be after start time.")

    duration = int((end - start).total_seconds())

    datetimes = [
        start + timedelta(seconds=i)
        for i in range(0, duration + 1, sample_seconds)
    ]

    if datetimes[-1] < end:
        datetimes.append(end)

    sample_times = timescale.from_datetimes(datetimes)

    altitudes, azimuths, ranges = geometry(
        satellite,
        observer,
        sample_times
    )

    return list(zip(
        datetimes,
        azimuths,
        altitudes,
        ranges
    ))


# --------------------------------------------------
# CSV EXPORT
# --------------------------------------------------

def export_pass(args):
    satellite = load_satellite(
        args.satellite,
        args.refresh_tle
    )

    observer = build_observer(args)

    start_time = timescale.now()

    end_time = timescale.from_datetime(
        as_utc_datetime(start_time)
        + timedelta(hours=args.hours)
    )

    rise_time, set_time = find_next_complete_pass(
        satellite,
        observer,
        start_time,
        end_time,
        args.min_elevation
    )

    rows = sample_pass(
        satellite,
        observer,
        rise_time,
        set_time,
        args.sample_seconds,
        args.padding_seconds
    )

    args.csv.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with args.csv.open(
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.writer(file)

        writer.writerow([
            "timestamp_utc",
            "azimuth_degrees",
            "elevation_degrees",
            "range_km"
        ])

        for timestamp, azimuth, elevation, distance in rows:

            writer.writerow([
                timestamp.isoformat(
                    timespec="seconds"
                ).replace("+00:00", "Z"),
                f"{azimuth:.4f}",
                f"{elevation:.4f}",
                f"{distance:.3f}"
            ])

    peak_elevation = max(
        float(row[2]) for row in rows
    )

    print("\n========================================")
    print(" SATELLITE PASS PREDICTION")
    print("========================================")

    print(f"Satellite: {satellite.name}")
    print(f"AOS UTC: {utc_text(rise_time)}")
    print(f"LOS UTC: {utc_text(set_time)}")
    print(f"Samples: {len(rows)}")
    print(f"Sample interval: {args.sample_seconds} seconds")
    print(f"Pre/post buffer: {args.padding_seconds} seconds")
    print(f"Peak elevation: {peak_elevation:.2f}°")
    print(f"CSV written to: {args.csv}")

    print("========================================\n")


# --------------------------------------------------
# COMMAND LINE INTERFACE
# --------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        description="Weather satellite tracking and pass prediction."
    )

    commands = parser.add_subparsers(
        dest="command",
        required=True
    )

    position = commands.add_parser("position")
    add_observer_arguments(position)

    position.add_argument(
        "--time-utc",
        type=parse_utc
    )

    position.set_defaults(handler=show_position)

    pass_export = commands.add_parser("pass")
    add_observer_arguments(pass_export)

    pass_export.add_argument(
        "--hours",
        type=float,
        default=24.0
    )

    pass_export.add_argument(
        "--min-elevation",
        type=float,
        default=10.0
    )

    pass_export.add_argument(
        "--sample-seconds",
        type=int,
        default=5
    )

    pass_export.add_argument(
        "--padding-seconds",
        type=int,
        default=60
    )

    pass_export.add_argument(
        "--csv",
        type=Path,
        default=PROJECT_DIR / "output" / "meteor_next_pass.csv"
    )

    pass_export.set_defaults(handler=export_pass)

    return parser


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    parser = build_parser()
    args = parser.parse_args()

    if getattr(args, "hours", 1) <= 0:
        parser.error("--hours must be greater than zero.")

    if getattr(args, "sample_seconds", 1) <= 0:
        parser.error("--sample-seconds must be positive.")

    if getattr(args, "padding_seconds", 0) < 0:
        parser.error("--padding-seconds cannot be negative.")

    if not -90 <= args.latitude <= 90:
        parser.error("Latitude must be between -90 and 90.")

    if not -180 <= args.longitude <= 180:
        parser.error("Longitude must be between -180 and 180.")

    if getattr(args, "min_elevation", 0) < 0 or getattr(args, "min_elevation", 0) > 90:
        parser.error("Minimum elevation must be between 0 and 90.")

    try:
        args.handler(args)

    except (OSError, ValueError, RuntimeError) as error:
        raise SystemExit(f"Error: {error}") from error


if __name__ == "__main__":
    main()
