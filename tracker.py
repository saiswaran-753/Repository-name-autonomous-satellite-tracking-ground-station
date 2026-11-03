"""Satellite tracking and pass-prediction software prototype.

Examples:
  python tracker.py position --latitude 12.9716 --longitude 77.5946 --elevation-m 920 --refresh-tle
  python tracker.py pass --latitude 12.9716 --longitude 77.5946 --elevation-m 920 --csv output/meteor_next_pass.csv --refresh-tle
"""

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


def add_observer_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--latitude", type=float, required=True, help="Degrees north; south is negative.")
    parser.add_argument("--longitude", type=float, required=True, help="Degrees east; west is negative.")
    parser.add_argument("--elevation-m", type=float, default=0.0, help="Ground-station elevation above sea level in metres.")
    parser.add_argument("--satellite", default=DEFAULT_SATELLITE, help=f"CelesTrak satellite name. Default: {DEFAULT_SATELLITE}")
    parser.add_argument("--refresh-tle", action="store_true", help="Download fresh orbital elements from CelesTrak.")


def as_utc_datetime(skyfield_time) -> datetime:
    value = skyfield_time.utc_datetime()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def utc_text(skyfield_time) -> str:
    return as_utc_datetime(skyfield_time).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise argparse.ArgumentTypeError("Use a UTC time such as 2026-10-31T12:00:00Z.") from error
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("Include Z or +00:00 in --time-utc.")
    return parsed.astimezone(timezone.utc)


def load_satellite(name: str, refresh_tle: bool):
    satellites = loader.tle_file(TLE_URL, reload=refresh_tle)
    wanted = name.casefold()

    for satellite in satellites:
        if satellite.name.casefold() == wanted:
            return satellite

    names = ", ".join(satellite.name for satellite in satellites)
    raise ValueError(f"Satellite '{name}' was not found. Available names: {names}")


def build_observer(args: argparse.Namespace):
    return wgs84.latlon(args.latitude, args.longitude, elevation_m=args.elevation_m)


def geometry(satellite, observer, time):
    """Return altitude/elevation, azimuth, and range for the observer."""
    topocentric = (satellite - observer).at(time)
    altitude, azimuth, distance = topocentric.altaz()
    return altitude.degrees, azimuth.degrees, distance.km


def show_position(args: argparse.Namespace) -> None:
    satellite = load_satellite(args.satellite, args.refresh_tle)
    observer = build_observer(args)
    time = timescale.from_datetime(args.time_utc) if args.time_utc else timescale.now()
    altitude, azimuth, distance_km = geometry(satellite, observer, time)

    print(f"Satellite: {satellite.name}")
    print(f"Observer:  {args.latitude:.6f}°, {args.longitude:.6f}°, {args.elevation_m:.1f} m")
    print(f"Time UTC:  {utc_text(time)}")
    print(f"Azimuth:   {azimuth:.2f}°  (0° North, 90° East)")
    print(f"Elevation: {altitude:.2f}°")
    print(f"Range:     {distance_km:.1f} km")
    print("Status:    ABOVE horizon" if altitude >= 0 else "Status:    below horizon")


def find_next_complete_pass(satellite, observer, start_time, end_time, minimum_elevation: float):
    event_times, events = satellite.find_events(
        observer,
        start_time,
        end_time,
        altitude_degrees=minimum_elevation,
    )

    rise_time = None
    for event_time, event in zip(event_times, events):
        if int(event) == 0:  # Rise above the minimum elevation.
            rise_time = event_time
        elif int(event) == 2 and rise_time is not None:  # Set below it.
            return rise_time, event_time

    raise RuntimeError(
        f"No complete pass above {minimum_elevation:.1f}° was found. "
        "Try --hours 48 or lower --min-elevation to 5."
    )


def sample_pass(satellite, observer, rise_time, set_time, sample_seconds: int):
    start = as_utc_datetime(rise_time)
    end = as_utc_datetime(set_time)
    duration_seconds = round((end - start).total_seconds())
    datetimes = [start + timedelta(seconds=offset) for offset in range(0, duration_seconds + 1, sample_seconds)]
    if datetimes[-1] < end:
        datetimes.append(end)

    sample_times = timescale.from_datetimes(datetimes)
    altitudes, azimuths, ranges = geometry(satellite, observer, sample_times)
    return list(zip(datetimes, azimuths, altitudes, ranges))


def export_pass(args: argparse.Namespace) -> None:
    satellite = load_satellite(args.satellite, args.refresh_tle)
    observer = build_observer(args)
    start_time = timescale.now()
    end_time = timescale.from_datetime(as_utc_datetime(start_time) + timedelta(hours=args.hours))
    rise_time, set_time = find_next_complete_pass(
        satellite,
        observer,
        start_time,
        end_time,
        args.min_elevation,
    )

    rows = sample_pass(satellite, observer, rise_time, set_time, args.sample_seconds)
    args.csv.parent.mkdir(parents=True, exist_ok=True)

    with args.csv.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["timestamp_utc", "azimuth_degrees", "elevation_degrees", "range_km"])
        for timestamp, azimuth, elevation, range_km in rows:
            writer.writerow([
                timestamp.isoformat(timespec="seconds").replace("+00:00", "Z"),
                f"{azimuth:.4f}",
                f"{elevation:.4f}",
                f"{range_km:.3f}",
            ])

    peak_elevation = max(float(elevation) for _, _, elevation, _ in rows)
    print(f"Satellite:        {satellite.name}")
    print(f"Pass starts UTC:  {utc_text(rise_time)}")
    print(f"Pass ends UTC:    {utc_text(set_time)}")
    print(f"Samples:          {len(rows)} every {args.sample_seconds} seconds")
    print(f"Peak elevation:   {peak_elevation:.2f}°")
    print(f"CSV written to:   {args.csv}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Track a weather satellite and export predicted passes.")
    commands = parser.add_subparsers(dest="command", required=True)

    position = commands.add_parser("position", help="Print current azimuth, elevation, and range.")
    add_observer_arguments(position)
    position.add_argument("--time-utc", type=parse_utc, help="Optional ISO UTC time; defaults to now.")
    position.set_defaults(handler=show_position)

    pass_export = commands.add_parser("pass", help="Export samples for the next complete pass.")
    add_observer_arguments(pass_export)
    pass_export.add_argument("--hours", type=float, default=24.0, help="Hours ahead to search; default: 24.")
    pass_export.add_argument("--min-elevation", type=float, default=10.0, help="Minimum pass elevation; default: 10.")
    pass_export.add_argument("--sample-seconds", type=int, default=5, help="Seconds between samples; default: 5.")
    pass_export.add_argument("--csv", type=Path, default=Path("output/meteor_next_pass.csv"), help="Output CSV path.")
    pass_export.set_defaults(handler=export_pass)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    if getattr(args, "hours", 1.0) <= 0:
        raise SystemExit("--hours must be greater than zero.")
    if getattr(args, "sample_seconds", 1) <= 0:
        raise SystemExit("--sample-seconds must be greater than zero.")

    try:
        args.handler(args)
    except (OSError, ValueError, RuntimeError) as error:
        raise SystemExit(f"Error: {error}") from error


if __name__ == "__main__":
    main()

