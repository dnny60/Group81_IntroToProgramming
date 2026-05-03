from __future__ import annotations

from dataclasses import dataclass
import math
import re
import unicodedata
import xml.etree.ElementTree as ET


NS_PARKING = "http://datex2.eu/schema/3/parking"
NS_COMMON = "http://datex2.eu/schema/3/common"
NS_LOC = "http://datex2.eu/schema/3/locationReferencing"
NS_FACILITIES = "http://datex2.eu/schema/3/facilities"

PRICES = {
    "green": 0.80,
    "yellow": 1.20,
    "red": 1.60,
    "brown": 2.00,
}

COLOR_HEX = {
    "green": "#2ecc71",
    "yellow": "#f1c40f",
    "red": "#e74c3c",
    "brown": "#a0522d",
    "unknown": "#7f8c8d",
}

COLOR_LABELS = {
    "green": "Verde",
    "yellow": "Amarela",
    "red": "Vermelha",
    "brown": "Castanha",
    "unknown": "Unknown",
}

COLOR_FILTERS = ("green", "yellow", "red", "brown")


@dataclass(frozen=True)
class ParkingZone:
    polygon_id: int
    zone_id: str
    part_index: int
    coords: tuple[tuple[float, float], ...]
    holes: tuple[tuple[tuple[float, float], ...], ...]
    color: str
    product: str
    schedule: str
    additional_info: str
    point_count: int
    centroid_lat: float
    centroid_lon: float
    time_limit_hours: float | None


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return normalized.encode("ascii", "ignore").decode("ascii").lower()


def detect_zone_color(values: list[str]) -> str:
    exact_colors = {
        "verde": "green",
        "amarela": "yellow",
        "vermelha": "red",
        "castanha": "brown",
    }

    for value in values:
        color = exact_colors.get(normalize_text(value))
        if color:
            return color

    for value in values:
        text = normalize_text(value)
        if "verde" in text:
            return "green"
        if "amarela" in text:
            return "yellow"
        if "vermelha" in text:
            return "red"
        if "castanha" in text:
            return "brown"

    return "unknown"


def first_value_containing(values: list[str], needle: str) -> str | None:
    needle = normalize_text(needle)
    for value in values:
        if needle in normalize_text(value):
            return value
    return None


def extract_schedule(values: list[str]) -> str:
    for value in values:
        text = normalize_text(value)
        if "horas" in text or re.search(r"\d+\s*-\s*\d+\s*h", text) or " a " in text:
            return value
    return "Not specified"


def parse_time_limit_hours(*texts: str) -> float | None:
    searchable = normalize_text(" ".join(text for text in texts if text))
    patterns = (
        r"(?:maximo|max|limite|ate)\D{0,20}(\d+(?:[,.]\d+)?)\s*(?:h|horas?)",
        r"(\d+(?:[,.]\d+)?)\s*(?:h|horas?)\D{0,20}(?:maximo|max|limite)",
    )

    for pattern in patterns:
        match = re.search(pattern, searchable)
        if not match:
            continue
        try:
            return float(match.group(1).replace(",", "."))
        except ValueError:
            return None
    return None


def clean_ring(coords: list[tuple[float, float]]) -> tuple[tuple[float, float], ...]:
    if len(coords) > 1 and coords[0] == coords[-1]:
        coords = coords[:-1]
    return tuple(coords)


def split_closed_rings(block: str) -> list[tuple[tuple[float, float], ...]]:
    pairs = re.findall(r"\[(-?\d+\.\d+),\s*(-?\d+\.\d+)\]", block)
    rings: list[tuple[tuple[float, float], ...]] = []
    current: list[tuple[float, float]] = []
    start: tuple[float, float] | None = None

    for lon_str, lat_str in pairs:
        try:
            coord = (float(lat_str), float(lon_str))
        except ValueError:
            continue

        if not current:
            start = coord

        current.append(coord)
        if coord == start and len(current) >= 4:
            ring = clean_ring(current)
            if len(ring) >= 3:
                rings.append(ring)
            current = []
            start = None

    ring = clean_ring(current)
    if len(ring) >= 3:
        rings.append(ring)

    return rings


def ring_key(ring: tuple[tuple[float, float], ...]) -> tuple[tuple[float, float], ...]:
    rounded = tuple((round(lat, 6), round(lon, 6)) for lat, lon in ring)
    if not rounded:
        return rounded

    rotations = [rounded[index:] + rounded[:index] for index in range(len(rounded))]
    reversed_ring = tuple(reversed(rounded))
    rotations.extend(reversed_ring[index:] + reversed_ring[:index] for index in range(len(reversed_ring)))
    return min(rotations)


def point_in_ring(lat: float, lon: float, ring: tuple[tuple[float, float], ...]) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > lon) != (yj > lon)) and (lat < (xj - xi) * (lon - yi) / (yj - yi + 1e-9) + xi):
            inside = not inside
        j = i
    return inside


