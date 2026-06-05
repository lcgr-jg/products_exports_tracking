from __future__ import annotations

import json
import time
from functools import lru_cache
from pathlib import Path

from export_pace.config import load_settings
from export_pace.installations_catalog import (
    fetch_installations_catalog,
    installation_options_from_names,
    zone_names_from_values,
)
from export_pace.locations import as_filter_list, sanitize_location_values

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
ZONES_CACHE_FILE = CACHE_DIR / "kpler_zones.json"
LEGACY_COUNTRIES_CACHE = CACHE_DIR / "zone_countries.json"
ZONES_CACHE_TTL_SEC = 7 * 24 * 3600
SEARCH_MIN_CHARS = 2
SEARCH_RESULT_LIMIT = 40

# Desk favourites + names that differ from shorthand (USGC ≠ "USGC" in the API).
PRESET_ZONE_OPTIONS = [
    {"label": "West Coast India (subregion)", "value": "zone:West Coast India"},
    {"label": "East Coast India (subregion)", "value": "zone:East Coast India"},
    {"label": "USGC (US Gulf Coast) (custom)", "value": "zone:USGC (US Gulf Coast)"},
    {"label": "Mideast Gulf (custom)", "value": "zone:Mideast Gulf"},
    {"label": "Greater ARA (custom)", "value": "zone:Greater ARA"},
    {"label": "Russia (country)", "value": "zone:Russia"},
    {"label": "Saudi Arabia (country)", "value": "zone:Saudi Arabia"},
    {"label": "Oman (country)", "value": "zone:Oman"},
    {"label": "United Arab Emirates (country)", "value": "zone:United Arab Emirates"},
    {"label": "Yanbu (port)", "value": "zone:Yanbu"},
    {"label": "Fujairah (port)", "value": "zone:Fujairah"},
    {"label": "Ras Tanura (port)", "value": "zone:Ras Tanura"},
]

PRESET_INSTALLATION_OPTIONS = [
    {"label": "Duqm Refinery (installation)", "value": "installation:Duqm Refinery"},
]

PRESET_PRODUCT_OPTIONS = [
    {"label": "Diesel", "value": "Diesel"},
    {"label": "Gasoil", "value": "Gasoil"},
    {"label": "Crude", "value": "Crude"},
    {"label": "Jet", "value": "Jet"},
    {"label": "Naphtha", "value": "Naphtha"},
    {"label": "Fuel Oil", "value": "Fuel Oil"},
]


