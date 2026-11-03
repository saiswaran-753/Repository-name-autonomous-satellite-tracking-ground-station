# Autonomous Satellite Tracking Ground Station

An undergraduate software prototype that predicts weather-satellite passes and produces simulated pan-and-tilt commands for a future motorized antenna rotator.

## Features

- Downloads current weather-satellite orbital data from CelesTrak.
- Calculates a satellite’s azimuth, elevation, and range from a configurable ground station.
- Predicts the next observable pass of **METEOR-M 2**.
- Exports timestamped antenna-pointing samples to CSV.
- Generates simulated antenna pan and tilt commands.
- Provides a deployable Streamlit dashboard.

## Project files

| File | Purpose |
| --- | --- |
| `tracker.py` | Satellite geometry and pass prediction |
| `simulate_rotator.py` | Converts pass data into pan/tilt motor commands |
| `streamlit_app.py` | Interactive web dashboard |
| `requirements.txt` | Python dependencies |
| `DEPLOYMENT.md` | Local-run and Streamlit deployment guide |

## Run locally

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

Open the local URL printed in the terminal, normally `http://localhost:8501`.

## Command-line prototype

```powershell
.\.venv\Scripts\python.exe tracker.py position --satellite "METEOR-M 2" --latitude 12.9716 --longitude 77.5946 --elevation-m 920 --refresh-tle
```

```powershell
.\.venv\Scripts\python.exe tracker.py pass --satellite "METEOR-M 2" --latitude 12.9716 --longitude 77.5946 --elevation-m 920 --hours 48 --min-elevation 10 --sample-seconds 5 --csv output\meteor_next_pass.csv --refresh-tle
```

```powershell
.\.venv\Scripts\python.exe simulate_rotator.py --input output\meteor_next_pass.csv --output output\motor_commands.csv
```

## Current scope

This is a software prototype. It predicts pointing data and simulates motor commands; connecting the commands to an Arduino/ESP32 and physical antenna rotator is the next hardware phase.

