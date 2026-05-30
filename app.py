"""Econ Dashboard — Streamlit UI (the 'display' layer).

All the numbers, plus some intuitions. Single page, collapsible sections, a
top Data Explorer for overlaying/downloading series, charts with MoM/YoY tabs,
a master table toggle, and an in-app form for the manual indicators (ISM, Tariffs).

Run:  streamlit run app.py
"""

from __future__ import annotations

import os
from datetime import date, datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from econ import refresh, store
from econ.indicators import INDICATORS, by_key, sections
from econ.models import Indicator, Reading
from econ.sources import fred_api_key

st.set_page_config(page_title="Econ Dashboard", page_icon="📊", layout="wide")

store.init_db()

# On a fresh deploy (e.g. Streamlit Cloud) the DB is empty, so load the seed
# fixtures once. Live FRED data is layered on top via the Refresh button.
if store.get_meta("seeded_at") is None:
    from seed import SEED

    store.upsert_readings(SEED)
    store.set_meta("seeded_at", date.today().isoformat())


# ---------------------------------------------------------------------------
# Admin gate — refresh + manual edits are admin-only when a password is set.
# If no ADMIN_PASSWORD is configured (e.g. running locally), you have full
# access. On a public deploy, set ADMIN_PASSWORD in Streamlit Cloud secrets so
# visitors get a read-only dashboard.
# ---------------------------------------------------------------------------


def admin_password() -> str | None:
    pw = os.environ.get("ECON_ADMIN_PASSWORD")
    if pw:
        return pw
    try:
        return st.secrets.get("ADMIN_PASSWORD")
    except Exception:
        return None


def is_admin() -> bool:
    if not admin_password():
        return True  # no password configured -> trusted (local) session
    return bool(st.session_state.get("is_admin", False))


# ---------------------------------------------------------------------------
# Data access (cached so the page is snappy; refresh/edit clears the cache)
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300)
def load_readings(indicator_key: str) -> pd.DataFrame:
    rows = store.get_readings(indicator_key)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {
                "series": r.series_label,
                "period": pd.to_datetime(r.period),
                "value": r.value,
                "unit": r.unit,
                "prior_value": r.prior_value,
                "commentary": r.commentary,
                "source": r.source,
            }
            for r in rows
        ]
    )


@st.cache_data(ttl=300)
def load_all_readings() -> pd.DataFrame:
    """Every series, long-form, for the Data Explorer."""
    frames = []
    for ind in INDICATORS:
        df = load_readings(ind.key)
        if df.empty:
            continue
        df = df.copy()
        df["indicator"] = ind.name
        df["pick"] = ind.name + " · " + df["series"]
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def clear_caches() -> None:
    load_readings.clear()
    load_all_readings.clear()


def fmt(value, unit: str) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    sign = "+" if unit == "%" and value > 0 else ""
    if unit == "$B":
        return f"${value:,.1f}B"
    if unit == "$T":
        return f"${value:,.2f}T"
    if unit == "K":
        return f"{sign}{value:,.0f}K"
    if unit == "%":
        return f"{sign}{value:.1f}%"
    if unit == "index":
        return f"{value:.1f}"
    return f"{value:,.2f}{unit}"


# ---------------------------------------------------------------------------
# Charting helpers
# ---------------------------------------------------------------------------


def combined_fig(df: pd.DataFrame, labels: list[str], unit_by_label: dict[str, str],
                 height: int = 300) -> go.Figure:
    """Overlay `labels` on one chart. Mixed units get a right-hand 2nd y-axis."""
    units: list[str] = []
    for label in labels:
        u = unit_by_label.get(label, "")
        if u not in units:
            units.append(u)
    primary = units[0] if units else ""
    secondary = units[1] if len(units) > 1 else None

    fig = go.Figure()
    for label in labels:
        sdf = df[df["series"] == label].sort_values("period")
        if sdf.empty:
            continue
        trace = go.Scatter(x=sdf["period"], y=sdf["value"],
                           mode="lines+markers", name=label)
        if secondary and unit_by_label.get(label) == secondary:
            trace.update(yaxis="y2")
        fig.add_trace(trace)

    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=10, b=10),
        xaxis_title="Date", yaxis_title=primary or "Value",
        legend=dict(orientation="h", y=-0.25),
        hovermode="x unified",
    )
    if secondary:
        fig.update_layout(
            yaxis2=dict(title=secondary, overlaying="y", side="right", showgrid=False))
    return fig


