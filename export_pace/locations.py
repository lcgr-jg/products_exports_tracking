from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LocationSelection:
    zones: tuple[str, ...]
    installations: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        return not self.zones and not self.installations

    @property
    def cache_key(self) -> tuple[str, ...]:
        return tuple(f"zone:{name}" for name in self.zones) + tuple(
            f"installation:{name}" for name in self.installations
        )


# Dash optgroup headers must never be stored as selected values.
GROUP_HEADER_VALUES = frozenset({
    "Favourites",
    "Subregions (e.g. West Coast India)",
    "Custom / trading zones (e.g. USGC)",
    "Regions",
    "Countries",
})


def as_filter_list(value: str | list[str] | None) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value] if value else []
    return [v for v in value if v]


def sanitize_location_values(values: list[str] | str | None) -> list[str]:
    """Drop nulls and optgroup labels that Dash can accidentally write as values."""
    clean: list[str] = []
    for raw in as_filter_list(values):
        if not isinstance(raw, str):
            continue
        text = raw.strip()
        if not text or text in GROUP_HEADER_VALUES:
            continue
        clean.append(text)
    return clean


def combine_location_dropdowns(
    zone_values: list[str] | None,
    installation_values: list[str] | None,
) -> LocationSelection:
    """Merge separate zone and installation multi-selects into one LocationSelection."""
    tagged: list[str] = []
    for raw in sanitize_location_values(zone_values):
        tagged.append(raw if raw.startswith("zone:") else f"zone:{raw}")
    for raw in sanitize_location_values(installation_values):
        tagged.append(raw if raw.startswith("installation:") else f"installation:{raw}")
    return parse_tagged_locations(tagged)


def parse_tagged_locations(values: list[str] | None) -> LocationSelection:
    """Parse dropdown values like ``zone:Oman`` or ``installation:Duqm Refinery``."""
    zones: list[str] = []
    installations: list[str] = []
    for raw in sanitize_location_values(values):
        if raw.startswith("zone:"):
            zones.append(raw.removeprefix("zone:"))
        elif raw.startswith("installation:"):
            installations.append(raw.removeprefix("installation:"))
        else:
            # Untagged legacy values are treated as zones (matches notebook behaviour).
            zones.append(raw)
    return LocationSelection(tuple(zones), tuple(installations))


def location_label(selection: LocationSelection, *, sep: str = ", ") -> str:
    parts = [*(selection.zones), *(selection.installations)]
    if not parts:
        return "—"
    return parts[0] if len(parts) == 1 else sep.join(parts)


def overlap_warning(selection: LocationSelection) -> str | None:
    """Warn when zones and installations are combined — API needs two calls; overlap may double-count."""
    if selection.zones and selection.installations:
        return (
            "Zones and installations are queried separately and summed. "
            "Avoid pairing a broad zone with a facility inside it (e.g. Oman + Duqm Refinery)."
        )
    return None
