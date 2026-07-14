from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime

import plotly.graph_objects as go
from dash import html
import dash_bootstrap_components as dbc

from export_pace.data import ViewResult
from export_pace.flow_direction import installation_role_label


@dataclass(frozen=True)
class FigureOptions:
    show_bands: bool = True
    show_median: bool = True
    show_last_month: bool = True
    show_last_year: bool = True
    show_hist_years: bool = False
    compare_locations: bool = False
    compare_products: bool = False
    show_anomalies: bool = True


def _pct_delta(current: float, reference: float) -> str:
    if reference == 0 or reference != reference or current != current:
        return "—"
    pct = (current / reference - 1) * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def _value_at_day(series, day: int) -> float:
    if day not in series.index:
        prior = series[series.index <= day]
        return float(prior.iloc[-1]) if len(prior) else float("nan")
    return float(series.loc[day])


def make_figure(view: ViewResult, opts: FigureOptions | None = None) -> go.Figure:
    opts = opts or FigureOptions()
    month_name = calendar.month_name[view.month]
    unit_label = "kb" if view.unit == "kb" else "kbd (cumulated)"
    x = view.band.index

    fig = go.Figure()

    if opts.show_bands:
        fig.add_trace(
            go.Scatter(x=x, y=view.band["max"], line=dict(width=0), hoverinfo="skip", showlegend=False)
        )
        fig.add_trace(
            go.Scatter(
                x=x,
                y=view.band["min"],
                fill="tonexty",
                line=dict(width=0),
                fillcolor="rgba(158,202,225,0.30)",
                name=f"{view.n_history}y range (min–max)",
                hoverinfo="skip",
            )
        )
        fig.add_trace(
            go.Scatter(x=x, y=view.band["p75"], line=dict(width=0), hoverinfo="skip", showlegend=False)
        )
        fig.add_trace(
            go.Scatter(
                x=x,
                y=view.band["p25"],
                fill="tonexty",
                line=dict(width=0),
                fillcolor="rgba(107,174,214,0.45)",
                name=f"{view.n_history}y IQR (25–75%)",
                hoverinfo="skip",
            )
        )

    if opts.show_median:
        fig.add_trace(
            go.Scatter(
                x=x,
                y=view.band["median"],
                name=f"{view.n_history}y median",
                line=dict(color="#2171b5", width=2),
            )
        )

    if opts.show_last_month:
        fig.add_trace(
            go.Scatter(
                x=view.last_mo.index,
                y=view.last_mo.values,
                name="Last month",
                line=dict(color="#9e9ac8", width=2),
            )
        )

    if opts.show_last_year:
        fig.add_trace(
            go.Scatter(
                x=view.last_yr.index,
                y=view.last_yr.values,
                name="Last year",
                line=dict(color="#74c476", width=2),
            )
        )

    if opts.show_hist_years and not view.hist_by_year.empty:
        for year in sorted(view.hist_by_year.columns):
            fig.add_trace(
                go.Scatter(
                    x=view.hist_by_year.index,
                    y=view.hist_by_year[year],
                    name=str(year),
                    line=dict(color="rgba(150,150,150,0.45)", width=1),
                    legendgroup="hist_years",
                    showlegend=False,
                    hovertemplate=f"{year}<br>Day %{{x}}: %{{y:,.0f}}<extra></extra>",
                )
            )

    palette = ["#e6550d", "#756bb1", "#31a354", "#d95f0e", "#1f78b4", "#e7298a", "#66a61e"]
    show_products = opts.compare_products and len(view.product_series) > 1
    show_locations = opts.compare_locations and len(view.location_series) > 1
    if show_products:
        for i, (label, series) in enumerate(view.product_series.items()):
            fig.add_trace(
                go.Scatter(
                    x=series.index,
                    y=series.values,
                    name=label,
                    line=dict(color=palette[i % len(palette)], width=2.5),
                )
            )
    elif show_locations:
        for i, (label, series) in enumerate(view.location_series.items()):
            fig.add_trace(
                go.Scatter(
                    x=series.index,
                    y=series.values,
                    name=label,
                    line=dict(color=palette[i % len(palette)], width=2.5),
                )
            )
    else:
        fig.add_trace(
            go.Scatter(
                x=view.current.index,
                y=view.current.values,
                name="Current month",
                line=dict(color="#e6550d", width=3, dash="dot"),
            )
        )

    as_of_note = ""
    if view.as_of is not None:
        as_of_note = f" — view as of {view.as_of.strftime('%d %b %Y')}"

    layout_kwargs = dict(
        title=(
            f"Cumulative {view.product_label} {view.flow_direction_label} — {view.location_label} — "
            f"{month_name} {view.target_year}{as_of_note}"
            + ("  (MOCK DATA)" if view.use_mock else "")
        ),
        xaxis_title="Day of month",
        yaxis_title=f"Cumulative {unit_label} (MTD)",
        xaxis=dict(range=[1, 31], dtick=2),
        template="plotly_white",
        legend=dict(orientation="h", y=-0.18),
        height=480,
        margin=dict(b=90),
    )
    if view.flow_direction == "net_export":
        fig.add_hline(y=0, line_dash="dash", line_color="#888", line_width=1)
        layout_kwargs["yaxis"] = dict(zeroline=True, zerolinecolor="#888")
    fig.update_layout(**layout_kwargs)
    return fig


