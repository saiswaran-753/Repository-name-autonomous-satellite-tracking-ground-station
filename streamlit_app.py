
"""Autonomous Satellite Tracking Ground Station Dashboard."""

import argparse
import contextlib
import io
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from skyfield.api import wgs84

import tracker
import simulate_rotator


# ==================================================
# PROJECT CONFIGURATION
# ==================================================

PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_DIR / "output"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PASS_FILE = OUTPUT_DIR / "dashboard_pass.csv"
MOTOR_FILE = OUTPUT_DIR / "dashboard_motor_commands.csv"
TELEMETRY_FILE = OUTPUT_DIR / "dashboard_tracking_telemetry.csv"


# ==================================================
# PAGE CONFIGURATION
# ==================================================

st.set_page_config(
    page_title="Satellite Tracking Ground Station",
    page_icon="🛰️",
    layout="wide"
)

st.title("🛰️ Autonomous Satellite Tracking Ground Station")

st.caption(
    "Satellite prediction | Antenna simulation | Tracking telemetry"
)

st.warning(
    "SOFTWARE SIMULATION ONLY — This application does not control "
    "physical motors, receive RF signals or decode satellite imagery."
)


# ==================================================
# HELPER FUNCTIONS
# ==================================================

def add_angle_trace(fig, timestamps, values, name, color):
    """Plot physical pan angles and break lines at 0/360 crossings."""

    values = np.asarray(values, dtype=float)
    timestamps = pd.to_datetime(timestamps, utc=True)

    broken_values = values.copy()

    if len(values) > 1:
        wrap_indices = np.where(
            np.abs(np.diff(values)) > 180
        )[0] + 1

        broken_values[wrap_indices] = np.nan

    fig.add_trace(
        go.Scatter(
            x=timestamps,
            y=broken_values,
            mode="lines",
            name=name,
            line=dict(width=2, color=color),
            connectgaps=False
        )
    )


def lifecycle_count(telemetry, status):
    return int(
        (telemetry["tracking_status"] == status).sum()
    )


# ==================================================
# SATELLITE AND MOTOR PROCESSING
# ==================================================

