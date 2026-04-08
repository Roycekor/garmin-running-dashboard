import sqlite3
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

DB_PATH = Path(__file__).parent / "analysis.db"

st.set_page_config(page_title="Running Analytics", layout="wide")
st.title("Running Analytics Dashboard")


@st.cache_data(ttl=300)
def load_data():
    try:
        with sqlite3.connect(str(DB_PATH)) as conn:
            df = pd.read_sql_query("SELECT * FROM run_analysis ORDER BY activity_date", conn)
    except Exception:
        st.error("run_analysis 테이블이 없습니다. `python scripts/main.py --analyze-only`를 먼저 실행하세요.")
        return pd.DataFrame()
    if 'activity_date' in df.columns:
        df['activity_date'] = pd.to_datetime(df['activity_date'])
        iso = df['activity_date'].dt.isocalendar()
        df['week'] = iso.year.astype(str) + '-W' + iso.week.astype(str).str.zfill(2)
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
    total_seconds = round(minutes * 60)
    m = total_seconds // 60
    s = total_seconds % 60
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

min_dist = st.sidebar.number_input("Min distance (km)", min_value=0.0, value=3.5, step=0.5)
if min_dist > 0:
    df = df[df['total_distance_km'] >= min_dist]

if df.empty:
    st.warning("No data for the selected filters.")
    st.stop()

# 페이스 계산 (전체 세션 기준, min/km)
df['overall_pace'] = df.apply(
    lambda r: (r['total_duration_sec'] / 60 / r['total_distance_km'])
    if r['total_distance_km'] and r['total_distance_km'] > 0 and r['total_duration_sec'] else None,
    axis=1
)

# --- Zone2 Pace Trend ---
st.header("Zone2 Pace Trend")
st.caption("Zone2 비율 30% 이상인 런만 표시. Lower number is faster.")

z2 = df[(df['zone2_avg_pace_min_km'].notna()) & (df['zone2_ratio'] >= 30)].copy()
if not z2.empty:
    z2 = z2.reset_index(drop=True)
    z2['pace_minutes'] = z2['zone2_avg_pace_min_km'].apply(pace_str_to_minutes)
    z2 = z2[z2['pace_minutes'].notna()].reset_index(drop=True)
    z2['rolling_avg'] = z2['pace_minutes'].rolling(window=5, min_periods=2).mean()

    _z2_labels = z2['activity_date'].dt.strftime('%m/%d')
    _z2_n = len(_z2_labels)
    _z2_idx = list(range(_z2_n))
    _z2_step = max(1, _z2_n // 12)
    _z2_tick = list(range(0, _z2_n, _z2_step))
    if (_z2_n - 1) not in _z2_tick:
        _z2_tick.append(_z2_n - 1)

    fig1 = go.Figure()
    fig1.add_trace(go.Scatter(
        x=_z2_idx, y=z2['pace_minutes'], mode='markers',
        name='Pace', marker=dict(size=8, color='#636EFA'),
        customdata=z2['zone2_avg_pace_min_km'], text=_z2_labels,
        hovertemplate='%{text}<br>Pace: %{customdata}<extra></extra>'
    ))
    fig1.add_trace(go.Scatter(
        x=_z2_idx, y=z2['rolling_avg'], mode='lines',
        name='5-run avg', line=dict(color='#EF553B', width=2, shape='spline'),
        customdata=z2['rolling_avg'].apply(minutes_to_pace_str), text=_z2_labels,
        hovertemplate='%{text}<br>Avg: %{customdata}<extra></extra>'
    ))
    pace_min = z2['pace_minutes'].min()
    pace_max = z2['pace_minutes'].max()
    pad = (pace_max - pace_min) * 0.3 if pace_max > pace_min else 0.5
    fig1.update_yaxes(title_text="Pace (min/km)",
                      range=[pace_max + pad, pace_min - pad],
                      tickvals=[v / 2 for v in range(8, 20)],
                      ticktext=[minutes_to_pace_str(v / 2) for v in range(8, 20)])
    fig1.update_xaxes(title_text="", tickangle=0, automargin=True,
                      tickvals=[i for i in _z2_tick],
                      ticktext=[_z2_labels.iloc[i] for i in _z2_tick],
                      range=[-0.3, _z2_n - 0.7])
    fig1.update_layout(height=400, margin=dict(t=20, l=60, r=60),
                       paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                       legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5))
    st.plotly_chart(fig1, use_container_width=True)
else:
    st.info("Zone2 pace data not available.")

# --- HR Drift ---
st.header("HR Drift")
st.caption("Zone2 비율 30% 이상인 런만 표시. Below 5% = good aerobic fitness. Above 7% = needs attention.")

