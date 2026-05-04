from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


Coordinate = tuple[float, float]
Ring = tuple[Coordinate, ...]


@dataclass(frozen=True)
class BoundaryPolygon:
    outer: Ring
    holes: tuple[Ring, ...]


@dataclass(frozen=True)
class LisbonBoundary:
    polygons: tuple[BoundaryPolygon, ...]
    bounds: tuple[float, float, float, float]
    padded_bounds: tuple[float, float, float, float]


def point_in_ring(lat: float, lon: float, ring: Ring) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > lon) != (yj > lon)) and (lat < (xj - xi) * (lon - yi) / (yj - yi + 1e-9) + xi):
            inside = not inside
        j = i
    return inside


def is_point_in_lisbon(boundary: LisbonBoundary | None, lat: float, lon: float) -> bool:
    if boundary is None:
        return True

    for polygon in boundary.polygons:
        if point_in_ring(lat, lon, polygon.outer) and not any(
            point_in_ring(lat, lon, hole) for hole in polygon.holes
        ):
            return True
    return False


def clean_ring(ring: list[Coordinate]) -> Ring:
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring = ring[:-1]
    return tuple(ring)


def parse_geojson_ring(raw_ring: list[list[float]]) -> Ring:
    ring: list[Coordinate] = []
    for raw_coord in raw_ring:
        if len(raw_coord) < 2:
            continue
        lon, lat = raw_coord[:2]
        ring.append((float(lat), float(lon)))

    cleaned = clean_ring(ring)
    if len(cleaned) < 3:
        raise ValueError("Boundary ring has fewer than three points.")
    return cleaned


def parse_polygon_coordinates(raw_polygon: list[list[list[float]]]) -> BoundaryPolygon:
    if not raw_polygon:
        raise ValueError("Boundary polygon has no rings.")

    outer = parse_geojson_ring(raw_polygon[0])
    holes = tuple(parse_geojson_ring(raw_ring) for raw_ring in raw_polygon[1:])
    return BoundaryPolygon(outer=outer, holes=holes)


def geometry_polygons(geometry: dict[str, Any]) -> list[BoundaryPolygon]:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if not coordinates:
        return []

    if geometry_type == "Polygon":
        return [parse_polygon_coordinates(coordinates)]
    if geometry_type == "MultiPolygon":
        return [parse_polygon_coordinates(raw_polygon) for raw_polygon in coordinates]
    return []


def feature_geometries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    payload_type = payload.get("type")
    if payload_type == "FeatureCollection":
        return [
            feature.get("geometry")
            for feature in payload.get("features", [])
            if isinstance(feature.get("geometry"), dict)
        ]
    if payload_type == "Feature":
        geometry = payload.get("geometry")
        return [geometry] if isinstance(geometry, dict) else []
    if payload_type in {"Polygon", "MultiPolygon"}:
        return [payload]
    return []


def compute_bounds(polygons: tuple[BoundaryPolygon, ...]) -> tuple[float, float, float, float]:
    coords = [
        coord
        for polygon in polygons
        for ring in (polygon.outer, *polygon.holes)
        for coord in ring
    ]
    if not coords:
        raise ValueError("Boundary file contains no coordinates.")

    south = min(lat for lat, _lon in coords)
    west = min(lon for _lat, lon in coords)
    north = max(lat for lat, _lon in coords)
    east = max(lon for _lat, lon in coords)
    return south, west, north, east


def pad_bounds(
    bounds: tuple[float, float, float, float],
    padding_degrees: float = 0.025,
) -> tuple[float, float, float, float]:
    south, west, north, east = bounds
    return (
        south - padding_degrees,
        west - padding_degrees,
        north + padding_degrees,
        east + padding_degrees,
    )


def load_lisbon_boundary(path: str | Path = "lisbon_boundary.geojson") -> LisbonBoundary:
    boundary_path = Path(path)
    if not boundary_path.exists():
        raise FileNotFoundError(
            "lisbon_boundary.geojson not found. Export the Lisbon admin_level=7 boundary from Overpass Turbo."
        )

    with boundary_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    polygons: list[BoundaryPolygon] = []
    for geometry in feature_geometries(payload):
        polygons.extend(geometry_polygons(geometry))

    if not polygons:
        raise ValueError("lisbon_boundary.geojson must contain a Polygon or MultiPolygon geometry.")

    boundary_polygons = tuple(polygons)
    bounds = compute_bounds(boundary_polygons)
    return LisbonBoundary(
        polygons=boundary_polygons,
        bounds=bounds,
        padded_bounds=pad_bounds(bounds),
    )