# ---------------------------------------------------------------------------
# Data Explorer (the interactive "spreadsheet" at the top)
# ---------------------------------------------------------------------------


def render_explorer() -> None:
    allrows = load_all_readings()
    allrows = allrows[allrows["value"].notna()] if not allrows.empty else allrows
    if allrows.empty:
        st.info("No numeric data yet — add a FRED key and **Refresh now**.")
        return

    options = sorted(allrows["pick"].unique())
    default = [o for o in options if ("CPI-U · Headline YoY" in o
               or "Real GDP" in o or "Unemployment" in o)][:3] or options[:2]
    chosen = st.multiselect("Series to overlay", options, default=default,
                            help="Pick any series across all indicators to compare.")
    if not chosen:
        return

    sub = allrows[allrows["pick"].isin(chosen)].copy()
    c1, c2 = st.columns([1, 2])
    normalize = c1.toggle(
        "Index to 100 at start", value=False,
        help="Rebase each series to 100 at its first point so you can compare "
             "shapes across different units (%, $B, index).")
    mind, maxd = sub["period"].min().date(), sub["period"].max().date()
    rng = c2.date_input("Date range", value=(max(mind, date(maxd.year - 5, 1, 1)), maxd),
                        min_value=mind, max_value=maxd)
    if isinstance(rng, tuple) and len(rng) == 2:
        lo, hi = pd.to_datetime(rng[0]), pd.to_datetime(rng[1])
        sub = sub[(sub["period"] >= lo) & (sub["period"] <= hi)]

    fig = go.Figure()
    for pick, g in sub.groupby("pick"):
        g = g.sort_values("period")
        y = g["value"]
        if normalize and len(y) and y.iloc[0]:
            y = y / y.iloc[0] * 100
        fig.add_trace(go.Scatter(x=g["period"], y=y, mode="lines", name=pick))
    fig.update_layout(
        height=440, margin=dict(l=10, r=10, t=10, b=10),
        xaxis_title="Date",
        yaxis_title="Index (100 = start)" if normalize else "Value",
        legend=dict(orientation="h", y=-0.25), hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True, key="explorer-chart")

    pivot = sub.pivot_table(index="period", columns="pick", values="value").sort_index()
    pivot.index = pivot.index.date
    st.dataframe(pivot, use_container_width=True)
    st.download_button(
        "⬇️ Download CSV (opens in Excel)", pivot.to_csv().encode(),
        "econ_explorer.csv", "text/csv")


# ---------------------------------------------------------------------------
# Manual entry form (ISM, Tariffs — the non-FRED indicators)
# ---------------------------------------------------------------------------


def render_manual_form(ind: Indicator) -> None:
    with st.expander("✏️ Add / update a reading"):
        with st.form(f"form-{ind.key}", clear_on_submit=True):
            label = st.selectbox("Series", [s.label for s in ind.series],
                                 key=f"lbl-{ind.key}")
            period = st.date_input("Period", value=date.today().replace(day=1),
                                   key=f"per-{ind.key}")
            raw_val = st.text_input("Value (leave blank for a note-only entry)",
                                    key=f"val-{ind.key}")
            note = st.text_input("Commentary", key=f"note-{ind.key}")
            if st.form_submit_button("💾 Save", type="primary"):
                value = None
                if raw_val.strip():
                    try:
                        value = float(raw_val)
                    except ValueError:
                        st.error("Value must be a number (or blank).")
                        return
                spec = next(s for s in ind.series if s.label == label)
                store.upsert_readings([Reading(
                    indicator_key=ind.key, series_label=label, period=period,
                    value=value, unit=spec.unit, release_date=date.today(),
                    commentary=note, source="manual:ui")])
                clear_caches()
                st.success(f"Saved {label} for {period:%Y-%m-%d}.")
                st.rerun()


