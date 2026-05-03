from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math
import re
import unicodedata

from parking_data import PRICES, ParkingZone


WALKING_SPEED_M_PER_MIN = 5000 / 60


@dataclass
class ZoneResult:
    zone: ParkingZone
    distance_m: float
    hourly_price: float | None
    total_cost: float | None
    savings: float | None
    score: float | None
    billable_hours: float
    billing_note: str
    walking_time_min: float
    warning: str
    is_current: bool = False
    is_cheapest: bool = False
    is_optimal: bool = False
    is_closest: bool = False
    route_distance_m: float | None = None
    route_is_fallback: bool = True


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_m = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius_m * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def point_in_polygon(lat: float, lon: float, polygon: tuple[tuple[float, float], ...]) -> bool:
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > lon) != (yj > lon)) and (lat < (xj - xi) * (lon - yi) / (yj - yi + 1e-9) + xi):
            inside = not inside
        j = i
    return inside


def walking_time_from_distance(distance_m: float) -> float:
    return distance_m / WALKING_SPEED_M_PER_MIN


def normalize_schedule_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return normalized.encode("ascii", "ignore").decode("ascii").lower()


def parse_schedule_windows(schedule: str) -> list[tuple[set[int], int, int]]:
    text = normalize_schedule_text(schedule)
    if "24 horas" in text:
        return [(set(range(7)), 0, 24 * 60)]

    windows: list[tuple[set[int], int, int]] = []
    hour_pattern = re.compile(
        r"(?<!\d)(\d{1,2})\s*h?\s*(?:-|as|ate)\s*(\d{1,2})\s*h"
    )

    for segment in text.split("|"):
        segment = segment.strip()
        if not segment:
            continue

        days = set(range(7))
        if "2a a 6a" in segment:
            days = set(range(5))
        elif "sab" in segment:
            days = {5}
        elif "dom" in segment:
            days = {6}

        match = hour_pattern.search(segment)
        if not match:
            continue

        start_hour = int(match.group(1))
        end_hour = int(match.group(2))
        if not (0 <= start_hour <= 24 and 0 <= end_hour <= 24):
            continue

        windows.append((days, start_hour * 60, end_hour * 60))

    return windows


def charged_hours_for_schedule(
    schedule: str,
    duration_hours: float,
    parking_start: datetime | None,
) -> tuple[float, str]:
    if parking_start is None:
        return duration_hours, "Full duration charged; no parking start time was provided."

    windows = parse_schedule_windows(schedule)
    if not windows:
        return duration_hours, "Full duration charged; schedule could not be parsed."

    start_dt = parking_start
    end_dt = parking_start + timedelta(hours=duration_hours)
    total_minutes = 0.0
    day_count = max(1, math.ceil(duration_hours / 24) + 2)

    for day_offset in range(-1, day_count):
        current_day = start_dt.date() + timedelta(days=day_offset)
        weekday = current_day.weekday()

        for days, start_minute, end_minute in windows:
            if weekday not in days:
                continue

            window_start = datetime.combine(current_day, datetime.min.time()) + timedelta(minutes=start_minute)
            window_end = datetime.combine(current_day, datetime.min.time()) + timedelta(minutes=end_minute)
            if end_minute <= start_minute:
                window_end += timedelta(days=1)

            overlap_start = max(start_dt, window_start)
            overlap_end = min(end_dt, window_end)
            if overlap_end > overlap_start:
                total_minutes += (overlap_end - overlap_start).total_seconds() / 60

    billable_hours = round(total_minutes / 60, 2)
    if billable_hours == duration_hours:
        note = "Entire stay is inside paid hours."
    elif billable_hours == 0:
        note = "Stay is outside paid hours."
    else:
        note = f"{billable_hours:.2f}h of {duration_hours:.2f}h falls inside paid hours."

    return billable_hours, note