def build_dashboard(
    latitude,
    longitude,
    elevation_m,
    satellite_name,
    hours,
    minimum_elevation,
    sample_seconds,
    refresh_tle,
    home_pan,
    home_tilt,
    pan_speed,
    tilt_speed,
    prep_lead,
    tolerance,
    simulation_step
):

    # 1. Load satellite
    satellite = tracker.load_satellite(
        satellite_name,
        refresh_tle
    )

    observer = wgs84.latlon(
        latitude,
        longitude,
        elevation_m=elevation_m
    )

    # 2. Find next pass
    current_time = tracker.timescale.now()

    end_time = tracker.timescale.from_datetime(
        tracker.as_utc_datetime(current_time)
        + timedelta(hours=hours)
    )

    rise_time, set_time = tracker.find_next_complete_pass(
        satellite,
        observer,
        current_time,
        end_time,
        minimum_elevation
    )

    # 3. Generate satellite samples
    samples = tracker.sample_pass(
        satellite,
        observer,
        rise_time,
        set_time,
        sample_seconds,
        padding_seconds=60
    )

    pass_data = pd.DataFrame(
        samples,
        columns=[
            "timestamp_utc",
            "azimuth_degrees",
            "elevation_degrees",
            "range_km"
        ]
    )

    pass_data["timestamp_utc"] = pd.to_datetime(
        pass_data["timestamp_utc"],
        utc=True
    )

    # 4. Save simulator input
    pass_data.to_csv(
        PASS_FILE,
        index=False,
        date_format="%Y-%m-%dT%H:%M:%SZ"
    )

    # 5. Prepare simulator arguments
    simulation_args = argparse.Namespace(
        input=PASS_FILE,
        output=MOTOR_FILE,
        telemetry=TELEMETRY_FILE,
        minimum_elevation=float(minimum_elevation),
        pan_speed=float(pan_speed),
        tilt_speed=float(tilt_speed),
        tracking_tolerance=float(tolerance),
        home_pan=float(home_pan),
        home_tilt=float(home_tilt),
        prep_lead_seconds=float(prep_lead),
        simulation_step=float(simulation_step)
    )

    # 6. Run lifecycle simulation
    console_output = io.StringIO()

    with contextlib.redirect_stdout(console_output):
        simulate_rotator.run_simulation(simulation_args)

    # 7. Read generated files
    motor_data = pd.read_csv(MOTOR_FILE)
    telemetry = pd.read_csv(TELEMETRY_FILE)

    if telemetry.empty:
        raise ValueError("Simulator generated empty telemetry.")

    telemetry["timestamp_utc"] = pd.to_datetime(
        telemetry["timestamp_utc"],
        utc=True
    )

    numeric_columns = [
        "target_pan",
        "target_tilt",
        "actual_pan",
        "actual_tilt",
        "pan_error",
        "tilt_error",
        "pointing_error_deg"
    ]

    for column in numeric_columns:
        telemetry[column] = pd.to_numeric(
            telemetry[column],
            errors="coerce"
        )

    # 8. Current satellite position
    altitude, azimuth, distance = tracker.geometry(
        satellite,
        observer,
        current_time
    )

    catalog_name, catalog_entry = tracker.satellite_catalog_entry(satellite_name)
    tle_epoch = tracker.utc_text(satellite.epoch)

    return {
        "satellite": catalog_name if catalog_entry else satellite.name,
        "norad_id": int(satellite.model.satnum),
        "orbit_type": catalog_entry["orbit"] if catalog_entry else "Provider catalogue",
        "tle_epoch": tle_epoch,
        "current_altitude": float(altitude),
        "current_azimuth": float(azimuth),
        "current_range": float(distance),
        "rise_time": tracker.utc_text(rise_time),
        "set_time": tracker.utc_text(set_time),
        "pass_data": pass_data,
        "motor_data": motor_data,
        "telemetry": telemetry,
        "simulation_summary": console_output.getvalue()
    }


# ==================================================
# SIDEBAR SETTINGS
# ==================================================

with st.sidebar:

    st.header("📍 Ground Station")

    latitude = st.number_input(
        "Latitude",
        value=17.3850,
        format="%.4f"
    )

    longitude = st.number_input(
        "Longitude",
        value=78.4867,
        format="%.4f"
    )

    elevation_m = st.number_input(
        "Elevation (metres)",
        min_value=0.0,
        value=0.0
    )

    st.divider()

    st.header("🛰️ Satellite Settings")

    satellite_options = tracker.satellite_catalog_names()
    default_index = satellite_options.index(tracker.DEFAULT_SATELLITE)
    satellite_name = st.selectbox(
        "Satellite catalogue",
        options=satellite_options,
        index=default_index,
        help="Select a satellite. Current TLE data is requested from CelesTrak by NORAD catalog number."
    )
    selected_entry = tracker.SATELLITE_CATALOG[satellite_name]
    st.caption(
        f"NORAD ID: {selected_entry['norad_id']} · "
        f"Orbit: {selected_entry['orbit']}"
    )

    search_hours = st.slider(
        "Search window (hours)",
        12, 72, 48, 12
    )

    minimum_elevation = st.slider(
        "Minimum elevation (degrees)",
        0, 30, 10
    )

    sample_seconds = st.select_slider(
        "Sample interval (seconds)",
        options=[1, 5, 10, 15, 30],
        value=5
    )

    refresh_tle = st.checkbox(
        "Download fresh orbital data",
        value=False
    )

    st.divider()

    st.header("⚙️ Motor Settings")

    home_pan = st.number_input(
        "Home pan (degrees)",
        value=0.0
    )

    home_tilt = st.number_input(
        "Home tilt (degrees)",
        min_value=0.0,
        max_value=90.0,
        value=0.0
    )

    pan_speed = st.number_input(
        "Pan speed (degrees/sec)",
        min_value=0.1,
        value=8.0
    )

    tilt_speed = st.number_input(
        "Tilt speed (degrees/sec)",
        min_value=0.1,
        value=5.0
    )

    tracking_tolerance = st.number_input(
        "Tracking tolerance (degrees)",
        min_value=0.0,
        value=2.0
    )

    prep_lead = st.number_input(
        "Preparation lead time (seconds)",
        min_value=0.0,
        value=60.0
    )

    simulation_step = st.number_input(
        "Simulation step (seconds)",
        min_value=0.1,
        value=1.0
    )

    predict = st.button(
        "🚀 Predict and Simulate",
        type="primary",
        use_container_width=True
    )


