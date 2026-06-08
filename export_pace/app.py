from __future__ import annotations

from datetime import date, datetime

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, ctx, dcc, html, no_update

from export_pace.config import kpler_sdk_available, load_settings
from export_pace.flow_direction import FLOW_DIRECTION_OPTIONS, location_role_label, parse_flow_direction
from export_pace.data import get_data_service
from export_pace.dimensions import (
    get_base_product_options,
    get_base_zone_options,
    get_dynamic_installation_options,
    history_options,
    merge_product_dropdown_options,
    merge_zone_dropdown_options,
    month_options,
    year_options,
)
from export_pace.installations_catalog import clear_installation_catalog_cache
from export_pace.figure import (
    FigureOptions,
    make_daily_figure,
    make_data_status_line,
    make_destination_figure,
    make_figure,
    make_heatmap_figure,
    make_kpi_strip,
    make_origin_cumulative_figure,
)
from export_pace.locations import (
    as_filter_list,
    combine_location_dropdowns,
)

settings = load_settings()
today = date.today()

OVERLAY_DEFAULTS = ["bands", "median", "last_month", "last_year", "anomalies"]


def _data_source_status() -> str:
    if settings.use_mock:
        return "Data source: MOCK (USE_MOCK=true in .env)"
    if not settings.kpler_email or not settings.kpler_password:
        return "Data source: LIVE requested but KPLER_EMAIL / KPLER_PASSWORD missing in .env"
    if not kpler_sdk_available():
        return "Data source: LIVE requested but kpler-sdk is not installed (pip install kpler-sdk)"
    return "Data source: Kpler Flows (live)"


app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.FLATLY],
    title="Export Pace — Kpler Flows",
    suppress_callback_exceptions=True,
)

ZONE_OPTIONS = get_base_zone_options()
PRODUCT_OPTIONS = get_base_product_options()