# ---------------------------------------------------------------------------
# Indicator rendering
# ---------------------------------------------------------------------------


def render_curve(ind: Indicator, df: pd.DataFrame, show_tables: bool) -> None:
    order = [s.label for s in ind.series]
    latest_period = df["period"].max()
    snap = df[df["period"] == latest_period]
    points = snap.set_index("series")["value"].reindex(order).dropna()
    if points.empty:
        st.caption("No curve data yet.")
        return
    fig = go.Figure(go.Scatter(x=points.index, y=points.values, mode="lines+markers"))
    fig.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10),
                      yaxis_title="Yield (%)", xaxis_title="Maturity")
    cols = st.columns([2, 3])
    with cols[1]:
        st.plotly_chart(fig, use_container_width=True, key=f"{ind.key}-curve")
    with cols[0]:
        st.caption(f"As of {latest_period:%Y-%m-%d}")
        if show_tables:
            st.dataframe(
                points.reset_index().rename(
                    columns={"series": "Maturity", "value": "Yield %"}),
                hide_index=True, use_container_width=True)


def render_timeseries(ind: Indicator, df: pd.DataFrame, show_tables: bool) -> None:
    order = [s.label for s in ind.series]
    present = [s for s in order if s in set(df["series"])]
    unit_by_label = {s.label: s.unit for s in ind.series}

    # Latest-value metric tiles (one per series).
    metric_cols = st.columns(max(len(present), 1))
    for col, label in zip(metric_cols, present):
        sdf = df[df["series"] == label].sort_values("period")
        last = sdf.iloc[-1]
        delta = None
        if last["prior_value"] is not None and pd.notna(last["prior_value"]):
            delta = f"revised from {fmt(last['prior_value'], last['unit'])}"
        col.metric(label, fmt(last["value"], last["unit"]), delta=delta,
                   delta_color="off")

    plot_df = df[df["value"].notna() & df["series"].isin(present)]
    if not plot_df.empty and plot_df["period"].nunique() > 1:
        if len(present) > 1:
            # Combined view + one tab per series (clean MoM vs YoY separation).
            tabs = st.tabs(["Combined"] + present)
            with tabs[0]:
                st.plotly_chart(combined_fig(plot_df, present, unit_by_label),
                                use_container_width=True, key=f"{ind.key}-combined")
            for tab, label in zip(tabs[1:], present):
                with tab:
                    st.plotly_chart(
                        combined_fig(plot_df, [label], unit_by_label),
                        use_container_width=True, key=f"{ind.key}-{label}")
        else:
            st.plotly_chart(combined_fig(plot_df, present, unit_by_label),
                            use_container_width=True, key=f"{ind.key}-single")

    if show_tables:
        recent = df.sort_values("period", ascending=False).head(8)
        show = recent[["period", "series", "value", "unit", "commentary"]].copy()
        show["value"] = [fmt(v, u) for v, u in zip(show["value"], show["unit"])]
        show["period"] = show["period"].dt.date
        show = show.drop(columns="unit").rename(columns=str.title)
        st.dataframe(show, hide_index=True, use_container_width=True)


