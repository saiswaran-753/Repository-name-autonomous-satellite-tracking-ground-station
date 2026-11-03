"""Convert satellite pass CSV data into simulated antenna motor commands.

This program does not control real motors yet.
It creates pan and tilt commands for future servo/stepper-motor control.
"""

import argparse
import csv
from pathlib import Path


def clamp(value, minimum, maximum):
    """Keep a value inside a safe range."""
    return max(minimum, min(value, maximum))


def normalise_pan(azimuth):
    """Convert azimuth into a pan angle from 0° to less than 360°."""
    return azimuth % 360.0


def convert_to_motor_commands(input_file, output_file, minimum_elevation):
    required_columns = {
        "timestamp_utc",
        "azimuth_degrees",
        "elevation_degrees",
    }

    with input_file.open("r", newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)

        if reader.fieldnames is None:
            raise ValueError("The input CSV has no header row.")

        missing_columns = required_columns - set(reader.fieldnames)

        if missing_columns:
            missing_text = ", ".join(sorted(missing_columns))
            raise ValueError(f"Input CSV is missing: {missing_text}")

        motor_rows = []
        skipped_rows = 0

        for row in reader:
            try:
                azimuth = float(row["azimuth_degrees"])
                elevation = float(row["elevation_degrees"])
            except (TypeError, ValueError):
                skipped_rows += 1
                continue

            # Do not create antenna commands when satellite is below horizon.
            if elevation < minimum_elevation:
                skipped_rows += 1
                continue

            pan_angle = normalise_pan(azimuth)
            tilt_angle = clamp(elevation, 0.0, 90.0)

            motor_rows.append({
                "timestamp_utc": row["timestamp_utc"],
                "pan_degrees": f"{pan_angle:.2f}",
                "tilt_degrees": f"{tilt_angle:.2f}",
            })

    if not motor_rows:
        raise ValueError(
            "No valid motor commands were created. "
            "Try lowering --minimum-elevation."
        )

    output_file.parent.mkdir(parents=True, exist_ok=True)

    with output_file.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "timestamp_utc",
                "pan_degrees",
                "tilt_degrees",
            ],
        )

        writer.writeheader()
        writer.writerows(motor_rows)

    print("Motor-command simulation complete.")
    print(f"Input file:       {input_file}")
    print(f"Output file:      {output_file}")
    print(f"Commands created: {len(motor_rows)}")
    print(f"Rows skipped:     {skipped_rows}")
    print(f"Minimum elevation: {minimum_elevation:.1f}°")


def main():
    parser = argparse.ArgumentParser(
        description="Create simulated antenna pan and tilt commands from a satellite-pass CSV."
    )

    parser.add_argument(
        "--input",
        type=Path,
        default=Path("output/meteor_next_pass.csv"),
        help="Input pass CSV file.",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/motor_commands.csv"),
        help="Output motor-command CSV file.",
    )

    parser.add_argument(
        "--minimum-elevation",
        type=float,
        default=0.0,
        help="Ignore satellite positions below this elevation. Default: 0°.",
    )

    args = parser.parse_args()

    if args.minimum_elevation < 0 or args.minimum_elevation > 90:
        raise SystemExit("--minimum-elevation must be between 0 and 90.")

    try:
        convert_to_motor_commands(
            args.input,
            args.output,
            args.minimum_elevation,
        )
    except (OSError, ValueError) as error:
        raise SystemExit(f"Error: {error}") from error


if __name__ == "__main__":
    main()