app.layout = dbc.Container(
    [
        dbc.Row(
            [
                dbc.Col(
                    [
                        html.H2("Cumulative MTD Flow Pace", className="mt-4 mb-1"),
                        html.P(
                            "Kpler Flows daily exports, imports, or net exports with seasonal bands.",
                            className="text-muted mb-0",
                        ),
                    ],
                    md=9,
                ),
                dbc.Col(
                    dbc.Button(
                        "Refresh live data",
                        id="refresh-btn",
                        color="secondary",
                        outline=True,
                        className="mt-4 float-end",
                    ),
                    md=3,
                ),
            ]
        ),
        dbc.Alert(id="status-alert", is_open=False, color="warning", className="mt-2"),
        dbc.Card(
            dbc.CardBody(
                dbc.Row(
                    [
                        dbc.Col(
                            [
                                html.Label("Flow direction"),
                                dbc.RadioItems(
                                    id="flow-direction",
                                    options=FLOW_DIRECTION_OPTIONS,
                                    value="export",
                                    inline=True,
                                ),
                            ],
                            md=12,
                        ),
                        dbc.Col(
                            [
                                html.Label(id="zones-label"),
                                dcc.Dropdown(
                                    id="locations-zones",
                                    options=ZONE_OPTIONS,
                                    value=["zone:West Coast India"],
                                    multi=True,
                                    searchable=True,
                                    placeholder="West Coast India, USGC, Oman, Yanbu…",
                                ),
                            ],
                            md=6,
                        ),
                        dbc.Col(
                            [
                                html.Label(id="installations-label"),
                                dcc.Dropdown(
                                    id="locations-installations",
                                    options=[],
                                    value=[],
                                    multi=True,
                                    searchable=True,
                                    placeholder="Select zones + product first, or type to search…",
                                ),
                            ],
                            md=6,
                        ),
                        dbc.Col(
                            [
                                html.Label("Products (type 2+ chars to search)"),
                                dcc.Dropdown(
                                    id="products",
                                    options=PRODUCT_OPTIONS,
                                    value=["Diesel"],
                                    multi=True,
                                    searchable=True,
                                ),
                            ],
                            md=6,
                        ),
                        dbc.Col(
                            [
                                html.Label("Chart overlays"),
                                dbc.Checklist(
                                    id="overlay-toggles",
                                    options=[
                                        {"label": "Seasonal bands", "value": "bands"},
                                        {"label": "Median", "value": "median"},
                                        {"label": "Last month", "value": "last_month"},
                                        {"label": "Last year", "value": "last_year"},
                                        {"label": "Prior years (fan)", "value": "hist_years"},
                                        {"label": "Compare locations", "value": "compare_locations"},
                                        {"label": "Compare products", "value": "compare_products"},
                                        {"label": "Flag volume anomalies", "value": "anomalies"},
                                    ],
                                    value=OVERLAY_DEFAULTS,
                                    inline=True,
                                ),
                            ],
                            md=6,
                        ),
                        dbc.Col(
                            [
                                html.Label("Month"),
                                dcc.Dropdown(
                                    id="month",
                                    options=month_options(),
                                    value=today.month,
                                    clearable=False,
                                ),
                            ],
                            md=2,
                        ),
                        dbc.Col(
                            [
                                html.Label("Year"),
                                dcc.Dropdown(
                                    id="year",
                                    options=year_options(),
                                    value=today.year,
                                    clearable=False,
                                ),
                            ],
                            md=2,
                        ),
                        dbc.Col(
                            [
                                html.Label("As-of day"),
                                dcc.Slider(
                                    id="as-of-day",
                                    min=1,
                                    max=31,
                                    step=1,
                                    value=today.day,
                                    marks={1: "1", 15: "15", 31: "31"},
                                ),
                                dbc.Checklist(
                                    id="use-live-as-of",
                                    options=[{"label": "Use today for live month", "value": "live"}],
                                    value=["live"],
                                    className="mt-2",
                                ),
                            ],
                            md=4,
                        ),
                        dbc.Col(
                            [
                                html.Label("History band"),
                                dcc.Dropdown(
                                    id="n-history",
                                    options=history_options(),
                                    value=5,
                                    clearable=False,
                                ),
                            ],
                            md=2,
                        ),
                        dbc.Col(
                            [
                                html.Label("Live month forecast"),
                                dbc.Checklist(
                                    id="with-forecast-live",
                                    options=[{"label": "Include Kpler forecast", "value": "on"}],
                                    value=[],
                                ),
                            ],
                            md=2,
                        ),
                        dbc.Col(
                            [
                                html.Label("Flow scope"),
                                dbc.Checklist(
                                    id="intra-flow-toggles",
                                    options=[
                                        {
                                            "label": "Include intra-country flows",
                                            "value": "intra_country",
                                        },
                                        {
                                            "label": "Include intra-region flows",
                                            "value": "intra_region",
                                        },
                                    ],
                                    value=["intra_region"],
                                    inline=True,
                                ),
                            ],
                            md=4,
                        ),
                    ],
                    className="g-3",
                )
            ),
            className="mb-3",
        ),
        html.Div(id="data-status"),
        html.Div(id="kpi-strip"),
        dcc.Loading(dcc.Graph(id="chart"), type="circle", color="#2171b5"),
        dcc.Loading(dcc.Graph(id="daily-chart"), type="dot", color="#6baed6"),
        dcc.Loading(dcc.Graph(id="heatmap-chart"), type="dot", color="#2171b5"),
        dbc.Row(
            [
                dbc.Col(dcc.Loading(dcc.Graph(id="destination-chart"), type="dot", color="#6baed6"), md=6),
                dbc.Col(dcc.Loading(dcc.Graph(id="origin-chart"), type="dot", color="#3182bd"), md=6),
            ],
            className="g-3 mb-3",
        ),
        html.Div(
            html.Small(
                f"{_data_source_status()} · Realized flows may lag 1–2 days.",
                className="text-muted",
            ),
            className="mb-4 mt-2",
        ),
        dcc.Store(id="last-refresh", data=None),
    ],
    fluid=True,
)


def _sanitize_zones(values):
    return [v for v in as_filter_list(values) if isinstance(v, str) and v.startswith("zone:")]


def _sanitize_installations(values):
    return [
        v for v in as_filter_list(values) if isinstance(v, str) and v.startswith("installation:")
    ]


def _intra_flow_flags(toggles: list[str] | None) -> tuple[bool, bool]:
    selected = toggles or []
    return "intra_country" in selected, "intra_region" in selected