def render_indicator(ind: Indicator, show_tables: bool) -> None:
    df = load_readings(ind.key)
    head = ind.headline_series()
    headline_txt = ""
    if not df.empty and head is not None:
        hs = df[df["series"] == head.label].sort_values("period")
        if not hs.empty and pd.notna(hs.iloc[-1]["value"]):
            headline_txt = f" — {fmt(hs.iloc[-1]['value'], head.unit)}"

    with st.expander(f"**{ind.name}**{headline_txt}", expanded=True):
        st.caption(f"_{ind.intuition}_")
        if df.empty:
            st.info("No data yet — add a FRED key and hit **Refresh now**, "
                    "or run `python seed.py`.")
        elif ind.is_curve:
            render_curve(ind, df, show_tables)
        else:
            render_timeseries(ind, df, show_tables)

        if ind.source_type in ("manual", "scrape") and is_admin():
            render_manual_form(ind)

        st.caption(
            f"📎 Source: [{ind.source_url.split('//')[-1][:60]}…]({ind.source_url})  ·  "
            f"`{ind.cadence}`  ·  `{ind.source_type}`")
        fred_ids: list[str] = []
        for s in ind.series:
            if s.fred_id and s.fred_id not in fred_ids:
                fred_ids.append(s.fred_id)
        if fred_ids:
            links = "  ·  ".join(
                f"[{fid}](https://fred.stlouisfed.org/series/{fid})" for fid in fred_ids)
            st.caption(f"🔗 FRED: {links}")


# ---------------------------------------------------------------------------
# Sidebar — refresh + status
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("📊 Econ Dashboard")
    st.caption("All the numbers, plus some intuitions.")

    has_key = bool(fred_api_key())
    st.write("**FRED API key:**", "✅ configured" if has_key else "❌ missing")
    if not has_key:
        st.info(
            "Add a free FRED key to pull live data:\n\n"
            "1. Get one at fredaccount.stlouisfed.org/apikeys\n"
            "2. Put `FRED_API_KEY=\"...\"` in `.streamlit/secrets.toml`\n\n"
            "Until then the dashboard shows seeded values.")

    st.write("**Last refresh:**", store.get_meta("last_refresh") or "never")

    # Admin login (only shown when a password is configured, i.e. on a deploy).
    if admin_password():
        if st.session_state.get("is_admin"):
            st.success("🔓 Admin mode")
            if st.button("Log out", use_container_width=True):
                st.session_state.is_admin = False
                st.rerun()
        else:
            with st.expander("🔐 Admin login"):
                entered = st.text_input("Password", type="password",
                                        key="admin_pw")
                if st.button("Unlock", use_container_width=True):
                    if entered == admin_password():
                        st.session_state.is_admin = True
                        st.rerun()
                    else:
                        st.error("Wrong password.")

    if is_admin():
        if st.button("🔄 Refresh now", use_container_width=True, type="primary"):
            with st.spinner("Fetching latest releases…"):
                summary = refresh.refresh_all()
            clear_caches()
            st.success(f"{summary['ok']} updated · {summary['new']} new · "
                       f"{summary['revised']} revised")
            for err in summary["errors"]:
                st.warning(f"{err['key']}: {err['detail']}")
            st.rerun()
    else:
        st.caption("👀 Read-only view. Log in as admin to refresh or edit.")

    chosen_sections = st.multiselect("Sections", sections(), default=sections(),
                                     help="Filter which sections show below.")


# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------

st.title("US Macro Dashboard")
st.caption(f"Rendered {datetime.now():%Y-%m-%d %H:%M} · "
           f"{len(INDICATORS)} indicators across {len(sections())} sections")

# Master controls (top of page)
ctrl1, ctrl2 = st.columns([1, 3])
show_tables = ctrl1.toggle("📋 Show data tables", value=True,
                           help="Master switch: hide/show the readings tables everywhere.")

with st.expander("🔬 Data Explorer — overlay & download any series", expanded=False):
    render_explorer()

st.divider()

for section in sections():
    if section not in chosen_sections:
        continue
    st.header(section)
    for ind in INDICATORS:
        if ind.section == section:
            render_indicator(ind, show_tables)
