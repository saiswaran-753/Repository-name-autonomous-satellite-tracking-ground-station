
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from skyfield.api import EarthSatellite, Loader, wgs84


TLE_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=weather&FORMAT=tle"
CELESTRAK_CATNR_URL = "https://celestrak.org/NORAD/elements/gp.php?CATNR={norad_id}&FORMAT=tle"
DEFAULT_SATELLITE = "METEOR-M 2"

SATELLITE_CATALOG = {
    "METEOR-M 2": {"norad_id": 40069, "orbit": "Polar LEO"},
    "METEOR-M 2-3": {"norad_id": 57166, "orbit": "Polar LEO"},
    "METEOR-M 2-4": {"norad_id": 59051, "orbit": "Polar LEO"},
    "INSAT-3DS": {"norad_id": 58990, "orbit": "Geostationary"},
    "GOES-19": {"norad_id": 60133, "orbit": "Geostationary"},
    "NOAA-20": {"norad_id": 43013, "orbit": "Polar LEO"},
    "NOAA-21": {"norad_id": 54234, "orbit": "Polar LEO"},
}

def satellite_catalog_names():
    return list(SATELLITE_CATALOG)

def satellite_catalog_entry(name):
    normalized = "".join(c for c in name.casefold() if c.isalnum())
    for display_name, entry in SATELLITE_CATALOG.items():
        candidate = "".join(c for c in display_name.casefold() if c.isalnum())
        if normalized == candidate:
            return display_name, entry
    return name, None
PROJECT_DIR = Path(__file__).resolve().parent

FALLBACK_TLE = PROJECT_DIR / "satellite_data" / "meteor_m_2.tle"
TLE_TIMEOUT = 10

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
# TLE FUNCTIONS
# --------------------------------------------------

def parse_tle_text(text):
    """Convert three-line TLE records into Skyfield satellites."""

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    satellites = []

    for index in range(len(lines) - 2):
        name = lines[index]
        line1 = lines[index + 1]
        line2 = lines[index + 2]

        if line1.startswith("1 ") and line2.startswith("2 "):
            satellite = EarthSatellite(
                line1,
                line2,
                name,
                timescale
            )
            satellites.append(satellite)

    return satellites


def load_remote_satellites(norad_id=None):
    """Download current TLE data, optionally for one NORAD catalog number."""

    url = CELESTRAK_CATNR_URL.format(norad_id=int(norad_id)) if norad_id is not None else TLE_URL
    request = Request(
        url,
        headers={"User-Agent": "SatelliteTrackingGroundStation/1.0"}
    )

    with urlopen(request, timeout=TLE_TIMEOUT) as response:
        tle_text = response.read().decode("utf-8")

    satellites = parse_tle_text(tle_text)

    if not satellites:
        raise ValueError("CelesTrak returned no valid TLE records.")

    return satellites


def load_fallback_satellite(name):
    """Load the bundled METEOR-M 2 TLE file."""

    if not FALLBACK_TLE.exists():
        raise FileNotFoundError(
            f"Fallback TLE file not found: {FALLBACK_TLE}"
        )

    tle_text = FALLBACK_TLE.read_text(encoding="utf-8")
    satellites = parse_tle_text(tle_text)

    for satellite in satellites:
        if satellite.name.casefold() == name.casefold():
            print(
                "WARNING: Using bundled fallback TLE. "
                "Orbital predictions may be less accurate."
            )
            return satellite

    raise ValueError(
        f"Satellite '{name}' was not found in the fallback TLE."
    )


# --------------------------------------------------
# SATELLITE FUNCTIONS
# --------------------------------------------------

def load_satellite(name, refresh_tle=False):
    """Load current CelesTrak TLE data for a selected catalogue satellite."""
    display_name, entry = satellite_catalog_entry(name)

    try:
        if entry:
            satellites = load_remote_satellites(entry["norad_id"])
            satellite = satellites[0]
            actual_id = int(satellite.model.satnum)
            if actual_id != int(entry["norad_id"]):
                raise ValueError(
                    f"CelesTrak returned NORAD {actual_id}; expected {entry['norad_id']}."
                )
            print(f"Satellite data source: CelesTrak (NORAD {entry['norad_id']})")
            return satellite

        satellites = load_remote_satellites()
        normalized = "".join(c for c in name.casefold() if c.isalnum())
        for satellite in satellites:
            candidate = "".join(c for c in satellite.name.casefold() if c.isalnum())
            if candidate == normalized:
                print("Satellite data source: CelesTrak weather group")
                return satellite
        raise ValueError(f"Satellite '{name}' was not found in CelesTrak.")

    except Exception as error:
        print(f"CelesTrak unavailable: {error}")
        if display_name == DEFAULT_SATELLITE:
            print("Trying local METEOR-M 2 fallback TLE...")
            return load_fallback_satellite(DEFAULT_SATELLITE)
        raise RuntimeError(
            f"Could not retrieve current TLE for {display_name} from CelesTrak. "
            "Check the network and try again."
        ) from error


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

    if (
        getattr(args, "min_elevation", 0) < 0
        or getattr(args, "min_elevation", 0) > 90
    ):
        parser.error("Minimum elevation must be between 0 and 90.")

    try:
        args.handler(args)

    except (OSError, ValueError, RuntimeError) as error:
        raise SystemExit(f"Error: {error}") from error


if __name__ == "__main__":
    main()
