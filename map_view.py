from __future__ import annotations

import html

import folium

from parking_data import COLOR_HEX, COLOR_LABELS
from parking_logic import ZoneResult, get_zone_marker_position
from geo_services import RouteResult


ZONE_FILL_OPACITY = 0.35


def format_money(value: float | None) -> str:
    return "N/A" if value is None else f"EUR {value:.2f}"


def zone_popup_html(result: ZoneResult) -> str:
    zone = result.zone
    route_note = "straight-line estimate" if result.route_is_fallback else "walking route"
    details = {
        "Zone ID": zone.zone_id,
        "Polygon": zone.polygon_id,
        "Color": COLOR_LABELS.get(zone.color, "Unknown"),
        "Price/hour": format_money(result.hourly_price),
        "Duration cost": format_money(result.total_cost),
        "Distance": f"{result.distance_m:.0f} m",
        "Walking time": f"{result.walking_time_min:.0f} min ({route_note})",
        "Score": "N/A" if result.score is None else f"{result.score:.3f}",
        "Product": zone.product,
        "Schedule": zone.schedule,
        "Parking type": zone.additional_info,
        "Boundary points": str(zone.point_count),
    }

    rows = "".join(
        f"<tr><th style='text-align:left;padding:3px 8px 3px 0;'>{html.escape(label)}</th>"
        f"<td style='padding:3px 0;'>{html.escape(str(value))}</td></tr>"
        for label, value in details.items()
    )
    return f"<strong>Parking Zone Details</strong><table>{rows}</table>"


def zone_tooltip(result: ZoneResult) -> str:
    price = format_money(result.hourly_price)
    return (
        f"<span style='display:none'>Polygon {result.zone.polygon_id}</span>"
        f"Zone {result.zone.zone_id} | {price}/h"
    )


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


def build_map(
    results: list[ZoneResult],
    destination_lat: float,
    destination_lon: float,
    radius_m: int,
    selected_polygon_id: int | None,
    routes: dict[int, RouteResult],
    location_ready: bool,
) -> folium.Map:
    parking_map = folium.Map(
        location=[destination_lat, destination_lon],
        zoom_start=15,
        control_scale=True,
        prefer_canvas=True,
    )

    if location_ready:
        folium.map.CustomPane("radiusPane", z_index=350, pointer_events=False).add_to(parking_map)
        folium.Circle(
            location=[destination_lat, destination_lon],
            radius=radius_m,
            color="#3388ff",
            weight=2,
            dash_array="5, 10",
            fill=True,
            fill_opacity=0.04,
            interactive=False,
            bubbling_mouse_events=False,
            pane="radiusPane",
        ).add_to(parking_map)

    for result in results:
        style = zone_style(result, selected_polygon_id)
        fill_color = COLOR_HEX.get(result.zone.color, COLOR_HEX["unknown"])
        locations = [list(result.zone.coords)]
        locations.extend(list(hole) for hole in result.zone.holes)
        folium.Polygon(
            locations=locations if result.zone.holes else result.zone.coords,
            color=style["color"],
            weight=style["weight"],
            fill=True,
            fill_color=fill_color,
            fill_opacity=style["fill_opacity"],
            tooltip=zone_tooltip(result),
            popup=folium.Popup(zone_popup_html(result), max_width=460),
        ).add_to(parking_map)

    for polygon_id, route in routes.items():
        folium.PolyLine(
            locations=route.coords,
            color="#2980b9",
            weight=5,
            opacity=0.85,
            dash_array="8, 8" if route.is_fallback else None,
            tooltip="Walking route" if not route.is_fallback else "Straight-line fallback",
        ).add_to(parking_map)

        result = next((item for item in results if item.zone.polygon_id == polygon_id), None)
        if result:
            marker_lat, marker_lon = get_zone_marker_position(result.zone)
            folium.Marker(
                [marker_lat, marker_lon],
                popup=f"Recommended zone {result.zone.zone_id}",
                icon=parking_icon(),
            ).add_to(parking_map) 
  
    if location_ready:
        folium.Marker(
            [destination_lat, destination_lon],
            popup="Destination",
            icon=folium.Icon(color="blue", icon="flag", prefix="fa"),
        ).add_to(parking_map)

    return parking_map
