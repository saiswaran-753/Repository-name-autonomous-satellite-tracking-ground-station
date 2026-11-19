
import argparse
import csv
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path


# --------------------------------------------------
# ANGLE AND MOTOR FUNCTIONS
# --------------------------------------------------

def normalise_pan(angle):
    return angle % 360.0


def angular_difference(target, actual):
    return (target - actual + 180.0) % 360.0 - 180.0


def clamp(value, minimum, maximum):
    return max(minimum, min(value, maximum))


def move_motor(current, target, max_step):
    difference = target - current

    if abs(difference) <= max_step:
        return target

    return current + math.copysign(max_step, difference)


def move_pan_motor(current, target, max_step):
    difference = angular_difference(target, current)

    if abs(difference) <= max_step:
        return normalise_pan(target)

    return normalise_pan(
        current + math.copysign(max_step, difference)
    )


def calculate_pointing_error(
    target_pan, target_tilt, actual_pan, actual_tilt
):
    pan_error = angular_difference(target_pan, actual_pan)
    tilt_error = target_tilt - actual_tilt

    p1 = math.radians(target_pan)
    p2 = math.radians(actual_pan)
    t1 = math.radians(target_tilt)
    t2 = math.radians(actual_tilt)

    cosine = (
        math.sin(t1) * math.sin(t2)
        + math.cos(t1) * math.cos(t2) * math.cos(p1 - p2)
    )

    total_error = math.degrees(
        math.acos(clamp(cosine, -1.0, 1.0))
    )

    return pan_error, tilt_error, total_error


# --------------------------------------------------
# TIME FUNCTIONS
# --------------------------------------------------

def timestamp_seconds(value):
    parsed = datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )

    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include a timezone.")

    return parsed.timestamp()


def format_timestamp(seconds):
    return datetime.fromtimestamp(
        seconds, tz=timezone.utc
    ).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")


# --------------------------------------------------
# LOAD SATELLITE DATA
# --------------------------------------------------

def load_samples(input_file):

    required = {
        "timestamp_utc",
        "azimuth_degrees",
        "elevation_degrees"
    }

    samples = []
    skipped = 0

    with input_file.open(
        "r", newline="", encoding="utf-8"
    ) as file:

        reader = csv.DictReader(file)

        if reader.fieldnames is None:
            raise ValueError("CSV has no header.")

        missing = required - set(reader.fieldnames)

        if missing:
            raise ValueError(
                f"Missing CSV columns: {', '.join(sorted(missing))}"
            )

        for row in reader:
            try:
                timestamp = row["timestamp_utc"]
                time_value = timestamp_seconds(timestamp)

                pan = float(row["azimuth_degrees"])
                tilt = float(row["elevation_degrees"])

                if not math.isfinite(pan) or not math.isfinite(tilt):
                    raise ValueError("Invalid satellite position.")

                if not -90 <= tilt <= 90:
                    raise ValueError("Invalid elevation.")

                samples.append({
                    "timestamp": timestamp,
                    "time": time_value,
                    "pan": normalise_pan(pan),
                    "tilt": tilt
                })

            except (ValueError, TypeError, AttributeError):
                skipped += 1

    if not samples:
        raise ValueError("No valid satellite samples found.")

    samples.sort(key=lambda item: item["time"])

    for i in range(1, len(samples)):
        if samples[i]["time"] <= samples[i - 1]["time"]:
            raise ValueError("Timestamps must be unique and increasing.")

    return samples, skipped


# --------------------------------------------------
# PRE-POSITIONING
# --------------------------------------------------

def calculate_preparation_time(
    home_pan, home_tilt, target_pan, target_tilt,
    pan_speed, tilt_speed
):
    pan_distance = abs(
        angular_difference(target_pan, home_pan)
    )

    tilt_distance = abs(target_tilt - home_tilt)

    pan_time = pan_distance / pan_speed
    tilt_time = tilt_distance / tilt_speed

    return (
        pan_distance,
        tilt_distance,
        pan_time,
        tilt_time,
        max(pan_time, tilt_time)
    )


