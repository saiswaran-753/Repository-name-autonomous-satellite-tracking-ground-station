# Autonomous Satellite Tracking Ground Station — Software Prototype

## What this prototype demonstrates

This Python software prototype downloads current weather-satellite orbital data, calculates the satellite’s position for a configurable ground station, predicts the next visible pass, and creates simulated antenna motor commands.

```text
Orbital data → tracker.py → pass CSV → simulate_rotator.py → motor-command CSV
```

The prototype does **not** drive physical motors yet. The generated pan and tilt values are ready for a future microcontroller and antenna-rotator stage.

## Requirements

- Windows 11
- Python 3.12
- Internet connection when using `--refresh-tle`

Install the dependency:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run the position calculation

```powershell
.\.venv\Scripts\python.exe tracker.py position --satellite "METEOR-M 2" --latitude 12.9716 --longitude 77.5946 --elevation-m 920 --refresh-tle
```

This prints UTC time, azimuth, elevation, range, and whether the satellite is above the horizon.

## Predict the next pass

```powershell
.\.venv\Scripts\python.exe tracker.py pass --satellite "METEOR-M 2" --latitude 12.9716 --longitude 77.5946 --elevation-m 920 --hours 48 --min-elevation 10 --sample-seconds 5 --csv output\meteor_next_pass.csv --refresh-tle
```

The output CSV includes `timestamp_utc`, `azimuth_degrees`, `elevation_degrees`, and `range_km`.

## Generate simulated antenna commands

```powershell
.\.venv\Scripts\python.exe simulate_rotator.py --input output\meteor_next_pass.csv --output output\motor_commands.csv
```

The output CSV contains `timestamp_utc`, `pan_degrees`, and `tilt_degrees`. `pan_degrees` represents the future antenna’s horizontal rotation; `tilt_degrees` represents its vertical elevation.

## Included demonstration results

The archive includes `meteor_next_pass.csv` and its corresponding `motor_commands.csv`. These files show that the complete software data flow has run successfully.

