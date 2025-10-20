import csv

# Define your new golf shot data
golf_data = [
    ["stroke_number", "hole_number", "latitude", "longitude"],
    [1, 1, 37.972241, -121.810302],
    [2, 1, 37.971043, -121.810119],
    [3, 1, 37.970157, -121.810390],
    [4, 1, 37.970077, -121.810187]
]

# Save to CSV file on your Desktop
with open("/Users/marcusduggs/Desktop/golf_data.csv", "w", newline="") as file:
    writer = csv.writer(file)
    writer.writerows(golf_data)

print("✅ golf_data.csv created successfully on your Desktop!")