def simulate_movement(
    pan, tilt, target_pan, target_tilt,
    pan_speed, tilt_speed, seconds, step
):
    remaining = seconds

    while remaining > 1e-9:
        dt = min(step, remaining)

        pan = move_pan_motor(
            pan, target_pan, pan_speed * dt
        )

        tilt = move_motor(
            tilt, target_tilt, tilt_speed * dt
        )

        tilt = clamp(tilt, 0.0, 90.0)
        remaining -= dt

    return pan, tilt


# --------------------------------------------------
# TELEMETRY
# --------------------------------------------------

def make_record(
    timestamp, phase, status,
    target_pan, target_tilt,
    actual_pan, actual_tilt
):
    pan_error, tilt_error, total_error = calculate_pointing_error(
        target_pan, target_tilt,
        actual_pan, actual_tilt
    )

    return {
        "timestamp_utc": timestamp,
        "phase": phase,
        "target_pan": f"{target_pan:.4f}",
        "target_tilt": f"{target_tilt:.4f}",
        "actual_pan": f"{actual_pan:.4f}",
        "actual_tilt": f"{actual_tilt:.4f}",
        "pan_error": f"{pan_error:.4f}",
        "tilt_error": f"{tilt_error:.4f}",
        "pointing_error_deg": f"{total_error:.4f}",
        "tracking_status": status
    }


# --------------------------------------------------
# COMPLETE SATELLITE LIFECYCLE
# --------------------------------------------------

