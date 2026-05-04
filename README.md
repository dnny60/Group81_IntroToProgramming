# BestParking

BestParking is a Streamlit web application that helps drivers compare regulated parking zones in Lisbon. It combines local EMEL parking-zone polygons from `listzones.xml` with address search, parking-duration pricing, filters, walking-route estimates, and a cost-distance recommendation score.

## Features

- Search a destination by address or landmark using Nominatim.
- Use browser GPS or click the map to set a destination.
- Restrict destination selection to the Lisbon municipality boundary when `lisbon_boundary.geojson` is available.
- Filter zones by color, distance, and unknown-price visibility.
- Enter parking duration and compare total estimated costs.
- Choose a parking date and start time so the app only charges hours that fall inside parsed paid schedules.
- Rank zones by a configurable cost-vs-distance balance.
- Reset filters to the default demo setup in one click.
- Highlight cheapest and optimal zones on the map.
- Draw walking routes to the nearest recommended zone edge using pedestrian OSRM, with straight-line fallback.
- Estimate the nearest street for the selected recommended parking point using reverse geocoding.
- Show a focused comparison table for the cheapest, optimal, and closest zones.
- Show zone details when a recommended row or map zone is selected.
- Warn when a parsed parking time limit is exceeded.

## Project Structure

```text
.
├── Project.py          # Streamlit UI and app state
├── parking_data.py     # XML parsing, constants, time-limit parsing
├── parking_logic.py    # Distance, filtering, pricing, scoring
├── geo_services.py     # Nominatim geocoding and OSRM routing
├── map_view.py         # Folium map rendering
├── boundary_data.py    # Lisbon boundary loading and validation
├── lisbon_boundary.geojson # Lisbon municipality boundary
├── listzones.xml       # Lisbon parking-zone data
├── requirements.txt    # Python dependencies
└── README.md           # Project documentation
```

## Installation

Use Python 3.10 or newer.

```bash
pip install -r requirements.txt
```

## Running the App

```bash
streamlit run Project.py
```

If the app does not open automatically, use the local URL shown in the terminal.

## Data

The app uses `listzones.xml`, a DATEX II XML file containing Lisbon regulated parking-zone polygons and metadata. It includes zone IDs, geographic boundaries, tariff colors, product/category text, schedules, and parking type details. It does not include live occupancy or individual parking bay availability.

For Lisbon-only map restrictions, the project includes `lisbon_boundary.geojson`, generated from OpenStreetMap relation `5400890` for the Lisbon municipality. It can be rebuilt from Overpass Turbo with:

```overpass
[out:json][timeout:25];
rel
  ["boundary"="administrative"]
  ["admin_level"="7"]
  ["name"="Lisboa"];
out geom;
```

If the file is missing or invalid, the app shows a warning and runs without the Lisbon boundary restriction.

## External Services

- **Nominatim**: address search and nearest-street reverse geocoding.
- **OSRM public routing services**: pedestrian route estimates.

Both services are cached by Streamlit to reduce repeated requests. If routing fails, or if OSRM returns an obviously excessive detour, the app estimates walking time from straight-line distance.

## Pricing Model

The app estimates price from the zone color:

- Green: EUR 0.80/hour
- Yellow: EUR 1.20/hour
- Red: EUR 1.60/hour
- Brown: EUR 2.00/hour

Total cost is calculated as:

```text
hourly price * charged hours
```

`charged hours` are estimated from the XML schedule when the app can parse it, for example `2ª A 6ª 9-19H` only charges the overlap with weekday 09:00-19:00.

The optimal recommendation balances cost and distance using the sidebar weighting control:

```text
Score = (cost/top_cost) * cost% + (distance/max_distance) * distance%
```
