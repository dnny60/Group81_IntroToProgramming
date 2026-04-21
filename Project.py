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

COLOR_HEX = {
    "green":  "#2ecc71",
    "yellow": "#f1c40f",
    "red":    "#e74c3c",
    "brown":  "#a0522d"
}

# =========================
# DISTÂNCIA ENTRE PONTOS
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
        if ((yi > lon) != (yj > lon)) and (lat < (xj - xi) * (lon - yi) / (yj - yi + 1e-9) + xi):
            inside = not inside
        j = i
    return inside

# =========================
# LER XML
# =========================
def load_polygons(xml_file):
    tree = ET.parse(xml_file)
    root = tree.getroot()
 
    parking_tables = root.findall(f".//{{{NS_PARKING}}}parkingTable")
    polygons = []
 
    for table in parking_tables:
        color = None
        for elem in table.findall(f".//{{{NS_COMMON}}}value"):
            if elem.text and color is None:
                text = elem.text.lower()
                if "verde" in text:       color = "green"
                elif "amarela" in text:   color = "yellow"
                elif "vermelha" in text:  color = "red"
                elif "castanha" in text:  color = "brown"
 
        if not color:
            continue
 
        for posList in table.findall(f".//{{{NS_LOC}}}posList"):
            if not posList.text:
                continue
 
            for bloco in posList.text.split(';'):
                pairs = re.findall(r'\[(-?\d+\.\d+),\s*(-?\d+\.\d+)\]', bloco)
                coords = []
                for lon_str, lat_str in pairs:
                    try:
                        coords.append((float(lat_str), float(lon_str)))
                    except ValueError:
                        continue
 
                if len(coords) >= 3:
                    centroid_lat = sum(c[0] for c in coords) / len(coords)
                    centroid_lon = sum(c[1] for c in coords) / len(coords)
                    polygons.append({
                        "coords": coords,
                        "color": color,
                        "centroid_lat": centroid_lat,
                        "centroid_lon": centroid_lon,
                    })
 
    print(f"[DEBUG] Zonas carregadas: {len(polygons)}")
    return polygons

# =========================
# LÓGICA PRINCIPAL
# =========================

# Retorna o preço da zona em que o utilizador se encontra, ou nenhuma se for não paga
def get_current_zone(polygons, user_lat, user_lon):
    for poly in polygons:
        if point_in_polygon(user_lat, user_lon, poly["coords"]):
            return prices[poly["color"]]
    return None  # zona não paga

# Retorna (cheapest_price, list_of_cheap_polygons) para todas as zonas na qual o vértice está dentro do raio selecionado pelo utilizador
def find_cheapest_nearby(polygons, user_lat, user_lon, radius, cheaper_than=None):
    cheapest_price = float('inf')
    cheapest_polygons = []
 
    for poly in polygons:

        dist = haversine(user_lat, user_lon, poly["centroid_lat"], poly["centroid_lon"])
        if dist > radius:
            continue
 
        price = prices[poly["color"]]
        if cheaper_than is not None and price >= cheaper_than:
            continue
 
        if price < cheapest_price:
            cheapest_price = price
            cheapest_polygons = [poly]
        elif price == cheapest_price:
            cheapest_polygons.append(poly)
 
    if cheapest_price == float('inf'):
        return None, []
    return cheapest_price, cheapest_polygons


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

        radius = st.selectbox("Choose the search radius (meters):", [100, 300, 500, 1000])

        # ---------------------------
        # 1. LOCALIZAÇÃO
        # ---------------------------
        
        DEFAULT_LAT, DEFAULT_LON = 38.749386, -9.157919
        user_lat, user_lon = DEFAULT_LAT, DEFAULT_LON
        location_source = None  # "gps", "click", or None (= default)

        if loc and loc['latitude'] is not None and loc['longitude'] is not None:
            user_lat = loc['latitude']
            user_lon = loc['longitude']
            location_source = "gps"

        if 'clicked_lat' in st.session_state:
            user_lat = st.session_state.clicked_lat
            user_lon = st.session_state.clicked_lon
            location_source = "click"
 
        location_ready = location_source is not None

        if not location_ready:
            st.warning(
                "⚠️ Your location could not be detected. "
                "Showing a default position in Lisbon. "
                "Please press the location button above, or tap the map to set your position."
            )

        # ---------------------------
        # 2. MENSAGENS DE TEXTO 
        # ---------------------------
        cheap_polys = []

        if location_ready:
            current_price = get_current_zone(polygons, user_lat, user_lon)

            if current_price is None:
                st.success("🎉 You are in a free zone (€0/hour)! This is the best possible spot.")
                cheap_polys = [] 
            else:
                st.error(f"📍 You are in a **€{current_price:.2f}/hour** zone.")
                cheap_price, cheap_polys = find_cheapest_nearby(polygons, user_lat, user_lon, radius, cheaper_than=current_price)
                
                if cheap_price is not None:
                    st.success(f"💸 Found {len(cheap_polys)} zone(s) nearby for only **€{cheap_price:.2f}/hour**! Check the map.")
                else:
                    st.info(f"✅ You are already in the cheapest paid zone within a {radius}m radius.")
        else:
            st.info("👆 Please click the location button above, or tap on the map to find the best spots.")
            

        # ----------------------
        # 2. O DESENHO DO MAPA
        # ----------------------
        st.write("*(You can tap anywhere on the map to change your location)*")

        m = folium.Map(location=[user_lat, user_lon], zoom_start=15)

        for poly in cheap_polys:
            hex_color = COLOR_HEX[poly["color"]]
            folium.Polygon(
                locations=poly["coords"],
                color=hex_color,
                weight=3,
                fill=True,
                fill_color=hex_color,
                fill_opacity=0.45,
                tooltip=f"✅ €{prices[poly['color']]:.2f}/hour"
            ).add_to(m)
 
        if location_ready:
            folium.Marker(
                [user_lat, user_lon],
                popup="You are here",
                icon=folium.Icon(color="black", icon="car", prefix='fa')
            ).add_to(m)
 
            folium.Circle(
                location=[user_lat, user_lon],
                radius=radius,
                color="#3388ff",
                weight=2,
                dash_array="5, 10",
                fill=True,
                fill_opacity=0.05
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