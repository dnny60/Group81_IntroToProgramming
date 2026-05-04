from __future__ import annotations

import html

import folium

from boundary_data import LisbonBoundary
from parking_data import COLOR_HEX
from parking_logic import ZoneResult, get_zone_marker_position
from geo_services import RouteResult


ZONE_FILL_OPACITY = 0.35
WEB_MERCATOR_WORLD_BOUNDS = (-85.05112878, -180.0, 85.05112878, 180.0)


def disable_path_interaction(layer):
    layer.options["interactive"] = False
    layer.options["bubblingMouseEvents"] = False
    return layer


def zone_style(result: ZoneResult, selected_polygon_id: int | None) -> dict[str, object]:
    color = COLOR_HEX.get(result.zone.color, COLOR_HEX["unknown"])

    return {
        "color": color,
        "weight": 4 if result.is_cheapest or result.is_optimal or selected_polygon_id == result.zone.polygon_id else 1,
        "fill_opacity": ZONE_FILL_OPACITY,
    }


def parking_icon(color: str = "#f39c12") -> folium.DivIcon:
    return folium.DivIcon(
        html=f"""
        <div style="
            width: 30px;
            height: 30px;
            border-radius: 50% 50% 50% 0;
            background: {html.escape(color)};
            transform: rotate(-45deg);
            border: 3px solid white;
            box-shadow: 0 2px 8px rgba(0,0,0,0.35);
            display: flex;
            align-items: center;
            justify-content: center;
        ">
            <span style="
                transform: rotate(45deg);
                color: white;
                font-size: 18px;
                line-height: 1;
                font-weight: 800;
                font-family: Arial, sans-serif;
            ">P</span>
        </div>
        """,
        icon_size=(30, 30),
        icon_anchor=(15, 30),
    )


def rectangle_ring(bounds: tuple[float, float, float, float]) -> list[tuple[float, float]]:
    south, west, north, east = bounds
    return [
        (south, west),
        (south, east),
        (north, east),
        (north, west),
        (south, west),
    ]


def boundary_mask_locations(boundary: LisbonBoundary) -> list[list[tuple[float, float]]]:
    locations = [rectangle_ring(WEB_MERCATOR_WORLD_BOUNDS)]
    for polygon in boundary.polygons:
        locations.append(list(polygon.outer))
        locations.extend(list(hole) for hole in polygon.holes)
    return locations


def add_unsupported_area_mask(parking_map: folium.Map, boundary: LisbonBoundary) -> None:
    mask = folium.Polygon(
        locations=boundary_mask_locations(boundary),
        color="#2f3437",
        weight=0,
        fill=True,
        fill_color="#2f3437",
        fill_opacity=0.55,
        fill_rule="evenodd",
        tooltip="Area not supported",
        class_name="unsupported-area-mask",
    )
    mask.options["interactive"] = True
    mask.options["bubblingMouseEvents"] = True
    mask.add_to(parking_map)


def build_map(
    results: list[ZoneResult],
    destination_lat: float,
    destination_lon: float,
    radius_m: int,
    selected_polygon_id: int | None,
    routes: dict[int, RouteResult],
    location_ready: bool,
    lisbon_boundary: LisbonBoundary | None = None,
) -> folium.Map:
    bounds_kwargs = {}
    if lisbon_boundary is not None:
        south, west, north, east = lisbon_boundary.padded_bounds
        bounds_kwargs = {
            "min_lat": south,
            "max_lat": north,
            "min_lon": west,
            "max_lon": east,
            "max_bounds": True,
        }

    parking_map = folium.Map(
        location=[destination_lat, destination_lon],
        zoom_start=15,
        control_scale=True,
        prefer_canvas=False,
        **bounds_kwargs,
    )

    if lisbon_boundary is not None:
        add_unsupported_area_mask(parking_map, lisbon_boundary)

    if location_ready:
        radius_circle = folium.Circle(
            location=[destination_lat, destination_lon],
            radius=radius_m,
            color="#3388ff",
            weight=2,
            dash_array="5, 10",
            fill=False,
            fill_opacity=0,
            class_name="bestparking-radius",
        )
        disable_path_interaction(radius_circle).add_to(parking_map)
        parking_map.get_root().html.add_child(
            folium.Element(
                """
                <style>
                    .bestparking-radius {
                        pointer-events: none !important;
                        stroke: #3388ff;
                        cursor: grab !important;
                    }
                    .bestparking-radius svg,
                    svg .bestparking-radius {
                        pointer-events: none !important;
                    }
                </style>
                """
            )
        )

    for result in results:
        style = zone_style(result, selected_polygon_id)
        fill_color = COLOR_HEX.get(result.zone.color, COLOR_HEX["unknown"])
        locations = [list(result.zone.coords)]
        locations.extend(list(hole) for hole in result.zone.holes)
        zone_polygon = folium.Polygon(
            locations=locations if result.zone.holes else result.zone.coords,
            color=style["color"],
            weight=style["weight"],
            fill=True,
            fill_color=fill_color,
            fill_opacity=style["fill_opacity"],
            class_name="bestparking-zone",
        )
        disable_path_interaction(zone_polygon).add_to(parking_map)

    for polygon_id, route in routes.items():
        route_line = folium.PolyLine(
            locations=route.coords,
            color="#2980b9",
            weight=5,
            opacity=0.85,
            dash_array="8, 8" if route.is_fallback else None,
            class_name="bestparking-route",
        )
        disable_path_interaction(route_line).add_to(parking_map)

        result = next((item for item in results if item.zone.polygon_id == polygon_id), None)
        if result:
            marker_lat, marker_lon = get_zone_marker_position(result.zone)
            folium.Marker(
                [marker_lat, marker_lon],
                icon=parking_icon(),
                interactive=False,
                bubbling_mouse_events=False,
            ).add_to(parking_map) 
  
    if location_ready:
        folium.Marker(
            [destination_lat, destination_lon],
            icon=folium.Icon(color="blue", icon="flag", prefix="fa"),
            interactive=False,
            bubbling_mouse_events=False,
        ).add_to(parking_map)

    return parking_map
