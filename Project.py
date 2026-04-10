import xml.etree.ElementTree as ET
import tkinter as tk
from tkinter import ttk, messagebox
import math
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
    return 38.749386, -9.157919  # Lisboa — substitui por GPS real

# =========================
# LÓGICA PRINCIPAL
# =========================
def min_dist_to_polygon(user_lat, user_lon, coords):
    """Distância ao vértice mais próximo do polígono."""
    return min(haversine(user_lat, user_lon, p[0], p[1]) for p in coords)

def find_best_zone(polygons, user_lat, user_lon, radius):
    current_zone = None
    nearby_zones = []

    for poly in polygons:
        coords = poly["coords"]
        price  = prices[poly["color"]]

        # Dentro da zona → conta sempre, independente do raio
        if point_in_polygon(user_lat, user_lon, coords):
            current_zone = price
            nearby_zones.append(price)
            continue

        # Fora da zona → mede distância ao ponto mais próximo
        dist = min_dist_to_polygon(user_lat, user_lon, coords)
        if dist <= radius:
            nearby_zones.append(price)

    if not nearby_zones:
        return "Não há zonas nesse raio."

    min_price = min(nearby_zones)

    if current_zone is not None and current_zone <= min_price:
        return "Estás na zona mais barata 🎉"
    else:
        return f"Há zonas mais baratas por {min_price}€/hora"

# =========================
# INTERFACE
# =========================
def run_app():
    polygons = load_polygons(r"C:\Users\utilizador\OneDrive - Nova SBE\Introduction to Programming\listzones.xml")

    def check():
        radius = int(combo.get())
        lat, lon = get_user_location()
        result = find_best_zone(polygons, lat, lon, radius)
        messagebox.showinfo("Resultado", result)

    root = tk.Tk()
    root.title("Zonas de Estacionamento")

    tk.Label(root, text="Escolhe o raio (metros):").pack(pady=10)

    combo = ttk.Combobox(root, values=[100, 300, 500])
    combo.current(0)
    combo.pack()

    tk.Button(root, text="Verificar", command=check).pack(pady=20)

    root.mainloop()

# =========================
# RUN
# =========================
run_app()