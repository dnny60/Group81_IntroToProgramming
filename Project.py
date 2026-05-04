from datetime import date, datetime, time
from pathlib import Path

import streamlit as st
from streamlit_folium import st_folium
from streamlit_geolocation import streamlit_geolocation

from boundary_data import LisbonBoundary, is_point_in_lisbon, load_lisbon_boundary
from geo_services import fetch_walking_route, geocode_address, reverse_geocode_street
from map_view import build_map
from parking_data import COLOR_FILTERS, COLOR_HEX, COLOR_LABELS, PRICES, load_parking_zones
from parking_logic import (
    apply_route_to_result,
    build_zone_results,
    coordinates_changed,
    nearest_point_on_polygon,
)


DEFAULT_LAT = 38.749386
DEFAULT_LON = -9.157919
BASE_DIR = Path(__file__).resolve().parent
PARKING_ZONES_PATH = BASE_DIR / "listzones.xml"
LISBON_BOUNDARY_PATH = BASE_DIR / "lisbon_boundary.geojson"
GEOMETRY_CACHE_VERSION = 3
BOUNDARY_CACHE_VERSION = 2
MAP_RENDER_VERSION = 5
UNSUPPORTED_AREA_MESSAGE = "This area is not supported. Please choose a destination in Lisbon."