# ==================================================
# EXECUTE SIMULATION
# ==================================================

if predict:

    with st.spinner(
        "Predicting satellite pass and simulating antenna..."
    ):

        try:

            result = build_dashboard(
                latitude,
                longitude,
                elevation_m,
                satellite_name,
                search_hours,
                minimum_elevation,
                sample_seconds,
                refresh_tle,
                home_pan,
                home_tilt,
                pan_speed,
                tilt_speed,
                prep_lead,
                tracking_tolerance,
                simulation_step
            )

            st.session_state["result"] = result

            st.success(
                "Satellite prediction and motor simulation completed!"
            )

        except Exception as error:

            st.error(
                f"Simulation failed: {type(error).__name__}: {error}"
            )


# ==================================================
# DISPLAY RESULTS
# ==================================================

if "result" not in st.session_state:

    st.info(
        "Configure the ground station and motor settings, "
        "then click Predict and Simulate."
    )

    st.stop()


result = st.session_state["result"]

pass_data = result["pass_data"]
motor_data = result["motor_data"]
telemetry = result["telemetry"]


# ==================================================
# SATELLITE INFORMATION
# ==================================================

st.divider()
st.header("📡 Satellite Information")

st.subheader(result["satellite"])

col1, col2, col3 = st.columns(3)

col1.metric(
    "Peak elevation",
    f"{pass_data['elevation_degrees'].max():.2f}°"
)

col2.metric(
    "Current azimuth",
    f"{result['current_azimuth']:.2f}°"
)

col3.metric(
    "Current range",
    f"{result['current_range']:.1f} km"
)

st.write(f"**NORAD catalog ID:** {result['norad_id']}")
st.write(f"**Orbit type:** {result['orbit_type']}")
st.write(f"**TLE epoch (UTC):** {result['tle_epoch']}")
st.caption("Pass predictions use the TLE epoch shown above. TLEs are time-sensitive; refresh before important observations.")
st.write(f"**AOS (UTC):** {result['rise_time']}")
st.write(f"**LOS (UTC):** {result['set_time']}")

st.write(
    f"**Current elevation:** "
    f"{result['current_altitude']:.2f}°"
)


# ==================================================
# ANTENNA READINESS
# ==================================================

st.divider()
st.header("⚙️ Antenna Preparation")

prep_rows = telemetry[
    telemetry["phase"] == "PREPOSITIONING"
]

if not prep_rows.empty:

    prep_status = prep_rows.iloc[-1]["tracking_status"]

    if prep_status == "READY":
        st.success("🟢 ANTENNA READY")
    else:
        st.error("🔴 ANTENNA NOT READY")

else:
    st.info("No pre-positioning record was generated.")


# ==================================================
# LIFECYCLE METRICS
# ==================================================

st.divider()
st.header("🛰️ Satellite Tracking Lifecycle")

tracking_count = lifecycle_count(
    telemetry, "TRACKING"
)

acquiring_count = lifecycle_count(
    telemetry, "ACQUIRING"
)

signal_lost = (
    lifecycle_count(telemetry, "SIGNAL_LOST") > 0
)

home_complete = (
    lifecycle_count(telemetry, "HOME") > 0
)

status_cols = st.columns(4)

status_cols[0].metric(
    "Tracking samples",
    tracking_count
)

status_cols[1].metric(
    "Acquiring samples",
    acquiring_count
)

