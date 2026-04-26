# BestParking

BestParking is a Streamlit web application that helps users find cheaper parking zones near their current location. It uses local parking-zone data from `listzones.xml`, checks the user's position, and displays nearby cheaper zones on an interactive map.

## Features

- Detects the user's current location using browser geolocation.
- Allows manual location selection by clicking on the map.
- Lets the user choose a search radius: 100m, 300m, 500m, or 1000m.
- Identifies the current parking-zone price.
- Finds cheaper nearby paid parking zones.
- Displays recommended zones on a Folium map.

## Project Structure

```text
.
├── Project.py          # Main Streamlit application
├── listzones.xml       # Parking-zone data with polygons and zone information
├── requirements.txt    # Python dependencies
└── README.md           # Project documentation
```

## Requirements

- Python 3.9 or newer
- pip

Python packages:

```text
streamlit
folium
streamlit-folium
streamlit-geolocation
```

## Installation

Clone or download the project, then install the dependencies:

```bash
pip install -r requirements.txt
```

## Running the App

Start the Streamlit application with:

```bash
streamlit run Project.py
```

Streamlit will open the app in your browser. If it does not open automatically, copy the local URL shown in the terminal.

## How It Works

1. The app loads parking-zone polygons from `listzones.xml`.
2. Each zone is assigned a price based on its color:
   - Green: EUR 0.80/hour
   - Yellow: EUR 1.20/hour
   - Red: EUR 1.60/hour
   - Brown: EUR 2.00/hour
3. The user's location is detected through GPS or selected manually on the map.
4. The app checks whether the user is inside a paid parking zone.
5. If the user is in a paid zone, the app searches for cheaper zones within the selected radius.
6. Recommended zones are highlighted on the map.

## Main Technologies

- **Streamlit**: Web app interface
- **Folium**: Interactive map rendering
- **streamlit-folium**: Folium integration inside Streamlit
- **streamlit-geolocation**: Browser-based geolocation
- **ElementTree**: XML parsing

## Notes

- The app depends on the `listzones.xml` file being present in the same directory as `Project.py`.
- If browser geolocation is unavailable, the app uses a default location in Lisbon.
- A clicked map location overrides the GPS location until the user returns to the home page.
