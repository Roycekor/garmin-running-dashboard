import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "analysis.db"

st.set_page_config(page_title="Running Analytics", layout="wide")
st.title("Running Analytics Dashboard")


@st.cache_resource
def get_connection():
    return sqlite3.connect(str(DB_PATH), check_same_thread=False)


@st.cache_data(ttl=300)
def load_data():
    conn = get_connection()
    try:
        df = pd.read_sql_query("SELECT * FROM run_analysis ORDER BY activity_date", conn)
    except Exception:
        st.error("run_analysis 테이블이 없습니다. `python scripts/main.py --analyze-only`를 먼저 실행하세요.")
        return pd.DataFrame()
    if 'activity_date' in df.columns:
        df['activity_date'] = pd.to_datetime(df['activity_date'])
        df['week'] = df['activity_date'].dt.isocalendar().year.astype(str) + '-W' + df['activity_date'].dt.isocalendar().week.astype(str).str.zfill(2)
    return df


def pace_str_to_minutes(pace_str):
    """'6:47' -> 6.783 (분 단위 float)"""
    if pd.isna(pace_str) or pace_str is None:
        return None
    try:
        parts = str(pace_str).split(':')
        return int(parts[0]) + int(parts[1]) / 60
    except (ValueError, IndexError):
        return None


def minutes_to_pace_str(minutes):
    """6.783 -> '6:47'"""
    if pd.isna(minutes):
        return ""
    m = int(minutes)
    s = round((minutes - m) * 60)
    return f"{m}:{s:02d}"


df = load_data()

if df.empty:
    st.stop()

# --- Sidebar filters ---
st.sidebar.header("Filters")
date_min = df['activity_date'].min().date()
date_max = df['activity_date'].max().date()
date_range = st.sidebar.date_input("Date range", value=(date_min, date_max), min_value=date_min, max_value=date_max)
if len(date_range) == 2:
    df = df[(df['activity_date'].dt.date >= date_range[0]) & (df['activity_date'].dt.date <= date_range[1])]

min_dist = st.sidebar.number_input("Min distance (km)", min_value=0.0, value=0.0, step=1.0)
if min_dist > 0:
    df = df[df['total_distance_km'] >= min_dist]

if df.empty:
    st.warning("No data for the selected filters.")
    st.stop()

# --- 1. Zone2 Pace Trend ---
st.header("1. Zone2 Pace Trend")
st.caption("Zone2 비율 30% 이상인 런만 표시. Lower number is faster.")

z2 = df[(df['zone2_avg_pace_min_km'].notna()) & (df['zone2_ratio'] >= 30)].copy()
if not z2.empty:
    z2['pace_minutes'] = z2['zone2_avg_pace_min_km'].apply(pace_str_to_minutes)
    z2 = z2[z2['pace_minutes'].notna()]
    z2['rolling_avg'] = z2['pace_minutes'].rolling(window=5, min_periods=2).mean()

    fig1 = go.Figure()
    fig1.add_trace(go.Scatter(
        x=z2['activity_date'], y=z2['pace_minutes'], mode='markers',
        name='Pace', marker=dict(size=8, color='#636EFA'),
        hovertemplate='%{x|%Y-%m-%d}<br>Pace: %{customdata}<extra></extra>',
        customdata=z2['zone2_avg_pace_min_km']
    ))
    fig1.add_trace(go.Scatter(
        x=z2['activity_date'], y=z2['rolling_avg'], mode='lines',
        name='5-run avg', line=dict(color='#EF553B', width=2),
        hovertemplate='%{x|%Y-%m-%d}<br>Avg: %{customdata}<extra></extra>',
        customdata=z2['rolling_avg'].apply(minutes_to_pace_str)
    ))
    pace_min = z2['pace_minutes'].min()
    pace_max = z2['pace_minutes'].max()
    pad = (pace_max - pace_min) * 0.3 if pace_max > pace_min else 0.5
    fig1.update_yaxes(title_text="Pace (min/km)",
                      range=[pace_max + pad, pace_min - pad],
                      tickvals=[v / 2 for v in range(8, 20)],
                      ticktext=[minutes_to_pace_str(v / 2) for v in range(8, 20)])
    fig1.update_xaxes(title_text="")
    fig1.update_layout(height=400, margin=dict(t=20),
                       legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5))
    st.plotly_chart(fig1, use_container_width=True)
else:
    st.info("Zone2 pace data not available.")

