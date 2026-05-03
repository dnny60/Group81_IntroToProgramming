from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from parking_logic import haversine, walking_time_from_distance


USER_AGENT = "bestparking-course-project"
OSRM_URLS = (
    # This public OSRM service is configured with a pedestrian profile.
    # Its URL keeps OSRM's usual "driving" segment even for the routed-foot backend.
    "https://routing.openstreetmap.de/routed-foot/route/v1/driving",
    "http://router.project-osrm.org/route/v1/foot",
)
MAX_ROUTE_DETOUR_RATIO = 4
MAX_ROUTE_DETOUR_EXTRA_M = 250


@dataclass(frozen=True)
class GeocodeResult:
    lat: float
    lon: float
    label: str


@dataclass(frozen=True)
class RouteResult:
    coords: tuple[tuple[float, float], ...]
    distance_m: float
    duration_min: float
    is_fallback: bool
    message: str


@dataclass(frozen=True)
class ReverseGeocodeResult:
    street: str
    label: str


def street_from_address(address: dict[str, str]) -> str | None:
    for key in (
        "road",
        "pedestrian",
        "footway",
        "path",
        "cycleway",
        "residential",
        "square",
        "place",
        "neighbourhood",
    ):
        value = address.get(key)
        if value:
            return value
    return None


@st.cache_data(ttl=86400, show_spinner=False)
def geocode_address(query: str) -> GeocodeResult:
    query = query.strip()
    if not query:
        raise ValueError("Enter an address or landmark to search.")

    try:
        from geopy.geocoders import Nominatim

        geocoder = Nominatim(user_agent=USER_AGENT, timeout=10)
        location = geocoder.geocode(query)
        if location is None:
            raise ValueError("Address not found. Try a more specific Lisbon address.")
        return GeocodeResult(float(location.latitude), float(location.longitude), location.address)
    except ImportError:
        return geocode_address_with_requests(query)


def geocode_address_with_requests(query: str) -> GeocodeResult:
    import requests

    response = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": query, "format": "json", "limit": 1},
        headers={"User-Agent": USER_AGENT},
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload:
        raise ValueError("Address not found. Try a more specific Lisbon address.")

    first = payload[0]
    return GeocodeResult(float(first["lat"]), float(first["lon"]), first.get("display_name", query))


@st.cache_data(ttl=86400, show_spinner=False)
def reverse_geocode_street(lat: float, lon: float) -> ReverseGeocodeResult:
    lat = round(lat, 6)
    lon = round(lon, 6)

    try:
        from geopy.geocoders import Nominatim

        geocoder = Nominatim(user_agent=USER_AGENT, timeout=10)
        location = geocoder.reverse((lat, lon), exactly_one=True, addressdetails=True, zoom=18)
        if location is None:
            return ReverseGeocodeResult("Street unavailable", "No reverse geocoding result.")

        raw = getattr(location, "raw", {}) or {}
        address = raw.get("address", {}) or {}
        street = street_from_address(address) or "Street unavailable"
        return ReverseGeocodeResult(street, raw.get("display_name", location.address))
    except ImportError:
        return reverse_geocode_street_with_requests(lat, lon)
    except Exception:
        return reverse_geocode_street_with_requests(lat, lon)


def reverse_geocode_street_with_requests(lat: float, lon: float) -> ReverseGeocodeResult:
    import requests

    response = requests.get(
        "https://nominatim.openstreetmap.org/reverse",
        params={
            "lat": lat,
            "lon": lon,
            "format": "jsonv2",
            "zoom": 18,
            "addressdetails": 1,
        },
        headers={"User-Agent": USER_AGENT},
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    address = payload.get("address", {}) or {}
    street = street_from_address(address) or "Street unavailable"
    return ReverseGeocodeResult(street, payload.get("display_name", "No reverse geocoding label."))


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_walking_route(start_lat: float, start_lon: float, end_lat: float, end_lon: float) -> RouteResult:
    start_lat = round(start_lat, 6)
    start_lon = round(start_lon, 6)
    end_lat = round(end_lat, 6)
    end_lon = round(end_lon, 6)
    direct_distance_m = haversine(start_lat, start_lon, end_lat, end_lon)

    if direct_distance_m < 1:
        return fallback_route(start_lat, start_lon, end_lat, end_lon, "Already at the recommended zone.")

    try:
        import requests

        errors: list[str] = []
        for osrm_url in OSRM_URLS:
            url = f"{osrm_url}/{start_lon},{start_lat};{end_lon},{end_lat}"
            try:
                response = requests.get(
                    url,
                    params={"overview": "full", "geometries": "geojson"},
                    headers={"User-Agent": USER_AGENT},
                    timeout=8,
                )
                response.raise_for_status()
                payload = response.json()
                routes = payload.get("routes") or []
                if not routes:
                    errors.append("No OSRM route found.")
                    continue

                route = routes[0]
                raw_coords = route.get("geometry", {}).get("coordinates") or []
                coords = tuple((float(lat), float(lon)) for lon, lat in raw_coords)
                if len(coords) < 2:
                    errors.append("OSRM returned no route geometry.")
                    continue

                route_distance_m = float(route.get("distance", 0))
                max_reasonable_distance = max(
                    direct_distance_m * MAX_ROUTE_DETOUR_RATIO,
                    direct_distance_m + MAX_ROUTE_DETOUR_EXTRA_M,
                )
                if route_distance_m > max_reasonable_distance:
                    errors.append(
                        f"OSRM route was {route_distance_m:.0f}m for a {direct_distance_m:.0f}m direct distance."
                    )
                    continue

                return RouteResult(
                    coords=coords,
                    distance_m=route_distance_m,
                    duration_min=float(route.get("duration", 0)) / 60,
                    is_fallback=False,
                    message="OSRM pedestrian route",
                )
            except Exception as exc:
                errors.append(str(exc))

        return fallback_route(start_lat, start_lon, end_lat, end_lon, "Route fallback: " + " | ".join(errors))
    except Exception as exc:
        return fallback_route(start_lat, start_lon, end_lat, end_lon, f"Route fallback: {exc}")


def fallback_route(start_lat: float, start_lon: float, end_lat: float, end_lon: float, message: str) -> RouteResult:
    distance_m = haversine(start_lat, start_lon, end_lat, end_lon)
    return RouteResult(
        coords=((start_lat, start_lon), (end_lat, end_lon)),
        distance_m=distance_m,
        duration_min=walking_time_from_distance(distance_m),
        is_fallback=True,
        message=message,
    )
