"""Kpler Flows direction helpers — exports (from), imports (to), net exports."""

from __future__ import annotations

from typing import Literal

from export_pace.locations import LocationSelection

FlowDirectionId = Literal["export", "import", "net_export"]

FLOW_DIRECTION_OPTIONS = [
    {"label": "Exports", "value": "export"},
    {"label": "Imports", "value": "import"},
    {"label": "Net exports", "value": "net_export"},
]


def parse_flow_direction(value: str | None) -> FlowDirectionId:
    if value in ("export", "import", "net_export"):
        return value
    return "export"


def to_kpler_flows_direction(direction: FlowDirectionId):
    from kpler.sdk import FlowsDirection

    return {
        "export": FlowsDirection.Export,
        "import": FlowsDirection.Import,
        "net_export": FlowsDirection.NetExport,
    }[direction]


def flow_direction_label(direction: FlowDirectionId) -> str:
    return {
        "export": "exports",
        "import": "imports",
        "net_export": "net exports",
    }[direction]


def location_role_label(direction: FlowDirectionId) -> str:
    """Human label for what the zone/installation filters represent."""
    return {
        "export": "origin",
        "import": "destination",
        "net_export": "region",
    }[direction]


def flows_location_kwargs(direction: FlowDirectionId, locations: LocationSelection) -> list[dict]:
    """
    Kpler location filters for separate API calls.

    Exports / net exports: cargo leaving the selected geography (``from_*``).
    Imports: cargo arriving into the selected geography (``to_*``).
    """
    if direction == "import":
        calls: list[dict] = []
        if locations.zones:
            calls.append({"to_zones": list(locations.zones)})
        if locations.installations:
            calls.append({"to_installations": list(locations.installations)})
        return calls

    calls = []
    if locations.zones:
        calls.append({"from_zones": list(locations.zones)})
    if locations.installations:
        calls.append({"from_installations": list(locations.installations)})
    return calls


def counterparty_country_split(direction: FlowDirectionId):
    """Kpler split for the country/region breakdown bar chart."""
    from kpler.sdk import FlowsSplit

    return {
        "export": FlowsSplit.DestinationCountries,
        "import": FlowsSplit.OriginCountries,
        "net_export": FlowsSplit.DestinationCountries,
    }[direction]


def installation_split(direction: FlowDirectionId):
    """Kpler split for the per-installation MTD chart."""
    from kpler.sdk import FlowsSplit

    return {
        "export": FlowsSplit.OriginInstallations,
        "import": FlowsSplit.DestinationInstallations,
        "net_export": FlowsSplit.OriginInstallations,
    }[direction]


def counterparty_label(direction: FlowDirectionId) -> str:
    return {
        "export": "destinations",
        "import": "origins",
        "net_export": "destinations",
    }[direction]


def installation_role_label(direction: FlowDirectionId) -> str:
    return {
        "export": "origin installations",
        "import": "destination terminals",
        "net_export": "installations",
    }[direction]


def overlap_warning_for_direction(
    selection: LocationSelection,
    direction: FlowDirectionId,
) -> str | None:
    if not (selection.zones and selection.installations):
        return None
    role = location_role_label(direction)
    return (
        f"Zones and installations are queried separately and summed ({role} side). "
        "Avoid pairing a broad zone with a facility inside it."
    )
