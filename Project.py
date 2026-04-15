import streamlit as st
import folium
from streamlit_folium import st_folium
from streamlit_geolocation import streamlit_geolocation
import math
import xml.etree.ElementTree as ET
import re

# =========================
# NAMESPACES DO XML
# =========================
NS_MC      = "http://datex2.eu/schema/3/messageContainer"
NS_PARKING = "http://datex2.eu/schema/3/parking"
NS_COMMON  = "http://datex2.eu/schema/3/common"
NS_LOC     = "http://datex2.eu/schema/3/locationReferencing"

# =========================
# PREÇOS POR COR
# =========================
prices = {
    "green":  0.80,
    "yellow": 1.20,
    "red":    1.60,
    "brown":  2.00
}

# =========================
# DISTÂNCIA (Haversine)
# =========================
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi    = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

# =========================
# PONTO DENTRO DO POLÍGONO
# =========================
def point_in_polygon(lat, lon, polygon):
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > lon) != (yj > lon)) and \
           (lat < (xj - xi) * (lon - yi) / (yj - yi + 1e-9) + xi):
            inside = not inside
        j = i
    return inside

# =========================
# LER XML
# =========================
def load_polygons(xml_file):
    tree = ET.parse(xml_file)
    root = tree.getroot()

    payload = root.find(f"{{{NS_MC}}}payload")
    parking_tables = payload.findall(f"{{{NS_PARKING}}}parkingTable")

    polygons = []

    for parking in parking_tables:

        # -------- COR --------
        color = None
        for elem in parking.iter(f"{{{NS_COMMON}}}value"):
            if elem.text and color is None:
                text = elem.text.lower()
                if "verde" in text:
                    color = "green"
                elif "amarela" in text:
                    color = "yellow"
                elif "vermelha" in text:
                    color = "red"
                elif "castanha" in text:
                    color = "brown"

        # -------- POLÍGONO --------
        for posList in parking.iter(f"{{{NS_LOC}}}posList"):
            if not posList.text:
                continue

            pairs = re.findall(r'-?\d+\.\d+,\s*-?\d+\.\d+', posList.text)
            coords = []
            for p in pairs:
                try:
                    lon, lat = map(float, p.split(','))
                    coords.append((lat, lon))
                except ValueError:
                    continue

            if coords and color:
                polygons.append({"coords": coords, "color": color})

    print(f"[DEBUG] Polígonos carregados: {len(polygons)}")
    return polygons

# =========================
# LOCALIZAÇÃO (SIMULADA)
# =========================
def get_user_location():
    return 38.749386, -9.157919  # Lisboa

# =========================
# LÓGICA PRINCIPAL
# =========================
def min_dist_to_polygon(user_lat, user_lon, coords):
    """Distância ao vértice mais próximo do polígono."""
    return min(haversine(user_lat, user_lon, p[0], p[1]) for p in coords)

def find_best_zone_with_polygon(polygons, user_lat, user_lon, radius):
  
    current_zone_price = None
    cheapest_price = float('inf')
    cheapest_polygon = None

    for poly in polygons:
        coords = poly["coords"]
        price = prices[poly["color"]]

        if point_in_polygon(user_lat, user_lon, coords):
            current_zone_price = price

        dist = min(haversine(user_lat, user_lon, p[0], p[1]) for p in coords)
        
        if dist <= radius:
            if price < cheapest_price:
                cheapest_price = price
                cheapest_polygon = poly

    return current_zone_price, cheapest_price, cheapest_polygon

# ==========================================
# 3. INTERFACE APLICAÇÃO
# ==========================================
def main():
    @st.cache_data
    def get_data():
        return load_polygons("listzones.xml")
    
    polygons = get_data()

    if 'page' not in st.session_state:
        st.session_state.page = "home"

    # ==========================================
    # PAGE 1: PÁGINA INICIAL
    # ==========================================
    if st.session_state.page == "home":
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.title("🚗 BestParking")
            st.write("Find the cheapest parking zone near you in the blink of an eye.")
            
            st.write("") 
            
            if st.button("Start 🚀", use_container_width=True):
                st.session_state.page = "map"
                st.rerun() 

    # ==========================================
    # PAGE 2: MAPA E RESULTADOS
    # ==========================================
    elif st.session_state.page == "map":
        st.title("📍 BestParking")

        st.write("Tap below to get your current location:")
        loc = streamlit_geolocation()

        user_lat, user_lon = 38.749386, -9.157919

        if loc and loc['latitude'] is not None and loc['longitude'] is not None:
            user_lat = loc['latitude']
            user_lon = loc['longitude']

        if 'clicked_lat' in st.session_state:
            user_lat = st.session_state.clicked_lat
            user_lon = st.session_state.clicked_lon

        radius = st.selectbox("Choose the search radius (meters):", [100, 300, 500, 1000])

        current_price, cheap_price, cheap_poly = find_best_zone_with_polygon(polygons, user_lat, user_lon, radius)

        # MENSAGENS DE RESULTADO
        if current_price is None:
            st.success("🎉 You are in a free zone (€0/hour)! This is the best possible spot.")
            cheap_poly = None 
        else:
            st.error(f"📍 You are in a **€{current_price:.2f}/hour** zone.")
            
            if cheap_price < current_price:
                st.success(f"💸 The cheapest zone within {radius}m costs only **€{cheap_price:.2f}/hour**! Check the map.")
            else:
                st.info(f"✅ You are already in the cheapest paid zone within a {radius}m radius.")

        # DESENHO DO MAPA
        st.write("*(You can tap anywhere on the map to change your location)*")
        m = folium.Map(location=[user_lat, user_lon], zoom_start=15)

        folium.Marker(
            [user_lat, user_lon], 
            popup="You are here", 
            icon=folium.Icon(color="black", icon="car", prefix='fa')
        ).add_to(m)

        if cheap_poly:
            folium.Polygon(
                locations=cheap_poly["coords"],
                color=cheap_poly["color"],
                fill=True,
                fill_opacity=0.4
            ).add_to(m)

        map_data = st_folium(m, width=350, height=450)

        if map_data and map_data.get("last_clicked"):
            new_lat = map_data["last_clicked"]["lat"]
            new_lon = map_data["last_clicked"]["lng"]
            
            if new_lat != user_lat or new_lon != user_lon:
                st.session_state.clicked_lat = new_lat
                st.session_state.clicked_lon = new_lon
                st.rerun()

        if st.button("⬅️ Back to Home"):
            st.session_state.page = "home"
            if 'clicked_lat' in st.session_state:
                del st.session_state['clicked_lat']
                del st.session_state['clicked_lon']
            st.rerun()

if __name__ == "__main__":
    main()