def _dedupe_options(options: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for opt in options:
        if "options" in opt:
            grouped = _dedupe_options(opt["options"])
            if grouped:
                out.append({"label": opt["label"], "options": grouped})
            continue
        val = opt["value"]
        if val not in seen:
            seen.add(val)
            out.append(opt)
    return out


def _flatten_option_groups(options: list[dict]) -> list[dict]:
    """Dash multi-select breaks with optgroups — use a flat labelled list instead."""
    flat: list[dict] = []
    for opt in options:
        if "options" in opt:
            for child in opt["options"]:
                flat.append(
                    {
                        "label": f"{opt['label']} › {child['label']}",
                        "value": child["value"],
                    }
                )
        else:
            flat.append(opt)
    return _dedupe_options(flat)


def _try_load_kpler_clients():
    settings = load_settings()
    if settings.use_mock or not settings.kpler_email or not settings.kpler_password:
        return None, None
    try:
        from kpler.sdk import Platform
        from kpler.sdk.configuration import Configuration
        from kpler.sdk.resources.products import Products
        from kpler.sdk.resources.zones import Zones

        config = Configuration(Platform.Liquids, settings.kpler_email, settings.kpler_password)
        return Zones(config), Products(config)
    except Exception:
        return None, None


def _option_from_value(value: str | None) -> dict | None:
    if not value or not isinstance(value, str):
        return None
    if value.startswith("zone:"):
        name = value.removeprefix("zone:")
        return {"label": name, "value": value}
    if value.startswith("installation:"):
        name = value.removeprefix("installation:")
        return {"label": f"{name} (installation)", "value": value}
    return {"label": value, "value": f"zone:{value}"}


def _zone_option(name: str, zone_type: str) -> dict:
    return {"label": f"{name} ({zone_type})", "value": f"zone:{name}"}


def _read_zones_cache() -> dict | None:
    for path in (ZONES_CACHE_FILE, LEGACY_COUNTRIES_CACHE):
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - payload.get("fetched_at", 0) > ZONES_CACHE_TTL_SEC:
                return None
            if path == LEGACY_COUNTRIES_CACHE and "countries" in payload:
                return {
                    "countries": payload["countries"],
                    "subregions": [],
                    "custom": [],
                    "regions": [],
                }
            if "countries" in payload:
                return payload
        except (json.JSONDecodeError, OSError, TypeError):
            continue
    return None


def _write_zones_cache(payload: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload["fetched_at"] = time.time()
    ZONES_CACHE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _fetch_zone_catalog(zones_client) -> dict:
    catalog = {"countries": [], "subregions": [], "custom": [], "regions": []}
    for key, zone_type in (
        ("countries", "country"),
        ("subregions", "subregion"),
        ("custom", "custom"),
        ("regions", "region"),
    ):
        df = zones_client.get(descendant_type=zone_type)
        catalog[key] = sorted(df["descendant_name"].dropna().astype(str).unique().tolist())
    return catalog


@lru_cache(maxsize=1)
def _get_zone_catalog() -> dict:
    cached = _read_zones_cache()
    if cached is not None and cached.get("subregions"):
        return cached

    zones_client, _ = _try_load_kpler_clients()
    if zones_client is None:
        return cached or {"countries": [], "subregions": [], "custom": [], "regions": []}

    try:
        catalog = _fetch_zone_catalog(zones_client)
        _write_zones_cache(catalog)
        print(
            "Cached Kpler zones:",
            f"{len(catalog['countries'])} countries,",
            f"{len(catalog['subregions'])} subregions,",
            f"{len(catalog['custom'])} custom,",
            f"{len(catalog['regions'])} regions",
        )
        return catalog
    except Exception as exc:
        print(f"Could not load Kpler zone catalog: {exc}")
        return cached or {"countries": [], "subregions": [], "custom": [], "regions": []}


def _catalog_group_options(key: str, zone_type: str) -> list[dict]:
    catalog = _get_zone_catalog()
    return [_zone_option(name, zone_type) for name in catalog.get(key, [])]


def get_base_zone_options() -> list[dict]:
    """Zones / countries / ports / subregions — flat list for the zones dropdown."""
    grouped = [
        {"label": "Favourites", "options": PRESET_ZONE_OPTIONS},
        {"label": "Subregions", "options": _catalog_group_options("subregions", "subregion")},
        {"label": "Custom zones", "options": _catalog_group_options("custom", "custom")},
        {"label": "Regions", "options": _catalog_group_options("regions", "region")},
        {"label": "Countries", "options": _catalog_group_options("countries", "country")},
    ]
    return _flatten_option_groups(grouped)


def get_base_installation_options() -> list[dict]:
    return list(PRESET_INSTALLATION_OPTIONS)


def get_base_location_options() -> list[dict]:
    return _dedupe_options(get_base_zone_options() + get_base_installation_options())


def search_kpler_zone_options(query: str) -> list[dict]:
    zones_client, _ = _try_load_kpler_clients()
    if zones_client is None:
        return []

    try:
        hits = zones_client.search(query)
        col = "zones" if "zones" in hits.columns else hits.columns[0]
        names = hits[col].dropna().astype(str).tolist()[:SEARCH_RESULT_LIMIT]
        return [_zone_option(name, "zone") for name in names]
    except Exception:
        return []


def _zone_only(values: list[str] | None) -> list[str]:
    return [v for v in sanitize_location_values(values) if v.startswith("zone:")]


def _installation_only(values: list[str] | None) -> list[str]:
    return [v for v in sanitize_location_values(values) if v.startswith("installation:")]


def merge_zone_dropdown_options(
    search_value: str | None,
    selected_values: list[str] | None,
) -> list[dict]:
    selected = _zone_only(selected_values)
    selected_opts = [o for o in (_option_from_value(v) for v in selected) if o]
    query = (search_value or "").strip()

    if len(query) < SEARCH_MIN_CHARS:
        return _dedupe_options(selected_opts + get_base_zone_options())

    zone_hits = search_kpler_zone_options(query)
    options = selected_opts + zone_hits
    if not zone_hits:
        options.append(
            {
                "label": f'Use "{query}" as zone (exact Kpler name)',
                "value": f"zone:{query}",
            }
        )
    return _dedupe_options(options)


def get_dynamic_installation_options(
    zone_values: list[str] | None,
    product_values: list[str] | None,
    search_value: str | None,
    selected_values: list[str] | None,
    *,
    force_refresh: bool = False,
) -> list[dict]:
    """
    Installations dropdown:
    - Default: Kpler Flows OriginInstallations catalog for selected zones + products
    - While typing (2+ chars): zone search + exact-name fallback
    """
    selected = _installation_only(selected_values)
    selected_opts = [o for o in (_option_from_value(v) for v in selected) if o]
    query = (search_value or "").strip()

    if len(query) >= SEARCH_MIN_CHARS:
        return merge_installation_dropdown_options(search_value, selected_values)

    zones = zone_names_from_values(zone_values)
    products = [p for p in as_filter_list(product_values) if isinstance(p, str) and p]
    if zones and products:
        names = fetch_installations_catalog(zones, products, force_refresh=force_refresh)
        catalog_opts = installation_options_from_names(names)
    else:
        catalog_opts = list(PRESET_INSTALLATION_OPTIONS)

    return _dedupe_options(selected_opts + catalog_opts)


def merge_installation_dropdown_options(
    search_value: str | None,
    selected_values: list[str] | None,
) -> list[dict]:
    selected = _installation_only(selected_values)
    selected_opts = [o for o in (_option_from_value(v) for v in selected) if o]
    query = (search_value or "").strip()

    if len(query) < SEARCH_MIN_CHARS:
        return _dedupe_options(selected_opts + get_base_installation_options())

    zones_client, _ = _try_load_kpler_clients()
    options = list(selected_opts)
    if zones_client is not None:
        try:
            hits = zones_client.search(query)
            col = "zones" if "zones" in hits.columns else hits.columns[0]
            for name in hits[col].dropna().astype(str).tolist()[:SEARCH_RESULT_LIMIT]:
                if "refinery" in name.lower() or "terminal" in name.lower():
                    options.append(
                        {
                            "label": f"{name} (installation?)",
                            "value": f"installation:{name}",
                        }
                    )
        except Exception:
            pass

    install_value = f"installation:{query}"
    if not any(opt["value"] == install_value for opt in options):
        options.append(
            {
                "label": f'Use "{query}" as installation (exact Kpler name)',
                "value": install_value,
            }
        )
    return _dedupe_options(options)


def merge_location_dropdown_options(
    search_value: str | None,
    selected_values: list[str] | None,
) -> list[dict]:
    """Legacy combined merge — zones + installations."""
    return _dedupe_options(
        merge_zone_dropdown_options(search_value, selected_values)
        + merge_installation_dropdown_options(search_value, selected_values)
    )


def search_product_options(query: str) -> list[dict]:
    _, products_client = _try_load_kpler_clients()
    if products_client is None:
        return []

    try:
        hits = products_client.search(query)
        col = "products" if "products" in hits.columns else hits.columns[0]
        names = hits[col].dropna().astype(str).tolist()[:SEARCH_RESULT_LIMIT]
        return [{"label": name, "value": name} for name in names]
    except Exception:
        return []


def get_base_product_options() -> list[dict]:
    return list(PRESET_PRODUCT_OPTIONS)


def merge_product_dropdown_options(
    search_value: str | None,
    selected_values: list[str] | None,
) -> list[dict]:
    selected = [v for v in as_filter_list(selected_values) if isinstance(v, str) and v]
    selected_opts = [{"label": v, "value": v} for v in selected]
    query = (search_value or "").strip()

    if len(query) < SEARCH_MIN_CHARS:
        return _dedupe_options(selected_opts + get_base_product_options())

    return _dedupe_options(selected_opts + search_product_options(query))


def get_location_options() -> list[dict]:
    return get_base_location_options()


def get_product_options() -> list[dict]:
    return get_base_product_options()


def month_options() -> list[dict]:
    import calendar

    return [{"label": calendar.month_name[i], "value": i} for i in range(1, 13)]


def year_options() -> list[dict]:
    from datetime import date

    current = date.today().year
    return [{"label": str(y), "value": y} for y in range(current, current - 8, -1)]


def history_options() -> list[dict]:
    return [
        {"label": "3 years", "value": 3},
        {"label": "5 years", "value": 5},
        {"label": "10 years", "value": 10},
    ]