@app.callback(
    Output("zones-label", "children"),
    Output("installations-label", "children"),
    Input("flow-direction", "value"),
)
def update_location_labels(flow_direction):
    direction = parse_flow_direction(flow_direction)
    role = location_role_label(direction)
    if direction == "import":
        zones = (
            f"Destination zones / countries / ports — imports arriving into selection "
            f"(type 2+ chars to search)"
        )
        installs = f"Destination installations / facilities ({role})"
    elif direction == "net_export":
        zones = "Zones / countries / ports — net export balance (type 2+ chars to search)"
        installs = f"Installations / facilities ({role})"
    else:
        zones = "Origin zones / countries / ports (type 2+ chars to search)"
        installs = f"Origin installations / facilities ({role})"
    return zones, installs


@app.callback(
    Output("locations-zones", "options"),
    Input("locations-zones", "search_value"),
    State("locations-zones", "value"),
    prevent_initial_call=True,
)
def update_zone_options(search_value, selected_values):
    query = (search_value or "").strip()
    if len(query) < 2:
        return get_base_zone_options() if not query else no_update
    return merge_zone_dropdown_options(query, selected_values)


@app.callback(
    Output("locations-zones", "value"),
    Input("locations-zones", "value"),
    prevent_initial_call=True,
)
def clean_zone_selection(selected_values):
    clean = _sanitize_zones(selected_values)
    original = as_filter_list(selected_values)
    if len(clean) == len(original) and all(a == b for a, b in zip(clean, original)):
        return no_update
    return clean


@app.callback(
    Output("locations-installations", "options"),
    Input("locations-zones", "value"),
    Input("products", "value"),
    Input("flow-direction", "value"),
    Input("intra-flow-toggles", "value"),
    Input("locations-installations", "search_value"),
    Input("refresh-btn", "n_clicks"),
    State("locations-installations", "value"),
)
def update_installation_options(
    zone_values,
    product_values,
    flow_direction,
    intra_toggles,
    search_value,
    refresh_clicks,
    selected_values,
):
    force = ctx.triggered_id == "refresh-btn"
    intra_country, intra_region = _intra_flow_flags(intra_toggles)
    return get_dynamic_installation_options(
        zone_values,
        product_values,
        search_value,
        selected_values,
        flow_direction=parse_flow_direction(flow_direction),
        with_intra_country=intra_country,
        with_intra_region=intra_region,
        force_refresh=force,
    )


@app.callback(
    Output("locations-installations", "value"),
    Input("locations-installations", "value"),
    Input("flow-direction", "value"),
    prevent_initial_call=True,
)
def clean_installation_selection(selected_values, flow_direction):
    if ctx.triggered_id == "flow-direction":
        return []
    clean = _sanitize_installations(selected_values)
    original = as_filter_list(selected_values)
    if len(clean) == len(original) and all(a == b for a, b in zip(clean, original)):
        return no_update
    return clean


@app.callback(
    Output("products", "options"),
    Input("products", "search_value"),
    State("products", "value"),
    prevent_initial_call=True,
)
def update_product_options(search_value, selected_values):
    query = (search_value or "").strip()
    if len(query) < 2:
        return get_base_product_options() if not query else no_update
    return merge_product_dropdown_options(query, selected_values)


@app.callback(
    Output("as-of-day", "max"),
    Input("month", "value"),
    Input("year", "value"),
)
def update_as_of_max(month, year):
    if not month or not year:
        return 31
    import calendar

    return calendar.monthrange(int(year), int(month))[1]