def nearest_point_on_ring(
    lat: float,
    lon: float,
    ring: tuple[tuple[float, float], ...],
) -> tuple[float, float, float]:
    if not ring:
        return lat, lon, 0

    ref_lat_rad = math.radians(lat)
    meters_per_degree_lat = 111_320
    meters_per_degree_lon = 111_320 * math.cos(ref_lat_rad)

    def to_local(point_lat: float, point_lon: float) -> tuple[float, float]:
        return (
            (point_lon - lon) * meters_per_degree_lon,
            (point_lat - lat) * meters_per_degree_lat,
        )

    def from_local(x: float, y: float) -> tuple[float, float]:
        return (
            lat + y / meters_per_degree_lat,
            lon + x / meters_per_degree_lon,
        )

    best_x = 0.0
    best_y = 0.0
    best_distance_sq = float("inf")

    for index, start in enumerate(ring):
        end = ring[(index + 1) % len(ring)]
        start_x, start_y = to_local(*start)
        end_x, end_y = to_local(*end)
        seg_x = end_x - start_x
        seg_y = end_y - start_y
        seg_len_sq = seg_x * seg_x + seg_y * seg_y

        if seg_len_sq == 0:
            candidate_x, candidate_y = start_x, start_y
        else:
            t = max(0.0, min(1.0, -(start_x * seg_x + start_y * seg_y) / seg_len_sq))
            candidate_x = start_x + t * seg_x
            candidate_y = start_y + t * seg_y

        distance_sq = candidate_x * candidate_x + candidate_y * candidate_y
        if distance_sq < best_distance_sq:
            best_distance_sq = distance_sq
            best_x = candidate_x
            best_y = candidate_y

    nearest_lat, nearest_lon = from_local(best_x, best_y)
    return nearest_lat, nearest_lon, haversine(lat, lon, nearest_lat, nearest_lon)


def nearest_point_on_polygon(
    lat: float,
    lon: float,
    polygon: tuple[tuple[float, float], ...],
    holes: tuple[tuple[tuple[float, float], ...], ...] = (),
) -> tuple[float, float, float]:
    if not polygon:
        return lat, lon, 0

    containing_hole = next((hole for hole in holes if point_in_polygon(lat, lon, hole)), None)
    if point_in_polygon(lat, lon, polygon) and containing_hole is None:
        return lat, lon, 0
    if containing_hole is not None:
        return nearest_point_on_ring(lat, lon, containing_hole)

    return nearest_point_on_ring(lat, lon, polygon)


def coordinates_changed(
    lat1: float | None,
    lon1: float | None,
    lat2: float | None,
    lon2: float | None,
    tolerance: float = 0.00001,
) -> bool:
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return True
    return abs(lat1 - lat2) > tolerance or abs(lon1 - lon2) > tolerance


def get_current_zone(zones: list[ParkingZone], lat: float, lon: float) -> ParkingZone | None:
    for zone in zones:
        if point_in_polygon(lat, lon, zone.coords) and not any(
            point_in_polygon(lat, lon, hole) for hole in zone.holes
        ):
            return zone
    return None


def build_zone_results(
    zones: list[ParkingZone],
    dest_lat: float,
    dest_lon: float,
    radius_m: int,
    selected_colors: set[str],
    duration_hours: float,
    cost_importance: int,
    include_unknown: bool,
    parking_start: datetime | None = None,
) -> tuple[list[ZoneResult], ParkingZone | None]:
    current_zone = get_current_zone(zones, dest_lat, dest_lon)
    current_price = PRICES.get(current_zone.color) if current_zone else None
    current_billable_hours = (
        charged_hours_for_schedule(current_zone.schedule, duration_hours, parking_start)[0]
        if current_zone
        else duration_hours
    )
    current_cost = current_price * current_billable_hours if current_price is not None else None
    current_polygon_id = current_zone.polygon_id if current_zone else None

    results: list[ZoneResult] = []
    for zone in zones:
        if zone.color == "unknown" and not include_unknown:
            continue
        if zone.color != "unknown" and zone.color not in selected_colors:
            continue

        _, _, distance_m = nearest_point_on_polygon(dest_lat, dest_lon, zone.coords, zone.holes)
        if distance_m > radius_m:
            continue

        hourly_price = PRICES.get(zone.color)
        billable_hours, billing_note = charged_hours_for_schedule(zone.schedule, duration_hours, parking_start)
        total_cost = hourly_price * billable_hours if hourly_price is not None else None
        savings = current_cost - total_cost if current_cost is not None and total_cost is not None else None
        warning = ""
        if zone.time_limit_hours is not None and duration_hours > zone.time_limit_hours:
            warning = f"Exceeds {zone.time_limit_hours:g}h limit"

        results.append(
            ZoneResult(
                zone=zone,
                distance_m=distance_m,
                hourly_price=hourly_price,
                total_cost=total_cost,
                savings=savings,
                score=None,
                billable_hours=billable_hours,
                billing_note=billing_note,
                walking_time_min=walking_time_from_distance(distance_m),
                warning=warning,
                is_current=zone.polygon_id == current_polygon_id,
            )
        )

    assign_scores_and_flags(results, cost_importance)
    return sort_results(results), current_zone