def run_simulation(args):

    samples, skipped = load_samples(args.input)

    home_pan = normalise_pan(args.home_pan)
    home_tilt = args.home_tilt

    # Find the first sample above the elevation threshold.
    active_indices = [
        i for i, sample in enumerate(samples)
        if sample["tilt"] >= args.minimum_elevation
    ]

    if not active_indices:
        raise ValueError(
            "No satellite samples reach the minimum elevation."
        )

    first_active = active_indices[0]
    last_active = active_indices[-1]

    aos_sample = samples[first_active]

    target_pan = aos_sample["pan"]
    target_tilt = aos_sample["tilt"]

    available_buffer = (
        aos_sample["time"] - samples[0]["time"]
    )

    available_time = (
        available_buffer
        if args.prep_lead_seconds is None
        else args.prep_lead_seconds
    )

    # Calculate preparation requirements.
    (
        pan_distance,
        tilt_distance,
        pan_time,
        tilt_time,
        required_time
    ) = calculate_preparation_time(
        home_pan, home_tilt,
        target_pan, target_tilt,
        args.pan_speed, args.tilt_speed
    )

    # Start at home and simulate preparation.
    actual_pan = home_pan
    actual_tilt = home_tilt

    prep_duration = min(available_time, available_buffer)

    prep_start = aos_sample["time"] - prep_duration

    actual_pan, actual_tilt = simulate_movement(
        actual_pan, actual_tilt,
        target_pan, target_tilt,
        args.pan_speed, args.tilt_speed,
        prep_duration, args.simulation_step
    )

    _, _, prep_error = calculate_pointing_error(
        target_pan, target_tilt,
        actual_pan, actual_tilt
    )

    ready = prep_error <= args.tracking_tolerance

    # Output collections.
    motor_rows = []
    telemetry = []

    # Record waiting state.
    telemetry.append(
        make_record(
            format_timestamp(samples[0]["time"]),
            "WAITING", "WAITING",
            home_pan, home_tilt,
            home_pan, home_tilt
        )
    )

    # Record preparation at its completion.
    if prep_duration > 0:
        telemetry.append(
            make_record(
                format_timestamp(aos_sample["time"]),
                "PREPOSITIONING",
                "READY" if ready else "NOT READY",
                target_pan, target_tilt,
                actual_pan, actual_tilt
            )
        )

    # Satellite pass lifecycle.
    state = "WAITING"
    previous_time = aos_sample["time"]

    acquired = False
    tracking_count = 0
    acquiring_count = 0
    signal_lost = False
    return_started = False
    return_completed = False

    for index, sample in enumerate(samples):

        current_time = sample["time"]
        target_pan = sample["pan"]
        target_tilt = sample["tilt"]

        above_threshold = (
            args.minimum_elevation <= target_tilt <= 90
        )

        # Ignore samples before AOS.
        if index < first_active:
            continue

        elapsed = max(0.0, current_time - previous_time)

        if index == first_active:
            # Use the result of pre-positioning.
            pass

        elif above_threshold and not signal_lost:

            actual_pan, actual_tilt = simulate_movement(
                actual_pan, actual_tilt,
                target_pan, target_tilt,
                args.pan_speed, args.tilt_speed,
                elapsed, args.simulation_step
            )

        elif not above_threshold and acquired:

            # First sample below the threshold means LOS.
            if not signal_lost:
                signal_lost = True
                state = "SIGNAL_LOST"

                telemetry.append(
                    make_record(
                        sample["timestamp"],
                        "LOSS_OF_SIGNAL",
                        "SIGNAL_LOST",
                        home_pan, home_tilt,
                        actual_pan, actual_tilt
                    )
                )

                previous_time = current_time
                continue

            # After LOS, return antenna towards home.
            return_started = True
            state = "RETURNING_HOME"

            actual_pan, actual_tilt = simulate_movement(
                actual_pan, actual_tilt,
                home_pan, home_tilt,
                args.pan_speed, args.tilt_speed,
                elapsed, args.simulation_step
            )

            _, _, home_error = calculate_pointing_error(
                home_pan, home_tilt,
                actual_pan, actual_tilt
            )

            if home_error <= 0.01:
                actual_pan = home_pan
                actual_tilt = home_tilt
                state = "HOME"
                return_completed = True

        else:
            # Satellite is below threshold before AOS.
            previous_time = current_time
            continue

        previous_time = current_time

        # Evaluate tracking or acquisition.
        if above_threshold and not signal_lost:

            _, _, pointing_error = calculate_pointing_error(
                target_pan, target_tilt,
                actual_pan, actual_tilt
            )

            if pointing_error <= args.tracking_tolerance:
                state = "TRACKING"
                acquired = True
                tracking_count += 1
            else:
                state = "ACQUIRING"
                acquiring_count += 1

            telemetry.append(
                make_record(
                    sample["timestamp"],
                    "TRACKING",
                    state,
                    target_pan, target_tilt,
                    actual_pan, actual_tilt
                )
            )

        elif return_started:

            telemetry.append(
                make_record(
                    sample["timestamp"],
                    "RETURN",
                    state,
                    home_pan, home_tilt,
                    actual_pan, actual_tilt
                )
            )

        motor_rows.append({
            "timestamp_utc": sample["timestamp"],
            "pan_degrees": f"{actual_pan:.4f}",
            "tilt_degrees": f"{actual_tilt:.4f}"
        })

    # Save outputs.
    save_csv(
        args.output,
        ["timestamp_utc", "pan_degrees", "tilt_degrees"],
        motor_rows
    )

    fields = [
        "timestamp_utc",
        "phase",
        "target_pan",
        "target_tilt",
        "actual_pan",
        "actual_tilt",
        "pan_error",
        "tilt_error",
        "pointing_error_deg",
        "tracking_status"
    ]

    save_csv(args.telemetry, fields, telemetry)

    tracking_errors = [
        float(row["pointing_error_deg"])
        for row in telemetry
        if row["phase"] == "TRACKING"
    ]

    average_error = (
        sum(tracking_errors) / len(tracking_errors)
        if tracking_errors else 0.0
    )

    maximum_error = (
        max(tracking_errors)
        if tracking_errors else 0.0
    )

    # Summary.
    print("\n========================================")
    print(" AUTONOMOUS SATELLITE GROUND STATION")
    print("========================================")

    print(f"Input CSV:             {args.input}")
    print(f"Motor output:          {args.output}")
    print(f"Telemetry output:      {args.telemetry}")

    print("----------------------------------------")
    print("PRE-POSITIONING")

    print(f"Home pan:              {home_pan:.2f}°")
    print(f"Home tilt:             {home_tilt:.2f}°")

    print(f"Target pan:            {target_pan:.4f}°")
    print(f"Target tilt:           {aos_sample['tilt']:.4f}°")

    print(f"Pan preparation:       {pan_time:.2f} sec")
    print(f"Tilt preparation:      {tilt_time:.2f} sec")
    print(f"Required preparation:  {required_time:.2f} sec")
    print(f"Available preparation: {available_time:.2f} sec")

    print(
        "Antenna readiness:    "
        + ("READY" if ready else "NOT READY")
    )

    print("----------------------------------------")
    print("SATELLITE LIFECYCLE")

    print(f"AOS:                   {aos_sample['timestamp']}")
    print(f"LOS:                   {samples[last_active]['timestamp']}")
    print(f"Tracking samples:      {tracking_count}")
    print(f"Acquiring samples:     {acquiring_count}")
    print(f"Signal lost detected:  {'YES' if signal_lost else 'NO'}")
    print(f"Return to home:        {'COMPLETE' if return_completed else 'INCOMPLETE'}")

    print("----------------------------------------")
    print("TRACKING PERFORMANCE")

    print(f"Average pointing error: {average_error:.4f}°")
    print(f"Maximum pointing error: {maximum_error:.4f}°")

    print("----------------------------------------")
    print(f"Skipped CSV rows:      {skipped}")
    print(f"Pan speed:             {args.pan_speed}°/sec")
    print(f"Tilt speed:            {args.tilt_speed}°/sec")

    print("========================================\n")