def initialize_state() -> None:
    defaults = {
        "destination_lat": DEFAULT_LAT,
        "destination_lon": DEFAULT_LON,
        "destination_label": "Default position in Lisbon",
        "destination_source": None,
        "selected_polygon_id": None,
        "selected_recommendation_polygon_id": None,
        "address_query": "",
        "duration_hours": 2.0,
        "radius_m": 500,
        "include_unknown": False,
        "cost_importance": 50,
        "parking_date": date.today(),
        "parking_start_time": time(9, 0),
        "map_key_nonce": 0,
        "recommendation_signature": None,
        "area_warning": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    for color in COLOR_FILTERS:
        key = f"filter_{color}"
        if key not in st.session_state:
            st.session_state[key] = True

    st.session_state.radius_m = min(1000, max(100, int(st.session_state.radius_m)))
    st.session_state.duration_hours = min(24.0, max(0.25, float(st.session_state.duration_hours)))
    st.session_state.cost_importance = min(100, max(0, int(st.session_state.cost_importance)))


def set_destination(lat: float, lon: float, label: str, source: str) -> None:
    st.session_state.destination_lat = lat
    st.session_state.destination_lon = lon
    st.session_state.destination_label = label
    st.session_state.destination_source = source
    st.session_state.selected_polygon_id = None
    st.session_state.selected_recommendation_polygon_id = None
    st.session_state.area_warning = None
    st.session_state.map_key_nonce += 1


def reset_destination() -> None:
    st.session_state.destination_lat = DEFAULT_LAT
    st.session_state.destination_lon = DEFAULT_LON
    st.session_state.destination_label = "Default position in Lisbon"
    st.session_state.destination_source = None
    st.session_state.selected_polygon_id = None
    st.session_state.selected_recommendation_polygon_id = None
    st.session_state.area_warning = None
    st.session_state.map_key_nonce += 1


def reset_filters() -> None:
    st.session_state.duration_hours = 2.0
    st.session_state.radius_m = 500
    st.session_state.include_unknown = False
    st.session_state.cost_importance = 50
    st.session_state.parking_date = date.today()
    st.session_state.parking_start_time = time(9, 0)
    st.session_state.selected_polygon_id = None
    st.session_state.selected_recommendation_polygon_id = None

    for color in COLOR_FILTERS:
        st.session_state[f"filter_{color}"] = True


def destination_is_supported(
    lisbon_boundary: LisbonBoundary | None,
    lat: float,
    lon: float,
) -> bool:
    return is_point_in_lisbon(lisbon_boundary, lat, lon)


def warn_unsupported_area() -> None:
    st.session_state.area_warning = UNSUPPORTED_AREA_MESSAGE


def format_money(value: float | None) -> str:
    return "N/A" if value is None else f"EUR {value:.2f}"


def table_rows(
    results,
    selected_polygon_id: int | None,
    street_by_polygon_id: dict[int, str] | None = None,
) -> list[dict[str, object]]:
    street_by_polygon_id = street_by_polygon_id or {}
    rows = []
    for result in results:
        labels = []
        if result.is_cheapest:
            labels.append("Cheapest")
        if result.is_optimal:
            labels.append("Optimal")
        if result.is_closest:
            labels.append("Closest")
        if result.is_current:
            labels.append("Current")

        rows.append(
            {
                "Polygon ID": result.zone.polygon_id,
                "Selected": "✓" if selected_polygon_id == result.zone.polygon_id else "",
                "Status": ", ".join(labels),
                "Zone ID": result.zone.zone_id,
                "Suggested street": street_by_polygon_id.get(result.zone.polygon_id, "N/A"),
                "Color": COLOR_LABELS.get(result.zone.color, "Unknown"),
                "Price/hour": format_money(result.hourly_price),
                "Distance": f"{result.distance_m:.0f} m",
                "Walking Time": f"{result.walking_time_min:.0f} min",
                "Charged Hours": f"{result.billable_hours:.2f} h",
                "Duration Cost": format_money(result.total_cost),
                "Score": "N/A" if result.score is None else f"{result.score:.3f}",
            }
        )
    return rows


def recommendation_results(results) -> list:
    picks = []

    for predicate in (
        lambda result: result.is_cheapest,
        lambda result: result.is_optimal,
        lambda result: result.is_closest,
    ):
        result = next((item for item in results if predicate(item)), None)
        if result is not None and result not in picks:
            picks.append(result)

    return picks


def primary_recommendation(results):
    return next((result for result in results if result.is_optimal), None) or (
        results[0] if results else None
    )


def ensure_recommendation_selection(results) -> None:
    recommendation = primary_recommendation(results)
    if recommendation is None:
        st.session_state.selected_recommendation_polygon_id = None
        return

    recommendation_ids = {result.zone.polygon_id for result in results}
    if st.session_state.selected_recommendation_polygon_id not in recommendation_ids:
        st.session_state.selected_recommendation_polygon_id = recommendation.zone.polygon_id


def recommendation_signature(
    controls: dict[str, object],
    destination_lat: float,
    destination_lon: float,
) -> tuple[object, ...]:
    return (
        round(destination_lat, 6),
        round(destination_lon, 6),
        controls["parking_start"].isoformat(),
        controls["duration_hours"],
        controls["radius_m"],
        tuple(sorted(controls["selected_colors"])),
        controls["include_unknown"],
        controls["cost_importance"],
    )


def reset_recommendation_on_input_change(
    controls: dict[str, object],
    destination_lat: float,
    destination_lon: float,
    results,
) -> None:
    signature = recommendation_signature(controls, destination_lat, destination_lon)
    if st.session_state.recommendation_signature == signature:
        ensure_recommendation_selection(results)
        return

    st.session_state.recommendation_signature = signature
    recommendation = primary_recommendation(results)
    st.session_state.selected_recommendation_polygon_id = (
        recommendation.zone.polygon_id if recommendation else None
    )
    st.session_state.selected_polygon_id = None


def selected_result(results, selected_polygon_id: int | None):
    if selected_polygon_id is None:
        return None
    return next((result for result in results if result.zone.polygon_id == selected_polygon_id), None)


def render_detail_panel(result, show_close: bool = True) -> None:
    st.subheader("Zone details")
    if result is None:
        st.info("Select a row in the results table or click a zone on the map.")
        return

    zone = result.zone
    if show_close and st.button("Close details", use_container_width=True):
        st.session_state.selected_polygon_id = None
        st.rerun()

    st.write(f"Price/hour: {format_money(result.hourly_price)}")
    st.write(f"Duration cost: {format_money(result.total_cost)}")

    with st.expander("Parking rules", expanded=True):
        st.write(f"Schedule: {zone.schedule}")
        st.write(f"Parking type: {zone.additional_info}")


def render_sidebar_legend() -> None:
    color_rows = "".join(
        f"""
        <div style="display:flex;align-items:center;gap:8px;margin:4px 0;">
            <span style="width:14px;height:14px;background:{COLOR_HEX[color]};border:1px solid #555;display:inline-block;"></span>
            <span>{COLOR_LABELS[color]}: {format_money(PRICES[color])}/h</span>
        </div>
        """
        for color in COLOR_FILTERS
    )

    st.sidebar.divider()
    st.sidebar.subheader("Map legend")
    st.sidebar.markdown(color_rows, unsafe_allow_html=True)
    st.sidebar.caption("Border color = parking-zone tariff color.")
    st.sidebar.caption("Thick border = current recommended zone.")
    st.sidebar.caption("Blue solid line = walking route; blue dashed line = straight-line estimate.")
    st.sidebar.caption("Blue flag = destination.")
    st.sidebar.caption("Dark grey area = outside the supported Lisbon boundary.")


def render_sidebar(lisbon_boundary: LisbonBoundary | None) -> dict[str, object]:
    st.sidebar.header("Parking search")

    with st.sidebar.form("address_search"):
        address = st.text_input(
            "Search destination",
            value=st.session_state.address_query,
            placeholder="Praca do Comercio, Lisbon",
        )
        search_clicked = st.form_submit_button("Search address", use_container_width=True)

    if search_clicked:
        st.session_state.address_query = address
        try:
            with st.spinner("Searching address..."):
                result = geocode_address(address)
            if destination_is_supported(lisbon_boundary, result.lat, result.lon):
                set_destination(result.lat, result.lon, result.label, "address")
                st.sidebar.success("Destination updated.")
            else:
                warn_unsupported_area()
                st.sidebar.warning(UNSUPPORTED_AREA_MESSAGE)
        except Exception as exc:
            st.sidebar.error(str(exc))

    if st.sidebar.button("Clear destination", use_container_width=True):
        reset_destination()
        st.rerun()

    st.sidebar.divider()
    st.sidebar.subheader("GPS")
    with st.sidebar:
        loc = streamlit_geolocation()
    if loc and loc.get("latitude") is not None and loc.get("longitude") is not None:
        gps_lat = float(loc["latitude"])
        gps_lon = float(loc["longitude"])
        if st.session_state.destination_source in (None, "gps") and coordinates_changed(
            gps_lat,
            gps_lon,
            st.session_state.destination_lat,
            st.session_state.destination_lon,
        ):
            if destination_is_supported(lisbon_boundary, gps_lat, gps_lon):
                set_destination(gps_lat, gps_lon, "Current GPS location", "gps")
            else:
                warn_unsupported_area()
        if st.sidebar.button("Use latest GPS location", use_container_width=True):
            if destination_is_supported(lisbon_boundary, gps_lat, gps_lon):
                set_destination(gps_lat, gps_lon, "Current GPS location", "gps")
                st.rerun()
            else:
                warn_unsupported_area()
                st.sidebar.warning(UNSUPPORTED_AREA_MESSAGE)

    st.sidebar.divider()
    if st.sidebar.button("Reset filters", use_container_width=True):
        reset_filters()
        st.rerun()

    st.sidebar.subheader("Parking time")
    if st.sidebar.button("Now", use_container_width=False):
        now = datetime.now()
        st.session_state.parking_date = now.date()
        st.session_state.parking_start_time = time(now.hour, now.minute)

    parking_date = st.sidebar.date_input("Parking date", key="parking_date")
    parking_start_time = st.sidebar.time_input("Parking start time", key="parking_start_time")

    duration_hours = st.sidebar.number_input(
        "Parking duration (hours)",
        min_value=0.25,
        max_value=24.0,
        step=0.25,
        key="duration_hours",
    )
    radius_m = st.sidebar.slider("Search radius (meters)", 100, 1000, 500, 100, key="radius_m")

    st.sidebar.subheader("Zone filters")
    selected_colors = {
        color
        for color in COLOR_FILTERS
        if st.sidebar.checkbox(COLOR_LABELS[color], key=f"filter_{color}")
    }
    include_unknown = st.sidebar.checkbox("Unknown price", key="include_unknown")

    with st.sidebar.expander("Optimal balance", expanded=False):
        cost_importance = st.slider("Cost importance", 0, 100, step=5, key="cost_importance")
        st.caption(f"Distance importance: {100 - cost_importance}%")
        st.caption("Score = (cost/top_cost) × cost% + (distance/max_distance) × distance%")

    render_sidebar_legend()

    return {
        "duration_hours": float(duration_hours),
        "radius_m": int(radius_m),
        "selected_colors": selected_colors,
        "include_unknown": include_unknown,
        "cost_importance": int(cost_importance),
        "parking_start": datetime.combine(parking_date, parking_start_time),
    }


@st.cache_data(show_spinner=False)
def get_zones(cache_version: int):
    return load_parking_zones(PARKING_ZONES_PATH)


@st.cache_data(show_spinner=False)
def get_lisbon_boundary(cache_version: int):
    try:
        return load_lisbon_boundary(LISBON_BOUNDARY_PATH), None
    except Exception as exc:
        return None, str(exc)


def main() -> None:
    st.set_page_config(page_title="🚗Best Street Parking", layout="wide")
    initialize_state()
    zones = get_zones(GEOMETRY_CACHE_VERSION)
    lisbon_boundary, boundary_error = get_lisbon_boundary(BOUNDARY_CACHE_VERSION)
    if boundary_error:
        st.sidebar.error(f"Lisbon boundary restriction disabled: {boundary_error}")
    controls = render_sidebar(lisbon_boundary)

    st.title("🚗BestParking")
    st.caption("Smart Lisbon street parking-zone advisor")

    location_ready = st.session_state.destination_source is not None
    destination_lat = st.session_state.destination_lat
    destination_lon = st.session_state.destination_lon

    if location_ready:
        st.success(
            f"Destination: {st.session_state.destination_label} "
            f"({st.session_state.destination_source})"
        )
    else:
        st.warning(
            "No destination selected yet. Showing the default Lisbon position. "
            "Search an address, use GPS, or click the map."
        )

    if st.session_state.area_warning:
        st.warning(st.session_state.area_warning)

    results, _current_zone = build_zone_results(
        zones=zones,
        dest_lat=destination_lat,
        dest_lon=destination_lon,
        radius_m=controls["radius_m"],
        selected_colors=controls["selected_colors"],
        duration_hours=controls["duration_hours"],
        cost_importance=controls["cost_importance"],
        include_unknown=controls["include_unknown"],
        parking_start=controls["parking_start"],
    )

    comparison_results = recommendation_results(results)
    reset_recommendation_on_input_change(
        controls,
        destination_lat,
        destination_lon,
        comparison_results,
    )
    selected_recommendation = selected_result(
        comparison_results,
        st.session_state.selected_recommendation_polygon_id,
    )
    selected = selected_result(results, st.session_state.selected_polygon_id)
    selected_street = None
    street_results_by_polygon_id = {}
    street_by_polygon_id = {}

    if location_ready:
        for result in comparison_results:
            street_lat, street_lon, _ = nearest_point_on_polygon(
                destination_lat,
                destination_lon,
                result.zone.coords,
                result.zone.holes,
            )
            try:
                street_result = reverse_geocode_street(street_lat, street_lon)
                street_results_by_polygon_id[result.zone.polygon_id] = street_result
                street_by_polygon_id[result.zone.polygon_id] = street_result.street
            except Exception:
                street_by_polygon_id[result.zone.polygon_id] = "Street unavailable"

    routes = {}
    if location_ready and selected_recommendation:
        route_lat, route_lon, _ = nearest_point_on_polygon(
            destination_lat,
            destination_lon,
            selected_recommendation.zone.coords,
            selected_recommendation.zone.holes,
        )
        route = fetch_walking_route(
            destination_lat,
            destination_lon,
            route_lat,
            route_lon,
        )
        routes[selected_recommendation.zone.polygon_id] = route
        apply_route_to_result(
            selected_recommendation,
            route.distance_m,
            route.duration_min,
            route.is_fallback,
        )
        selected_street = street_results_by_polygon_id.get(selected_recommendation.zone.polygon_id)

    summary_result = selected_recommendation or primary_recommendation(comparison_results)

    summary_cols = st.columns(4)
    summary_cols[0].metric("Radius", f"{controls['radius_m']} m")
    summary_cols[1].metric("Duration", f"{controls['duration_hours']:.2f}h")
    summary_cols[2].metric(
        "Total cost",
        format_money(summary_result.total_cost if summary_result else None),
    )
    if summary_result:
        summary_cols[3].metric(
            "Distance to destination + Walking time",
            f"{summary_result.distance_m:.0f} m / {summary_result.walking_time_min:.0f} min",
        )
    else:
        summary_cols[3].metric("Distance to destination + Walking time", "N/A")

    if summary_result:
        st.caption(
            f"Pricing uses start time {controls['parking_start']:%Y-%m-%d %H:%M}; "
            f"charged hours for the selected zone: {summary_result.billable_hours:.2f}h "
            f"based on schedule `{summary_result.zone.schedule}`."
        )

    if location_ready and selected_recommendation:
        street_text = selected_street.street if selected_street else "Street unavailable"
        st.info(
            f"Suggested parking street: **{street_text}** "
            f"(zone {selected_recommendation.zone.zone_id})"
        )

    map_col, detail_col = st.columns([2, 1])
    with map_col:
        map_results = [selected_recommendation] if selected_recommendation else []
        parking_map = build_map(
            results=map_results,
            destination_lat=destination_lat,
            destination_lon=destination_lon,
            radius_m=controls["radius_m"],
            selected_polygon_id=st.session_state.selected_polygon_id,
            routes=routes,
            location_ready=location_ready,
            lisbon_boundary=lisbon_boundary,
        )
        map_data = st_folium(
            parking_map,
            key=f"parking_map_{MAP_RENDER_VERSION}_{st.session_state.map_key_nonce}",
            height=620,
            use_container_width=True,
            returned_objects=["last_clicked"],
        )

    with detail_col:
        detail_result = selected or selected_recommendation
        render_detail_panel(detail_result, show_close=selected is not None)

    if map_data and map_data.get("last_clicked"):
        new_lat = map_data["last_clicked"]["lat"]
        new_lon = map_data["last_clicked"]["lng"]
        if coordinates_changed(new_lat, new_lon, destination_lat, destination_lon):
            if destination_is_supported(lisbon_boundary, new_lat, new_lon):
                set_destination(new_lat, new_lon, "Map click destination", "click")
            else:
                warn_unsupported_area()
                st.session_state.map_key_nonce += 1
            st.rerun()

    st.subheader("Comparison table")
    rows = table_rows(
        comparison_results,
        st.session_state.selected_recommendation_polygon_id,
        street_by_polygon_id,
    )
    if not rows:
        st.info("No parking zones match the current filters and radius.")
        return

    table_key = (
        "results_table_"
        f"{controls['parking_start'].strftime('%Y%m%d%H%M')}_"
        f"{controls['duration_hours']}_"
        f"{controls['radius_m']}_"
        f"{controls['cost_importance']}_"
        + "_".join(str(row["Polygon ID"]) for row in rows)
    )
    table_state = st.dataframe(
        rows,
        hide_index=True,
        use_container_width=True,
        column_order=[
            "Selected",
            "Status",
            "Zone ID",
            "Suggested street",
            "Color",
            "Price/hour",
            "Distance",
            "Walking Time",
            "Charged Hours",
            "Duration Cost",
            "Score",
        ],
        on_select="rerun",
        selection_mode="single-row",
        key=table_key,
    )
    if table_state.selection.rows:
        row_index = table_state.selection.rows[0]
        if row_index >= len(rows):
            return

        selected_polygon_id = rows[row_index]["Polygon ID"]
        if selected_polygon_id != st.session_state.selected_recommendation_polygon_id:
            st.session_state.selected_recommendation_polygon_id = selected_polygon_id
            st.session_state.selected_polygon_id = selected_polygon_id
            st.rerun()


if __name__ == "__main__":
    main()