def assign_scores_and_flags(results: list[ZoneResult], cost_importance: int) -> None:
    if results:
        closest = min(results, key=lambda result: result.distance_m)
        closest.is_closest = True

    priced_results = [result for result in results if result.total_cost is not None]
    if not priced_results:
        return

    max_cost = max(result.total_cost or 0 for result in priced_results) or 1
    max_distance = max(result.distance_m for result in results) or 1
    cost_weight = cost_importance / 100
    distance_weight = 1 - cost_weight

    for result in priced_results:
        cost_component = (result.total_cost or 0) / max_cost
        distance_component = result.distance_m / max_distance
        result.score = cost_weight * cost_component + distance_weight * distance_component

    cheapest = min(
        priced_results,
        key=lambda result: (
            result.total_cost if result.total_cost is not None else float("inf"),
            result.distance_m,
        ),
    )
    cheapest.is_cheapest = True

    optimal = min(priced_results, key=lambda result: result.score if result.score is not None else float("inf"))
    optimal.is_optimal = True


def sort_results(results: list[ZoneResult]) -> list[ZoneResult]:
    return sorted(
        results,
        key=lambda result: (
            result.score is None,
            result.score if result.score is not None else float("inf"),
            result.total_cost if result.total_cost is not None else float("inf"),
            result.distance_m,
        ),
    )


def route_candidates(results: list[ZoneResult], limit: int = 2) -> list[ZoneResult]:
    candidates: list[ZoneResult] = []

    for predicate in (
        lambda result: result.is_optimal,
        lambda result: result.is_cheapest,
        lambda result: result.is_closest,
        lambda result: result.score is not None,
    ):
        for result in results:
            if predicate(result) and result not in candidates:
                candidates.append(result)
            if len(candidates) >= limit:
                return candidates

    return candidates


def apply_route_to_result(result: ZoneResult, distance_m: float, duration_min: float, is_fallback: bool) -> None:
    result.route_distance_m = distance_m
    result.walking_time_min = duration_min
    result.route_is_fallback = is_fallback
    

    
    
def get_zone_marker_position(zone: ParkingZone) -> tuple[float, float]:
    """Return a point guaranteed to be inside the zone polygon (and not inside any hole)."""
    # 1. Try the precomputed centroid (area-weighted with holes)
    if point_in_polygon(zone.centroid_lat, zone.centroid_lon, zone.coords) and not any(
        point_in_polygon(zone.centroid_lat, zone.centroid_lon, hole) for hole in zone.holes
    ):
        return zone.centroid_lat, zone.centroid_lon

    # 2. Fallback to outer ring centroid (simple average of vertices)
    outer = zone.coords
    avg_lat = sum(c[0] for c in outer) / len(outer)
    avg_lon = sum(c[1] for c in outer) / len(outer)
    if point_in_polygon(avg_lat, avg_lon, outer) and not any(
        point_in_polygon(avg_lat, avg_lon, hole) for hole in zone.holes
    ):
        return avg_lat, avg_lon

    # 3. Try midpoints of outer edges (most robust fallback)
    for i in range(len(outer)):
        p1 = outer[i]
        p2 = outer[(i + 1) % len(outer)]
        mid_lat = (p1[0] + p2[0]) / 2
        mid_lon = (p1[1] + p2[1]) / 2
        if point_in_polygon(mid_lat, mid_lon, outer) and not any(
            point_in_polygon(mid_lat, mid_lon, hole) for hole in zone.holes
        ):
            return mid_lat, mid_lon

    # Ultimate fallback (should not happen for valid polygons)
    return zone.centroid_lat, zone.centroid_lon