hr = df[(df['hr_drift_percent'].notna()) & (df['zone2_ratio'] >= 30)].copy()
if not hr.empty:
    hr = hr.reset_index(drop=True)
    _hr_labels = hr['activity_date'].dt.strftime('%m/%d')
    _hr_n = len(_hr_labels)
    _hr_idx = list(range(_hr_n))
    _hr_step = max(1, _hr_n // 12)
    _hr_tick = list(range(0, _hr_n, _hr_step))
    if (_hr_n - 1) not in _hr_tick:
        _hr_tick.append(_hr_n - 1)

    fig2 = go.Figure()
    colors = ['#00CC96' if v <= 5 else '#FFA15A' if v <= 7 else '#EF553B' for v in hr['hr_drift_percent']]
    fig2.add_trace(go.Bar(
        x=_hr_idx, y=hr['hr_drift_percent'],
        marker_color=colors, name='HR Drift %',
        customdata=_hr_labels,
        hovertemplate='%{customdata}<br>Drift: %{y:.1f}%<extra></extra>'
    ))
    fig2.add_hline(y=5, line_dash="dash", line_color="green", annotation_text="5% target")
    drift_min = hr['hr_drift_percent'].min()
    drift_max = hr['hr_drift_percent'].max()
    drift_pad = (drift_max - drift_min) * 0.3 if drift_max > drift_min else 1
    fig2.update_yaxes(title_text="HR Drift (%)", range=[min(0, drift_min - drift_pad), drift_max + drift_pad])
    fig2.update_xaxes(title_text="", tickangle=0, automargin=True,
                      tickvals=[i for i in _hr_tick],
                      ticktext=[_hr_labels.iloc[i] for i in _hr_tick],
                      range=[-0.3, _hr_n - 0.7])
    fig2.update_layout(height=400, margin=dict(t=20, l=60, r=60),
                       paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    st.plotly_chart(fig2, use_container_width=True)
else:
    st.info("HR drift data not available.")

# --- HR & Pace Trend (dual axis) ---
st.header("HR & Pace Trend")

_hp = df[df['avg_hr'].notna() & df['overall_pace'].notna()].copy()
if not _hp.empty:
    _hp = _hp.reset_index(drop=True)
    _x_labels = _hp['activity_date'].dt.strftime('%m/%d')
    _n = len(_x_labels)
    _step = max(1, _n // 12)
    _tick_idx = list(range(0, _n, _step))
    if (_n - 1) not in _tick_idx:
        _tick_idx.append(_n - 1)

    _x_idx = list(range(_n))

    fig0a = go.Figure()
    fig0a.add_hrect(y0=137, y1=159, fillcolor='rgba(99,110,250,0.08)', line_width=0,
                    annotation_text='Zone 2 (137-159)', annotation_position='top left',
                    annotation_font_size=10, annotation_font_color='rgba(255,255,255,0.4)')
    fig0a.add_trace(go.Scatter(
        x=_x_idx, y=_hp['avg_hr'], mode='lines+markers',
        name='Avg HR (bpm)',
        line=dict(color='#5B8AF5', width=2.5),
        marker=dict(size=4, color='#5B8AF5'),
        customdata=_x_labels,
        hovertemplate='%{customdata}<br>HR: %{y:.0f} bpm<extra></extra>'
    ))
    fig0a.add_trace(go.Scatter(
        x=_x_idx, y=_hp['overall_pace'], mode='lines+markers',
        name='Pace (min/km, lower = faster)',
        line=dict(color='#6BBF8A', width=2.2, dash='dot'),
        marker=dict(size=5, color='#6BBF8A'),
        yaxis='y2',
        customdata=_hp['overall_pace'].apply(minutes_to_pace_str),
        hovertemplate=('%{text}<br>Pace: %{customdata}<extra></extra>'),
        text=_x_labels,
    ))
    fig0a.update_layout(
        template='plotly_dark',
        height=450, margin=dict(t=20, l=60, r=60),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        yaxis=dict(title='bpm', range=[125, 185],
                   gridcolor='rgba(255,255,255,0.08)', dtick=5),
        yaxis2=dict(title='min/km', overlaying='y', side='right',
                    range=[9.5, 5.0], autorange=False,
                    tickvals=[5.5, 6.0, 6.5, 7.0, 7.5, 8.0, 8.5, 9.0],
                    ticktext=[minutes_to_pace_str(v) for v in [5.5, 6.0, 6.5, 7.0, 7.5, 8.0, 8.5, 9.0]],
                    showgrid=False),
        xaxis=dict(tickangle=0, automargin=True,
                   tickvals=[i for i in _tick_idx],
                   ticktext=[_x_labels.iloc[i] for i in _tick_idx],
                   gridcolor='rgba(255,255,255,0.08)',
                   range=[-0.3, _n - 0.7]),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    font=dict(size=11)),
    )
    st.plotly_chart(fig0a, use_container_width=True)
else:
    st.info("HR & Pace data not available.")

# --- Monthly Distance ---
st.header("Monthly Distance")

wd = df[df['total_distance_km'].notna()].copy()
if not wd.empty:
    wd['month'] = wd['activity_date'].dt.to_period('M').astype(str)
    monthly_dist = wd.groupby('month').agg(
        total_km=('total_distance_km', 'sum'),
        runs=('total_distance_km', 'count')
    ).reset_index()
    monthly_dist['total_km'] = monthly_dist['total_km'].round(1)
    monthly_dist['month_label'] = monthly_dist['month'].apply(
        lambda m: f"{int(m.split('-')[1])}월")

    fig3 = px.bar(monthly_dist, x='month_label', y='total_km',
                  hover_data={'runs': True, 'total_km': ':.1f'},
                  labels={'total_km': 'Distance (km)', 'month_label': '', 'runs': 'Runs'})
    fig3.update_traces(marker_color='#636EFA')
    km_max = monthly_dist['total_km'].max()
    fig3.update_yaxes(title_text='km', range=[0, km_max * 1.3])
    fig3.update_layout(height=400, margin=dict(t=20, l=60, r=60), bargap=0.3,
                       paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    st.plotly_chart(fig3, use_container_width=True)
else:
    st.info("Distance data not available.")

# --- Zone Distribution (Monthly) ---
st.header("Zone Distribution (Monthly)")

_zone_cols = ['z1_pct', 'z2_pct', 'z2b_pct', 'z3_pct', 'z4plus_pct']
if all(c in df.columns for c in _zone_cols) and not df[_zone_cols].isna().all().all():
    _zdf = df[df[_zone_cols].notna().any(axis=1)].copy()
    _zdf['month'] = _zdf['activity_date'].dt.to_period('M').astype(str)
    _monthly_z = _zdf.groupby('month')[_zone_cols].mean().reset_index()
    _monthly_z['month_label'] = _monthly_z['month'].apply(
        lambda m: f"{int(m.split('-')[1])}월")

    _zone_labels = {'z1_pct': 'Z1 (<137)', 'z2_pct': 'Z2 (137-153)', 'z2b_pct': 'Z2b (154-159)',
                    'z3_pct': 'Z3 (160-170)', 'z4plus_pct': 'Z4+ (171+)'}
    _zone_colors = {'z1_pct': '#1f77b4', 'z2_pct': '#2ca02c', 'z2b_pct': '#98df8a',
                    'z3_pct': '#ffbb78', 'z4plus_pct': '#d62728'}

    fig0b = go.Figure()
    for col in _zone_cols:
        fig0b.add_trace(go.Bar(
            x=_monthly_z['month_label'], y=_monthly_z[col], name=_zone_labels[col],
            marker_color=_zone_colors[col],
            hovertemplate='%{x}<br>' + _zone_labels[col] + ': %{y:.1f}%<extra></extra>'
        ))
    fig0b.update_layout(
        template='plotly_dark', barmode='stack',
        height=400, margin=dict(t=20, l=60, r=60),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        yaxis=dict(title='%', range=[0, 105], dtick=20, ticksuffix='%',
                   gridcolor='rgba(255,255,255,0.08)'),
        xaxis=dict(gridcolor='rgba(255,255,255,0.08)'),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    font=dict(size=11)),
        bargap=0.3
    )
    st.plotly_chart(fig0b, use_container_width=True)
else:
    st.info("Zone distribution data not available. Re-run analysis to populate.")

# --- Long Run Pace Stability (8km+) ---
st.header("Long Run Pace Stability (8km+)")
st.caption("Lower CV = more consistent pacing. CV < 7.5% = stable.")

ps = df[df['pace_stability_cv'].notna()].copy()
if not ps.empty:
    ps = ps.reset_index(drop=True)
    _ps_labels = ps['activity_date'].dt.strftime('%m/%d')
    _ps_n = len(_ps_labels)
    _ps_idx = list(range(_ps_n))
    _ps_step = max(1, _ps_n // 12)
    _ps_tick = list(range(0, _ps_n, _ps_step))
    if (_ps_n - 1) not in _ps_tick:
        _ps_tick.append(_ps_n - 1)

    fig4 = go.Figure()
    fig4.add_trace(go.Scatter(
        x=_ps_idx, y=ps['pace_stability_cv'], mode='markers+lines',
        marker=dict(size=8, color='#AB63FA'), line=dict(color='#AB63FA', width=1),
        customdata=ps['total_distance_km'], text=_ps_labels,
        hovertemplate='%{text}<br>CV: %{y:.1f}%<br>Distance: %{customdata:.1f}km<extra></extra>'
    ))
    fig4.add_hline(y=7.5, line_dash="dash", line_color="green", annotation_text="7.5% target")
    cv_min = ps['pace_stability_cv'].min()
    cv_max = ps['pace_stability_cv'].max()
    cv_pad = (cv_max - cv_min) * 0.3 if cv_max > cv_min else 1
    fig4.update_yaxes(title_text="Pace CV (%)", range=[max(0, cv_min - cv_pad), cv_max + cv_pad])
    fig4.update_xaxes(title_text="", tickangle=0, automargin=True,
                      tickvals=[i for i in _ps_tick],
                      ticktext=[_ps_labels.iloc[i] for i in _ps_tick],
                      range=[-0.3, _ps_n - 0.7])
    fig4.update_layout(height=400, margin=dict(t=20, l=60, r=60),
                       paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    st.plotly_chart(fig4, use_container_width=True)
else:
    st.info("No long runs (8km+) with pace stability data.")

# --- Summary ---
st.divider()
st.header("Summary")

_recent = df.tail(5)
_early = df.head(5)
_period = f"{date_min.strftime('%Y.%m')} ~ {date_max.strftime('%Y.%m')}"
_recent_hr = round(_recent['avg_hr'].mean()) if not _recent['avg_hr'].isna().all() else None
_early_hr = round(_early['avg_hr'].mean()) if not _early['avg_hr'].isna().all() else None
_recent_pace = _recent['overall_pace'].mean() if not _recent['overall_pace'].isna().all() else None
_early_pace = _early['overall_pace'].mean() if not _early['overall_pace'].isna().all() else None
_has_zone_cols = 'z2_pct' in df.columns and not df['z2_pct'].isna().all()
if _has_zone_cols:
    _r_z2 = _recent['z2_pct'] + _recent['z2b_pct']  # NaN 행은 NaN 유지
    _e_z2 = _early['z2_pct'] + _early['z2b_pct']
    _recent_z2 = round(_r_z2.mean()) if _r_z2.notna().any() else None
    _early_z2 = round(_e_z2.mean()) if _e_z2.notna().any() else None
else:
    _recent_z2 = round(_recent['zone2_ratio'].mean()) if not _recent['zone2_ratio'].isna().all() else None
    _early_z2 = round(_early['zone2_ratio'].mean()) if not _early['zone2_ratio'].isna().all() else None

# Row 1: overview
r1c1, r1c2, r1c3, r1c4 = st.columns(4)
with r1c1:
    st.metric("Total Runs", f"{len(df)}", help=_period)
with r1c2:
    total_km = df['total_distance_km'].sum()
    st.metric("Total Distance", f"{total_km:.0f} km")
with r1c3:
    if not z2.empty:
        latest_pace = z2.iloc[-1]['zone2_avg_pace_min_km']
        st.metric("Latest Z2 Pace", latest_pace)
    else:
        st.metric("Latest Z2 Pace", "N/A")
with r1c4:
    if not z2.empty:
        best_pace = z2.loc[z2['pace_minutes'].idxmin(), 'zone2_avg_pace_min_km']
        st.metric("Best Z2 Pace", best_pace)
    else:
        st.metric("Best Z2 Pace", "N/A")

# Row 2: recent trend + averages
r2c1, r2c2, r2c3, r2c4 = st.columns(4)
with r2c1:
    delta_hr = f"{_recent_hr - _early_hr:+d} bpm" if _recent_hr is not None and _early_hr is not None else None
    st.metric("Avg HR (recent)", f"{_recent_hr} bpm" if _recent_hr else "N/A",
              delta=delta_hr, delta_color="inverse")
with r2c2:
    delta_pace = None
    if _recent_pace is not None and _early_pace is not None:
        diff_sec = round((_recent_pace - _early_pace) * 60)
        delta_pace = f"{diff_sec:+d}s"
    st.metric("Avg Pace (recent)", minutes_to_pace_str(_recent_pace) if _recent_pace else "N/A",
              delta=delta_pace, delta_color="inverse")
with r2c3:
    delta_z2 = f"{_recent_z2 - _early_z2:+d}%p" if _recent_z2 is not None and _early_z2 is not None else None
    st.metric("Z2 Ratio (recent)", f"{_recent_z2}%" if _recent_z2 is not None else "N/A", delta=delta_z2)
with r2c4:
    avg_drift = hr['hr_drift_percent'].mean() if not hr.empty else None
    st.metric("Avg HR Drift", f"{avg_drift:.1f}%" if avg_drift is not None else "N/A")