def make_destination_figure(view: ViewResult, *, top_n: int = 10) -> go.Figure | None:
    if view.destinations_mtd.empty:
        return None
    month_name = calendar.month_name[view.month]
    top = view.destinations_mtd.head(top_n)
    if view.flow_direction == "net_export":
        top = top.reindex(top.abs().sort_values(ascending=False).index).head(top_n)
    top = top.sort_values()
    colors = [
        "#e6550d" if v < 0 else "#6baed6"
        for v in top.values
    ]
    fig = go.Figure(
        go.Bar(
            x=top.values,
            y=top.index,
            orientation="h",
            marker_color=colors,
            text=[f"{v:,.0f}" for v in top.values],
            textposition="outside",
        )
    )
    fig.update_layout(
        title=(
            f"Top {view.counterparty_label} — {view.product_label} "
            f"{view.flow_direction_label} MTD — {month_name} {view.target_year}"
        ),
        xaxis_title=f"MTD {view.unit}",
        yaxis_title="",
        template="plotly_white",
        height=max(220, 40 + 28 * len(top)),
        margin=dict(l=10, r=40, t=50, b=40),
        showlegend=False,
    )
    return fig


def make_unknown_trade_status_panel(view: ViewResult) -> html.Div | None:
    """Break down country-Unknown counterparty volume by Kpler trade status."""
    from export_pace.unknown_trades import should_show_unknown_detail

    detail = view.unknown_trade_status
    if detail is None or not should_show_unknown_detail(view.destinations_mtd, detail):
        return None

    role = view.counterparty_label.rstrip("s")
    unit = view.unit
    total = float(detail.by_status.sum())
    rows: list = []
    max_val = float(detail.by_status.max())
    status_colors = {
        "In Transit": "#6baed6",
        "Loading": "#fd8d3c",
        "Scheduled": "#9e9ac8",
        "Delivered": "#74c476",
    }

    for status, kb in detail.by_status.items():
        pct = (kb / total * 100) if total > 0 else 0
        bar_pct = (kb / max_val * 100) if max_val > 0 else 0
        color = status_colors.get(status, "#6baed6")
        rows.append(
            html.Tr(
                [
                    html.Td(status, style={"width": "28%", "paddingRight": "8px"}),
                    html.Td(
                        html.Div(
                            html.Div(
                                style={
                                    "width": f"{bar_pct:.0f}%",
                                    "height": "14px",
                                    "backgroundColor": color,
                                    "borderRadius": "2px",
                                    "minWidth": "4px",
                                }
                            ),
                            style={
                                "backgroundColor": "#eef2f7",
                                "borderRadius": "2px",
                                "height": "14px",
                            },
                        ),
                        style={"width": "42%"},
                    ),
                    html.Td(
                        f"{kb:,.0f} {unit} ({pct:.0f}%)",
                        style={"width": "30%", "textAlign": "right", "whiteSpace": "nowrap"},
                    ),
                ]
            )
        )

    return html.Div(
        dbc.Card(
            dbc.CardBody(
                [
                    html.H6(f"Unknown {role} — by cargo status", className="mb-1"),
                    html.P(
                        f"{detail.unknown_country_kb:,.0f} {unit} with unconfirmed "
                        f"{role} country · {detail.n_cargos} cargo(s):",
                        className="text-muted small mb-2",
                    ),
                    html.Table(
                        [html.Tbody(rows)],
                        style={"width": "100%", "fontSize": "0.875rem"},
                    ),
                    html.Small(
                        "Source: Kpler Trades · status is fully populated even when destination is Unknown.",
                        className="text-muted d-block mt-2",
                    ),
                ]
            ),
            className="mt-2",
        )
    )