def ring_area_and_centroid(
    ring: tuple[tuple[float, float], ...],
    lon_scale: float,
) -> tuple[float, float, float] | None:
    if len(ring) < 3:
        return None

    cross_sum = 0.0
    centroid_x_sum = 0.0
    centroid_y_sum = 0.0

    for index, (lat1, lon1) in enumerate(ring):
        lat2, lon2 = ring[(index + 1) % len(ring)]
        x1 = lon1 * lon_scale
        x2 = lon2 * lon_scale
        cross = x1 * lat2 - x2 * lat1
        cross_sum += cross
        centroid_x_sum += (x1 + x2) * cross
        centroid_y_sum += (lat1 + lat2) * cross

    signed_area = cross_sum / 2
    if abs(signed_area) < 1e-12:
        return None

    centroid_lon = centroid_x_sum / (6 * signed_area * lon_scale)
    centroid_lat = centroid_y_sum / (6 * signed_area)
    return signed_area, centroid_lat, centroid_lon


def fallback_centroid(ring: tuple[tuple[float, float], ...]) -> tuple[float, float]:
    return (
        sum(coord[0] for coord in ring) / len(ring),
        sum(coord[1] for coord in ring) / len(ring),
    )


def polygon_centroid(
    outer: tuple[tuple[float, float], ...],
    holes: list[tuple[tuple[float, float], ...]],
) -> tuple[float, float]:
    reference_lat = sum(coord[0] for coord in outer) / len(outer)
    lon_scale = math.cos(math.radians(reference_lat)) or 1
    outer_result = ring_area_and_centroid(outer, lon_scale)
    if outer_result is None:
        return fallback_centroid(outer)

    outer_area, outer_lat, outer_lon = outer_result
    total_area = abs(outer_area)
    weighted_lat = outer_lat * total_area
    weighted_lon = outer_lon * total_area

    for hole in holes:
        hole_result = ring_area_and_centroid(hole, lon_scale)
        if hole_result is None:
            continue

        hole_area, hole_lat, hole_lon = hole_result
        hole_weight = abs(hole_area)
        total_area -= hole_weight
        weighted_lat -= hole_lat * hole_weight
        weighted_lon -= hole_lon * hole_weight

    if total_area <= 1e-12:
        return outer_lat, outer_lon

    return weighted_lat / total_area, weighted_lon / total_area


def add_geometry_group(
    groups: dict[
        tuple[tuple[float, float], ...],
        dict[str, object],
    ],
    outer: tuple[tuple[float, float], ...],
    hole: tuple[tuple[float, float], ...] | None = None,
) -> None:
    key = ring_key(outer)
    if key not in groups:
        groups[key] = {
            "outer": outer,
            "holes": [],
            "hole_keys": set(),
        }

    if hole is None:
        return

    hole_key = ring_key(hole)
    hole_keys = groups[key]["hole_keys"]
    holes = groups[key]["holes"]
    if isinstance(hole_keys, set) and isinstance(holes, list) and hole_key not in hole_keys:
        holes.append(hole)
        hole_keys.add(hole_key)


def load_parking_zones(xml_file: str) -> list[ParkingZone]:
    tree = ET.parse(xml_file)
    root = tree.getroot()
    parking_tables = root.findall(f".//{{{NS_PARKING}}}parkingTable")
    zones: list[ParkingZone] = []

    for table in parking_tables:
        values = [
            elem.text.strip()
            for elem in table.findall(f".//{{{NS_COMMON}}}value")
            if elem.text and elem.text.strip()
        ]
        product = first_value_containing(values, "Produto:") or "Not specified"
        schedule = extract_schedule(values)
        additional_info = next(
            (
                elem.text.strip()
                for elem in table.findall(f".//{{{NS_FACILITIES}}}additionalInformation")
                if elem.text and elem.text.strip()
            ),
            "Not specified",
        )
        color = detect_zone_color(values)
        time_limit_hours = parse_time_limit_hours(product, additional_info, schedule)
        geometry_groups: dict[tuple[tuple[float, float], ...], dict[str, object]] = {}

        for pos_list in table.findall(f".//{{{NS_LOC}}}posList"):
            if not pos_list.text:
                continue

            for block in pos_list.text.split(";"):
                rings = split_closed_rings(block)
                if not rings:
                    continue

                outer = rings[0]
                add_geometry_group(geometry_groups, outer)

                for ring in rings[1:]:
                    first_lat, first_lon = ring[0]
                    if point_in_ring(first_lat, first_lon, outer):
                        add_geometry_group(geometry_groups, outer, ring)
                    else:
                        add_geometry_group(geometry_groups, ring)

        for part_index, group in enumerate(geometry_groups.values(), start=1):
            coords = group["outer"]
            holes = group["holes"]
            if not isinstance(coords, tuple) or not isinstance(holes, list):
                continue

            centroid_lat, centroid_lon = polygon_centroid(coords, holes)
            point_count = len(coords) + sum(len(hole) for hole in holes)
            zones.append(
                ParkingZone(
                    polygon_id=len(zones) + 1,
                    zone_id=table.get("id", "Unknown"),
                    part_index=part_index,
                    coords=coords,
                    holes=tuple(holes),
                    color=color,
                    product=product,
                    schedule=schedule,
                    additional_info=additional_info,
                    point_count=point_count,
                    centroid_lat=centroid_lat,
                    centroid_lon=centroid_lon,
                    time_limit_hours=time_limit_hours,
                )
            )

    return zones
