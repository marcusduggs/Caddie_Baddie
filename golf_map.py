import csv
import folium

# Read golf shot data from CSV
with open("/Users/marcusduggs/Desktop/golf_data.csv", "r") as file:
    reader = csv.DictReader(file)
    golf_data = list(reader)

# Initialize map centered on first shot
start_lat = float(golf_data[0]["latitude"])
start_lon = float(golf_data[0]["longitude"])
golf_map = folium.Map(location=[start_lat, start_lon], zoom_start=18, tiles="OpenStreetMap")

# Create a list of coordinates for the path
coordinates = []
for shot in golf_data:
    lat = float(shot["latitude"])
    lon = float(shot["longitude"])
    coordinates.append((lat, lon))
    
    # Add a marker for each shot
    folium.Marker(
        [lat, lon],
        popup=f"Stroke {shot['stroke_number']} - Hole {shot['hole_number']}"
    ).add_to(golf_map)

# Draw a polyline (connects all the shots)
folium.PolyLine(
    locations=coordinates,
    color="blue",
    weight=4,
    opacity=0.8
).add_to(golf_map)

# Save to your Desktop
golf_map.save("/Users/marcusduggs/Desktop/golf_shots_map.html")

print("✅ Map created with connected shot path! Open golf_shots_map.html to view it.")