def make_unknown_detail_content(view: ViewResult) -> html.Div:
    return make_unknown_trade_status_panel(view) or html.Div()


def _installation_palette() -> list[str]:
    return [
        "#3182bd",
        "#6baed6",
        "#9ecae1",
        "#c6dbef",
        "#e6550d",
        "#fd8d3c",
        "#fdae6b",
        "#31a354",
    ]


def make_origin_cumulative_figure(view: ViewResult) -> go.Figure | None:
    """Cumulative MTD by installation — stacked area (exports/imports) or lines (net)."""
    if view.origin_cumulative is None or view.origin_cumulative.empty:
        return None
    month_name = calendar.month_name[view.month]
    role = installation_role_label(view.flow_direction)
    use_stacked = view.flow_direction != "net_export" and (view.origin_cumulative >= 0).all().all()
    fig = go.Figure()
    palette = _installation_palette()
    for i, col in enumerate(view.origin_cumulative.columns):
        trace_kwargs = dict(
            x=view.origin_cumulative.index,
            y=view.origin_cumulative[col],
            name=col,
            mode="lines",
            line=dict(
                width=2 if not use_stacked else 0.5,
                color=palette[i % len(palette)],
            ),
        )
        if use_stacked:
            trace_kwargs["stackgroup"] = "installations"
            trace_kwargs["fillcolor"] = palette[i % len(palette)]
        fig.add_trace(go.Scatter(**trace_kwargs))
    fig.update_layout(
        title=(
            f"Cumulative MTD by {role} — {view.location_label} — "
            f"{view.flow_direction_label} — {month_name} {view.target_year}"
        ),
        xaxis_title="Day of month",
        yaxis_title=f"Cumulative {view.unit} (MTD)",
        xaxis=dict(range=[1, 31], dtick=2),
        template="plotly_white",
        height=300,
        legend=dict(orientation="h", y=-0.22),
        margin=dict(b=80),
    )
    return fig


def make_heatmap_figure(view: ViewResult) -> go.Figure | None:
    if view.heatmap_pct.empty:
        return None
    month_name = calendar.month_name[view.month]
    z = view.heatmap_pct.values
    signed = view.flow_direction == "net_export"
    if signed:
        zlim = max(float(abs(z).max()), 1.0)
        heatmap_kwargs = dict(
            colorscale="RdBu",
            zmin=-zlim,
            zmax=zlim,
            zmid=0,
            colorbar=dict(title="Signed %"),
        )
        pace_note = " (signed % of month)"
    else:
        heatmap_kwargs = dict(
            colorscale="Blues",
            zmin=0,
            zmax=100,
            colorbar=dict(title="% of month"),
        )
        pace_note = ""
    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=view.heatmap_pct.columns,
            y=[str(y) for y in view.heatmap_pct.index],
            hovertemplate="Year %{y}<br>Day %{x}<br>%{z:.0f}%<extra></extra>",
            **heatmap_kwargs,
        )
    )
    fig.update_layout(
        title=(
            f"Month pacing heatmap — {view.flow_direction_label} — "
            f"{month_name} — {view.location_label}{pace_note}"
        ),
        xaxis_title="Day of month",
        yaxis_title="Year",
        template="plotly_white",
        height=max(220, 36 + 28 * len(view.heatmap_pct.index)),
        margin=dict(l=60, r=20, t=50, b=40),
    )
    return fig


def make_daily_figure(view: ViewResult, opts: FigureOptions | None = None) -> go.Figure:
    opts = opts or FigureOptions()
    month_name = calendar.month_name[view.month]
    unit_label = "kb" if view.unit == "kb" else "kbd"
    anomaly_set = set(view.anomaly_days) if opts.show_anomalies else set()
    signed = view.flow_direction == "net_export"

    def _bar_color(day: int, value: float) -> str:
        if day in anomaly_set:
            return "#e6550d"
        if signed and value < 0:
            return "#9e9ac8"
        return "#6baed6"

    fig = go.Figure()
    if view.realized_daily is not None:
        aligned_realized = view.realized_daily.reindex(view.current_daily.index).fillna(0)
        forecast_inc = (view.current_daily - aligned_realized).clip(lower=0)
        fig.add_trace(
            go.Bar(
                x=view.current_daily.index,
                y=aligned_realized.values,
                name="Realized",
                marker_color="#6baed6",
            )
        )
        fig.add_trace(
            go.Bar(
                x=view.current_daily.index,
                y=forecast_inc.values,
                name="Kpler forecast",
                marker_color="#fd8d3c",
            )
        )
        fig.update_layout(barmode="stack")
    else:
        fig.add_trace(
            go.Bar(
                x=view.current_daily.index,
                y=view.current_daily.values,
                name="Daily flows",
                marker_color=[
                    _bar_color(int(day), float(val))
                    for day, val in view.current_daily.items()
                ],
            )
        )

    anomaly_note = ""
    if anomaly_set:
        tail = ">2σ vs history" if not signed else ">2σ vs history (either direction)"
        anomaly_note = f" — {len(anomaly_set)} unusual day(s) flagged ({tail})"
    if view.realized_daily is not None:
        anomaly_note += " — stacked: realized + forecast"

    fig.update_layout(
        title=(
            f"Daily {view.product_label} {view.flow_direction_label} — "
            f"{month_name} {view.target_year}{anomaly_note}"
        ),
        xaxis_title="Day of month",
        yaxis_title=f"{unit_label} / day",
        xaxis=dict(range=[0.5, 31.5], dtick=2),
        template="plotly_white",
        height=280,
        margin=dict(t=50, b=50),
        showlegend=view.realized_daily is not None,
    )
    return fig