status_cols[2].metric(
    "Signal lost",
    "YES" if signal_lost else "NO"
)

status_cols[3].metric(
    "Return home",
    "COMPLETE" if home_complete else "INCOMPLETE"
)


# ==================================================
# LIFECYCLE EVENTS
# ==================================================

st.subheader("Lifecycle Events")

event_order = [
    ("WAITING", "WAITING"),
    ("PREPOSITIONING", "READY"),
    ("PREPOSITIONING", "NOT READY"),
    ("TRACKING", "ACQUIRING"),
    ("TRACKING", "TRACKING"),
    ("LOSS_OF_SIGNAL", "SIGNAL_LOST"),
    ("RETURN", "RETURNING_HOME"),
    ("RETURN", "HOME")
]

observed = set(
    zip(
        telemetry["phase"].astype(str),
        telemetry["tracking_status"].astype(str)
    )
)

for phase, status in event_order:

    if (phase, status) in observed:
        st.write(
            f"✓ **{status.replace('_', ' ')}**"
        )


# ==================================================
# TRACKING PERFORMANCE
# ==================================================

tracking_data = telemetry[
    telemetry["phase"] == "TRACKING"
]

tracking_errors = tracking_data[
    "pointing_error_deg"
].dropna()

average_error = (
    tracking_errors.mean()
    if not tracking_errors.empty
    else 0.0
)

maximum_error = (
    tracking_errors.max()
    if not tracking_errors.empty
    else 0.0
)

st.divider()
st.header("🎯 Tracking Performance")

error_a, error_b = st.columns(2)

error_a.metric(
    "Average pointing error",
    f"{average_error:.4f}°"
)

error_b.metric(
    "Maximum pointing error",
    f"{maximum_error:.4f}°"
)


# ==================================================
# ANTENNA PAN CHART
# ==================================================

st.divider()
st.header("📈 Antenna Position Tracking")

chart_data = telemetry.dropna(
    subset=[
        "target_pan",
        "actual_pan",
        "target_tilt",
        "actual_tilt"
    ]
).copy()

if not chart_data.empty:

    # ----------------------------------------------
    # PAN
    # ----------------------------------------------

    st.subheader("Horizontal Rotation – Pan")

    pan_fig = go.Figure()

    add_angle_trace(
        pan_fig,
        chart_data["timestamp_utc"],
        chart_data["target_pan"] % 360,
        "Target Pan",
        "#2196F3"
    )

    add_angle_trace(
        pan_fig,
        chart_data["timestamp_utc"],
        chart_data["actual_pan"] % 360,
        "Actual Pan",
        "#00C853"
    )

    pan_fig.update_layout(
        height=380,
        yaxis=dict(
            title="Pan angle (degrees)",
            range=[0, 360],
            dtick=45
        ),
        xaxis_title="Time (UTC)",
        hovermode="x unified",
        legend_title="Antenna position"
    )

    st.plotly_chart(
        pan_fig,
        use_container_width=True
    )

    st.caption(
        "Physical pan angles are displayed from 0° to 360°. "
        "Lines break at circular wraparound."
    )

    # ----------------------------------------------
    # TILT
    # ----------------------------------------------

    st.subheader("Vertical Movement – Tilt")

    tilt_fig = go.Figure()

    tilt_fig.add_trace(
        go.Scatter(
            x=chart_data["timestamp_utc"],
            y=chart_data["target_tilt"],
            mode="lines",
            name="Target Tilt",
            line=dict(color="#2196F3", width=2)
        )
    )

    tilt_fig.add_trace(
        go.Scatter(
            x=chart_data["timestamp_utc"],
            y=chart_data["actual_tilt"],
            mode="lines",
            name="Actual Tilt",
            line=dict(color="#00C853", width=2)
        )
    )

    tilt_fig.update_layout(
        height=380,
        yaxis=dict(
            title="Tilt angle (degrees)",
            range=[0, 90],
            dtick=10
        ),
        xaxis_title="Time (UTC)",
        hovermode="x unified"
    )

    st.plotly_chart(
        tilt_fig,
        use_container_width=True
    )