# --------------------------------------------------
# CSV OUTPUT
# --------------------------------------------------

def save_csv(path, fields, rows):

    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open(
        "w", newline="", encoding="utf-8"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fields
        )

        writer.writeheader()
        writer.writerows(rows)


# --------------------------------------------------
# COMMAND LINE
# --------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description="Autonomous satellite antenna lifecycle simulator."
    )

    parser.add_argument(
        "--input",
        type=Path,
        default=Path("output/meteor_next_pass.csv")
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/motor_commands.csv")
    )

    parser.add_argument(
        "--telemetry",
        type=Path,
        default=Path("output/tracking_telemetry.csv")
    )

    parser.add_argument(
        "--minimum-elevation",
        type=float,
        default=10.0
    )

    parser.add_argument(
        "--pan-speed",
        type=float,
        default=5.0
    )

    parser.add_argument(
        "--tilt-speed",
        type=float,
        default=3.0
    )

    parser.add_argument(
        "--tracking-tolerance",
        type=float,
        default=2.0
    )

    parser.add_argument(
        "--home-pan",
        "--initial-pan",
        dest="home_pan",
        type=float,
        default=0.0
    )

    parser.add_argument(
        "--home-tilt",
        "--initial-tilt",
        dest="home_tilt",
        type=float,
        default=0.0
    )

    parser.add_argument(
        "--prep-lead-seconds",
        type=float,
        default=None
    )

    parser.add_argument(
        "--simulation-step",
        type=float,
        default=1.0
    )

    args = parser.parse_args()

    if not 0 <= args.minimum_elevation <= 90:
        parser.error("Minimum elevation must be between 0 and 90.")

    if args.pan_speed <= 0 or args.tilt_speed <= 0:
        parser.error("Motor speeds must be greater than zero.")

    if not all(math.isfinite(x) for x in (
        args.pan_speed, args.tilt_speed,
        args.home_pan, args.home_tilt,
        args.tracking_tolerance, args.simulation_step
    )):
        parser.error("Numeric arguments must be finite.")

    if not 0 <= args.home_tilt <= 90:
        parser.error("Home tilt must be between 0 and 90.")

    if args.tracking_tolerance < 0:
        parser.error("Tracking tolerance cannot be negative.")

    if args.simulation_step <= 0:
        parser.error("Simulation step must be positive.")

    if args.prep_lead_seconds is not None:
        if not math.isfinite(args.prep_lead_seconds) or args.prep_lead_seconds < 0:
            parser.error("Preparation time must be finite and non-negative.")

    try:
        run_simulation(args)

    except (OSError, ValueError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