def make_data_status_line(view: ViewResult, *, refreshed_at: datetime | None = None) -> html.Div:
    parts: list[str] = []
    if view.latest_data_day:
        parts.append(f"Latest Kpler flow date: {view.latest_data_day.strftime('%d %b %Y')}")
    if view.as_of:
        parts.append(f"Chart truncated at: {view.as_of.strftime('%d %b %Y')}")
    if refreshed_at:
        parts.append(f"Refreshed: {refreshed_at.strftime('%H:%M:%S')}")
    if view.use_mock:
        parts.append("MOCK data")
    if view.anomaly_days:
        parts.append(f"Anomaly days: {', '.join(str(d) for d in view.anomaly_days)}")
    parts.append(
        "Intra-country: "
        f"{'on' if view.with_intra_country else 'off'} · "
        f"Intra-region: {'on' if view.with_intra_region else 'off'}"
    )
    if not parts:
        parts.append("No flow data in range")
    return html.Div(
        html.Small(" · ".join(parts), className="text-muted"),
        className="mb-2",
    )


def make_kpi_strip(view: ViewResult) -> list:
    if view.as_of is not None:
        dom = view.as_of.day
    elif len(view.current.index):
        dom = int(view.current.index[-1])
    else:
        dom = 1

    mtd = _value_at_day(view.current, dom)
    median = _value_at_day(view.band["median"], dom)
    last_yr = _value_at_day(view.last_yr, dom)
    days_elapsed = dom
    projected_eom = mtd / days_elapsed * view.days_in_month if days_elapsed else float("nan")

    def kpi_card(title: str, value: str, subtitle: str = "") -> dbc.Col:
        return dbc.Col(
            dbc.Card(
                dbc.CardBody(
                    [
                        html.Div(title, className="text-muted small"),
                        html.Div(value, className="fs-5 fw-semibold"),
                        html.Div(subtitle, className="text-muted small"),
                    ]
                ),
                className="h-100",
            ),
            lg=2,
            md=4,
            sm=6,
            xs=12,
        )

    pct = view.percentile_rank
    pct_text = f"{pct:.0f}th" if pct is not None and pct == pct else "—"
    pct_sub = f"vs {view.n_history} prior {calendar.month_name[view.month]}s" if pct is not None else ""
    mtd_sub = ""
    if view.flow_direction == "net_export" and mtd == mtd:
        mtd_sub = "positive = net exporter" if mtd >= 0 else "negative = net importer"
    proj_sub = "MTD / days elapsed × days in month"
    if view.flow_direction == "net_export":
        proj_sub += " (signed)"

    return dbc.Row(
        [
            kpi_card(
                f"MTD {view.flow_direction_label} (day {dom})",
                f"{mtd:,.0f} {view.unit}" if mtd == mtd else "—",
                mtd_sub,
            ),
            kpi_card("Historical percentile", pct_text, pct_sub),
            kpi_card(
                f"vs {view.n_history}y median",
                _pct_delta(mtd, median),
                f"median: {median:,.0f} {view.unit}" if median == median else "",
            ),
            kpi_card(
                "vs last year (same day)",
                _pct_delta(mtd, last_yr),
                f"last year: {last_yr:,.0f} {view.unit}" if last_yr == last_yr else "",
            ),
            kpi_card(
                "Run-rate month-end (proj.)",
                f"{projected_eom:,.0f} {view.unit}" if projected_eom == projected_eom else "—",
                proj_sub,
            ),
        ],
        className="g-3 mb-3",
    )