@app.callback(
    Output("chart", "figure"),
    Output("daily-chart", "figure"),
    Output("destination-chart", "figure"),
    Output("origin-chart", "figure"),
    Output("heatmap-chart", "figure"),
    Output("kpi-strip", "children"),
    Output("data-status", "children"),
    Output("status-alert", "children"),
    Output("status-alert", "is_open"),
    Output("status-alert", "color"),
    Output("last-refresh", "data"),
    Input("locations-zones", "value"),
    Input("locations-installations", "value"),
    Input("products", "value"),
    Input("month", "value"),
    Input("year", "value"),
    Input("as-of-day", "value"),
    Input("use-live-as-of", "value"),
    Input("n-history", "value"),
    Input("with-forecast-live", "value"),
    Input("overlay-toggles", "value"),
    Input("flow-direction", "value"),
    Input("intra-flow-toggles", "value"),
    Input("refresh-btn", "n_clicks"),
    State("last-refresh", "data"),
)
def update_view(
    zone_values,
    installation_values,
    product_values,
    month,
    year,
    as_of_day,
    use_live_as_of,
    n_history,
    with_forecast_live,
    overlay_toggles,
    flow_direction,
    intra_toggles,
    refresh_clicks,
    last_refresh,
):
    zones = _sanitize_zones(zone_values)
    installations = _sanitize_installations(installation_values)
    locations = combine_location_dropdowns(zones, installations)

    if locations.is_empty:
        empty = make_figure_placeholder("Select at least one zone or installation.")
        return (
            empty,
            empty,
            empty,
            empty,
            empty,
            [],
            html.Div(),
            "Select at least one zone or installation.",
            True,
            "warning",
            last_refresh,
        )
    if not product_values:
        empty = make_figure_placeholder("Select at least one product.")
        return (
            empty,
            empty,
            empty,
            empty,
            empty,
            [],
            html.Div(),
            "Select at least one product.",
            True,
            "warning",
            last_refresh,
        )

    service = get_data_service()
    refreshed_at = None
    if ctx.triggered_id == "refresh-btn":
        service.refresh_live_cache()
        clear_installation_catalog_cache()
        refreshed_at = datetime.now()
        last_refresh = refreshed_at.isoformat()
    elif last_refresh:
        try:
            refreshed_at = datetime.fromisoformat(last_refresh)
        except ValueError:
            refreshed_at = None

    forecast_on = "on" in (with_forecast_live or [])
    intra_country, intra_region = _intra_flow_flags(intra_toggles)
    toggles = overlay_toggles or []
    fig_opts = FigureOptions(
        show_bands="bands" in toggles,
        show_median="median" in toggles,
        show_last_month="last_month" in toggles,
        show_last_year="last_year" in toggles,
        show_hist_years="hist_years" in toggles,
        compare_locations="compare_locations" in toggles,
        compare_products="compare_products" in toggles,
        show_anomalies="anomalies" in toggles,
    )

    is_live_month = year == today.year and month == today.month
    resolved_as_of_day = None
    if not (is_live_month and "live" in (use_live_as_of or [])):
        resolved_as_of_day = as_of_day

    try:
        view = service.build_view(
            locations=locations,
            products=product_values,
            month=int(month),
            target_year=int(year),
            n_history=int(n_history or 5),
            as_of_day=resolved_as_of_day,
            with_forecast_live=forecast_on,
            compare_locations=fig_opts.compare_locations,
            compare_products=fig_opts.compare_products,
            flow_direction=parse_flow_direction(flow_direction),
            with_intra_country=intra_country,
            with_intra_region=intra_region,
        )
    except Exception as exc:
        empty = make_figure_placeholder(f"Error loading data: {exc}")
        return empty, empty, empty, empty, empty, [], html.Div(), str(exc), True, "danger", last_refresh

    dest_fig = make_destination_figure(view) or make_figure_placeholder(
        f"No {view.counterparty_label} breakdown for this selection."
    )
    origin_fig = make_origin_cumulative_figure(view) or make_figure_placeholder(
        "Installation breakdown appears when exactly one zone is selected (no facilities)."
    )
    heatmap_fig = make_heatmap_figure(view) or make_figure_placeholder(
        "No heatmap data for this selection."
    )

    alert_msg = view.warning
    return (
        make_figure(view, fig_opts),
        make_daily_figure(view, fig_opts),
        dest_fig,
        origin_fig,
        heatmap_fig,
        make_kpi_strip(view),
        make_data_status_line(view, refreshed_at=refreshed_at),
        alert_msg,
        bool(alert_msg),
        "warning",
        last_refresh,
    )


def make_figure_placeholder(message: str):
    import plotly.graph_objects as go

    fig = go.Figure()
    fig.update_layout(
        title=message,
        template="plotly_white",
        height=480,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        annotations=[
            dict(
                text=message,
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
                font=dict(size=14, color="#666"),
            )
        ],
    )
    return fig


if __name__ == "__main__":
    print(_data_source_status())
    app.run(debug=False, host="127.0.0.1", port=8050)