# --- 2. HR Drift ---
st.header("2. HR Drift")
st.caption("Below 5% = good aerobic fitness. Above 7% = needs attention.")

hr = df[df['hr_drift_percent'].notna()].copy()
if not hr.empty:
    fig2 = go.Figure()
    colors = ['#00CC96' if v <= 5 else '#FFA15A' if v <= 7 else '#EF553B' for v in hr['hr_drift_percent']]
    fig2.add_trace(go.Bar(
        x=hr['activity_date'], y=hr['hr_drift_percent'],
        marker_color=colors, name='HR Drift %',
        hovertemplate='%{x|%Y-%m-%d}<br>Drift: %{y:.1f}%<extra></extra>'
    ))
    fig2.add_hline(y=5, line_dash="dash", line_color="green", annotation_text="5% target")
    drift_min = hr['hr_drift_percent'].min()
    drift_max = hr['hr_drift_percent'].max()
    drift_pad = (drift_max - drift_min) * 0.3 if drift_max > drift_min else 1
    fig2.update_yaxes(title_text="HR Drift (%)", range=[min(0, drift_min - drift_pad), drift_max + drift_pad])
    fig2.update_xaxes(title_text="")
    fig2.update_layout(height=400, margin=dict(t=20))
    st.plotly_chart(fig2, use_container_width=True)
else:
    st.info("HR drift data not available.")

# --- 3. Weekly Distance ---
st.header("3. Weekly Distance")

wd = df[df['total_distance_km'].notna()].copy()
if not wd.empty:
    weekly = wd.groupby('week').agg(
        total_km=('total_distance_km', 'sum'),
        runs=('total_distance_km', 'count')
    ).reset_index()
    weekly['total_km'] = weekly['total_km'].round(1)

    fig3 = px.bar(weekly, x='week', y='total_km',
                  hover_data={'runs': True, 'total_km': ':.1f'},
                  labels={'total_km': 'Distance (km)', 'week': 'Week', 'runs': 'Runs'})
    fig3.update_traces(marker_color='#636EFA')
    km_max = weekly['total_km'].max()
    fig3.update_yaxes(range=[0, km_max * 1.3])
    fig3.update_layout(height=400, margin=dict(t=20))
    st.plotly_chart(fig3, use_container_width=True)
else:
    st.info("Distance data not available.")

# --- 4. Pace Stability (10km+) ---
st.header("4. Long Run Pace Stability (8km+)")
st.caption("Lower CV = more consistent pacing. CV < 7.5% = stable.")

ps = df[df['pace_stability_cv'].notna()].copy()
if not ps.empty:
    fig4 = go.Figure()
    fig4.add_trace(go.Scatter(
        x=ps['activity_date'], y=ps['pace_stability_cv'], mode='markers+lines',
        marker=dict(size=8, color='#AB63FA'), line=dict(color='#AB63FA', width=1),
        hovertemplate='%{x|%Y-%m-%d}<br>CV: %{y:.1f}%<br>Distance: %{customdata:.1f}km<extra></extra>',
        customdata=ps['total_distance_km']
    ))
    fig4.add_hline(y=7.5, line_dash="dash", line_color="green", annotation_text="7.5% target")
    cv_min = ps['pace_stability_cv'].min()
    cv_max = ps['pace_stability_cv'].max()
    cv_pad = (cv_max - cv_min) * 0.3 if cv_max > cv_min else 1
    fig4.update_yaxes(title_text="Pace CV (%)", range=[max(0, cv_min - cv_pad), cv_max + cv_pad])
    fig4.update_xaxes(title_text="")
    fig4.update_layout(height=400, margin=dict(t=20))
    st.plotly_chart(fig4, use_container_width=True)
else:
    st.info("No long runs (8km+) with pace stability data.")

# --- Summary metrics ---
st.divider()
st.header("Summary")
col1, col2, col3, col4 = st.columns(4)
with col1:
    total_runs = len(df)
    st.metric("Total Runs", total_runs)
with col2:
    total_km = df['total_distance_km'].sum()
    st.metric("Total Distance", f"{total_km:.0f} km")
with col3:
    if not z2.empty:
        latest_pace = z2.iloc[-1]['zone2_avg_pace_min_km']
        st.metric("Latest Z2 Pace", latest_pace)
    else:
        st.metric("Latest Z2 Pace", "N/A")
with col4:
    avg_drift = hr['hr_drift_percent'].mean() if not hr.empty else None
    st.metric("Avg HR Drift", f"{avg_drift:.1f}%" if avg_drift else "N/A")