else:

    st.info("No antenna position telemetry available.")


# ==================================================
# POINTING ERROR ANALYSIS
# ==================================================

st.divider()
st.header("🎯 Pointing Error Analysis")

error_data = telemetry.dropna(
    subset=["pointing_error_deg"]
).copy()

if not error_data.empty:

    error_fig = go.Figure()

    phases = [
        ("ACQUIRING", "#FF9800"),
        ("TRACKING", "#00C853"),
        ("RETURNING_HOME", "#2196F3")
    ]

    for status, color in phases:

        subset = error_data[
            error_data["tracking_status"] == status
        ]

        if not subset.empty:

            error_fig.add_trace(
                go.Scatter(
                    x=subset["timestamp_utc"],
                    y=subset["pointing_error_deg"],
                    mode="lines+markers",
                    name=status.replace("_", " ").title(),
                    line=dict(color=color, width=2),
                    marker=dict(size=5)
                )
            )

    error_fig.add_hline(
        y=tracking_tolerance,
        line_dash="dash",
        line_color="red",
        annotation_text="Tracking tolerance"
    )

    error_fig.update_layout(
        height=400,
        xaxis_title="Time (UTC)",
        yaxis_title="Pointing error (degrees)",
        hovermode="x unified"
    )

    st.plotly_chart(
        error_fig,
        use_container_width=True
    )

else:

    st.info("No pointing error telemetry available.")


# ==================================================
# SATELLITE PATH
# ==================================================

st.divider()
st.header("🛰️ Predicted Satellite Path")

path_data = pass_data.copy()

path_data["Continuous Azimuth"] = np.degrees(
    np.unwrap(
        np.radians(
            path_data["azimuth_degrees"].to_numpy()
        )
    )
)

path_data = path_data.set_index("timestamp_utc")

st.subheader("Satellite Azimuth")

st.line_chart(
    path_data[["Continuous Azimuth"]],
    height=280
)

st.subheader("Satellite Elevation")

st.line_chart(
    path_data[["elevation_degrees"]],
    height=280
)


# ==================================================
# TRACKING TELEMETRY
# ==================================================

st.divider()
st.header("📋 Tracking Telemetry")

st.dataframe(
    telemetry,
    use_container_width=True,
    hide_index=True
)


# ==================================================
# MOTOR COMMANDS
# ==================================================

st.header("⚙️ Generated Motor Commands")

st.dataframe(
    motor_data,
    use_container_width=True,
    hide_index=True
)


# ==================================================
# DOWNLOAD FILES
# ==================================================

st.divider()
st.header("📥 Download Simulation Data")

pass_csv = pass_data.to_csv(
    index=False
).encode("utf-8")

motor_csv = motor_data.to_csv(
    index=False
).encode("utf-8")

telemetry_csv = telemetry.to_csv(
    index=False
).encode("utf-8")

download_a, download_b, download_c = st.columns(3)

download_a.download_button(
    "Download Pass CSV",
    data=pass_csv,
    file_name=f"{result['satellite'].lower().replace(' ', '_')}_next_pass.csv",
    mime="text/csv",
    use_container_width=True
)

download_b.download_button(
    "Download Motor Commands",
    data=motor_csv,
    file_name="motor_commands.csv",
    mime="text/csv",
    use_container_width=True
)

download_c.download_button(
    "Download Tracking Telemetry",
    data=telemetry_csv,
    file_name="tracking_telemetry.csv",
    mime="text/csv",
    use_container_width=True
)


# ==================================================
# SIMULATION SUMMARY
# ==================================================

with st.expander("View detailed simulation console output"):

    st.code(
        result["simulation_summary"],
        language="text"
    )


# ==================================================
# FOOTER
# ==================================================

st.divider()

st.caption(
    "Autonomous Satellite Tracking Ground Station | "
    "B.Tech Software Prototype | Simulation Mode"
)