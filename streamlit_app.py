"""Deployable web dashboard for the satellite-tracking software prototype."""

from datetime import timedelta

import pandas as pd
import streamlit as st
from skyfield.api import wgs84

import tracker


st.set_page_config(
    page_title="Satellite Tracking Ground Station",
    page_icon="🛰️",
    layout="wide",
)

st.title("🛰️ Autonomous Satellite Tracking Ground Station")
st.caption("Software prototype: live pass prediction and simulated antenna commands")


def build_pass_data(latitude, longitude, elevation_m, satellite_name, hours, min_elevation, sample_seconds, refresh_tle):
    satellite = tracker.load_satellite(satellite_name, refresh_tle)
    observer = wgs84.latlon(latitude, longitude, elevation_m=elevation_m)
    current_time = tracker.timescale.now()
    end_time = tracker.timescale.from_datetime(
        tracker.as_utc_datetime(current_time) + timedelta(hours=hours)
    )

    rise_time, set_time = tracker.find_next_complete_pass(
        satellite,
        observer,
        current_time,
        end_time,
        min_elevation,
    )
    samples = tracker.sample_pass(
        satellite,
        observer,
        rise_time,
        set_time,
        sample_seconds,
    )

    pass_data = pd.DataFrame(
        samples,
        columns=[
            "timestamp_utc",
            "azimuth_degrees",
            "elevation_degrees",
            "range_km",
        ],
    )
    pass_data["timestamp_utc"] = pd.to_datetime(pass_data["timestamp_utc"], utc=True)

    motor_data = pass_data[pass_data["elevation_degrees"] >= 0].copy()
    motor_data["pan_degrees"] = motor_data["azimuth_degrees"] % 360
    motor_data["tilt_degrees"] = motor_data["elevation_degrees"].clip(0, 90)
    motor_data = motor_data[["timestamp_utc", "pan_degrees", "tilt_degrees"]]

    current_altitude, current_azimuth, current_range = tracker.geometry(
        satellite,
        observer,
        current_time,
    )

    return {
        "satellite": satellite.name,
        "current_time": tracker.utc_text(current_time),
        "current_altitude": float(current_altitude),
        "current_azimuth": float(current_azimuth),
        "current_range": float(current_range),
        "rise_time": tracker.utc_text(rise_time),
        "set_time": tracker.utc_text(set_time),
        "pass_data": pass_data,
        "motor_data": motor_data,
    }


with st.sidebar:
    st.header("Ground station settings")
    latitude = st.number_input("Latitude (degrees north)", value=12.9716, format="%.4f")
    longitude = st.number_input("Longitude (degrees east)", value=77.5946, format="%.4f")
    elevation_m = st.number_input("Elevation above sea level (m)", min_value=0.0, value=920.0)
    search_hours = st.slider("Search window (hours)", min_value=12, max_value=72, value=48, step=12)
    minimum_elevation = st.slider("Minimum elevation (degrees)", min_value=0, max_value=30, value=10)
    sample_seconds = st.select_slider("Sample interval (seconds)", options=[1, 5, 10, 15, 30], value=5)
    refresh_tle = st.checkbox("Try to download current orbital data", value=False)
    st.caption("The dashboard uses bundled METEOR-M 2 data when the live CelesTrak feed is unavailable.")
    predict = st.button("Predict next pass", type="primary", use_container_width=True)


if predict:
    with st.spinner("Calculating satellite pass and antenna commands..."):
        try:
            st.session_state["result"] = build_pass_data(
                latitude,
                longitude,
                elevation_m,
                "METEOR-M 2",
                search_hours,
                float(minimum_elevation),
                sample_seconds,
                refresh_tle,
            )
        except (OSError, ValueError, RuntimeError) as error:
            st.error(f"Could not calculate a pass: {error}")


if "result" not in st.session_state:
    st.info("Set the ground-station location, then select **Predict next pass**.")
    st.stop()


result = st.session_state["result"]
pass_data = result["pass_data"]
motor_data = result["motor_data"]

st.subheader(f"Tracking result: {result['satellite']}")
metric_a, metric_b, metric_c = st.columns(3)
metric_a.metric("Peak elevation", f"{pass_data['elevation_degrees'].max():.1f}°")
metric_b.metric("Current azimuth", f"{result['current_azimuth']:.1f}°")
metric_c.metric("Current range", f"{result['current_range']:.0f} km")

st.write(f"**Pass window (UTC):** {result['rise_time']} to {result['set_time']}")
st.write(f"**Current elevation:** {result['current_altitude']:.1f}°")

st.subheader("Predicted antenna path")
chart_data = pass_data.set_index("timestamp_utc")[["azimuth_degrees", "elevation_degrees"]]
st.line_chart(chart_data)

st.subheader("Simulated antenna motor commands")
st.caption("Pan is horizontal rotation; tilt is vertical rotation. This software does not drive physical motors yet.")
st.dataframe(motor_data, use_container_width=True, hide_index=True)

pass_csv = pass_data.to_csv(index=False).encode("utf-8")
motor_csv = motor_data.to_csv(index=False).encode("utf-8")
download_a, download_b = st.columns(2)
download_a.download_button(
    "Download pass CSV",
    data=pass_csv,
    file_name="meteor_next_pass.csv",
    mime="text/csv",
    use_container_width=True,
)
download_b.download_button(
    "Download motor commands CSV",
    data=motor_csv,
    file_name="motor_commands.csv",
    mime="text/csv",
    use_container_width=True,
)

