# Export Pace — Kpler Flows Dash app

Interactive cumulative month-to-date (MTD) export pace chart built from the `kpler_exports_prototype.ipynb` notebook.

## Setup

```bash
cd products_exports_tracking
pip install -r requirements.txt
```

Add credentials to `.env`:

```
KPLER_EMAIL=you@example.com
KPLER_PASSWORD=...
```

For local UI development without API access:

```
USE_MOCK=true
```

## Run

**Use the same Python environment as the notebook** (`Coding\.venv`, Python 3.13).
The `dash_irr_database\.venv` does not include `kpler-sdk`.

```powershell
# from products_exports_tracking/
..\.venv\Scripts\Activate.ps1
python -m export_pace.app
```

Or:

```powershell
.\run.ps1
```

Open http://127.0.0.1:8050/

On startup the console prints the active data source, e.g. `Data source: Kpler Flows (live)`.
The page footer shows the same. If it says MOCK or mentions a missing package, fix that before expecting live data.

## Troubleshooting

| Footer / console says | Fix |
|-----------------------|-----|
| `MOCK (USE_MOCK=true)` | Set `USE_MOCK=false` in `.env` and restart the app |
| `kpler-sdk is not installed` | Activate `Coding\.venv` or `pip install kpler-sdk` |
| `KPLER_EMAIL / KPLER_PASSWORD missing` | Add credentials to `.env` (no quotes needed) |
| Chart title still says `(MOCK DATA)` | Restart app after changing `.env` |

## Location filters

Dropdown values are tagged as `zone:…` or `installation:…`. Kpler does **not** allow `from_zones` and `from_installations` in the same API request, so the app issues separate calls and sums daily totals when both types are selected.

Avoid combining a broad zone with a facility inside it (e.g. Oman + Duqm Refinery) — that can double-count.

### Finding locations in Kpler

The location dropdown is grouped:

| Group | Examples |
|-------|----------|
| **Favourites** | West Coast India, USGC (US Gulf Coast) |
| **Subregions** | West Coast India, East Coast India, … |
| **Custom / trading zones** | USGC (US Gulf Coast), Mideast Gulf, Greater ARA, … |
| **Countries** | All ~237 Kpler countries |

**USGC:** Kpler's exact name is `USGC (US Gulf Coast)` — type `USGC` or `gulf coast` in the search box, or pick it from Favourites / Custom zones.

**West Coast India:** listed under Subregions and Favourites (same as the Kpler web app).

Type 2+ characters to live-search ports, refineries, and anything else (`Yanbu`, `Rotterdam`, …). Installation-only names (e.g. `Duqm Refinery`) appear as a fallback when zone search returns nothing.

**Products:** The dropdown lists common desk products (Diesel, Gasoline, Gasoil, VLSFO, …). Type 2+ characters to search the full Kpler product catalog (e.g. `gasol`, `propane`).

Zone catalog is cached for a week in `.cache/kpler_zones.json`.

## v3 features (analytics)

- **Cumulative MTD by installation** — stacked area chart (replaces daily stacked bars) when one zone is selected
- **Month pacing heatmap** — years × day-of-month, color = % of that year's month-end total reached
- **Compare products** — overlay separate MTD curves per product (e.g. Diesel vs Gasoil) on the main chart
- **Volume anomaly flags** — daily bars highlighted when volume exceeds historical same-day median + 2σ; listed in status line

## v2 features (desk analytics)

- **Destination breakdown** — horizontal bar of top destination countries for the selected month (Kpler `DestinationCountries` split)
- **Installation stacked chart** — daily exports by origin installation when exactly one zone is selected (`OriginInstallations` split)
- **Historical percentile** — KPI showing where current MTD pace ranks vs prior same-months in the history band
- **Prior years (fan)** — overlay toggle draws thin grey curves for each year in the history window
- **Compare locations** — when multiple zones or installations are selected, overlay separate MTD curves instead of one combined total
- **Parquet disk cache** — historical `Total` flows cached under `.cache/flows/` (set `USE_DISK_CACHE=false` in `.env` to disable)

## v1.5 features

- **Refresh live data** — top-right button clears the live-month cache and re-pulls from Kpler
- **Daily bar chart** — non-cumulative daily exports below the MTD pace chart
- **Overlay toggles** — show/hide seasonal bands, median, last month, last year
- **Split location dropdowns** — zones/countries/ports separate from installations/facilities
- **Dynamic installations list** — populated from Kpler Flows `OriginInstallations` for your selected zones + products (cached 1 week)
- **Data-as-of line** — latest Kpler flow date and chart truncation date above the charts

### Installations dropdown

When you pick zones (e.g. West Coast India) and a product (e.g. Diesel), the app queries Kpler Flows with `split=OriginInstallations` over the last year and lists facilities that actually exported that product. Change zones or product to refresh the list. Use **Refresh live data** to force a re-pull.

## Layout

| Module | Role |
|--------|------|
| `export_pace/data.py` | Kpler Flows fetch, cache, v2 splits, `build_view()` |
| `export_pace/flows_disk_cache.py` | Optional parquet cache for historical bulk pulls |
| `export_pace/transform.py` | MTD cumulative curves and seasonal band |
| `export_pace/figure.py` | Plotly chart and KPI strip |
| `export_pace/dimensions.py` | Dropdown presets + optional Kpler search |
| `export_pace/app.py` | Dash layout and callbacks |
