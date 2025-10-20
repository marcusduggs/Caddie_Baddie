import os
import shutil

# Create a folder to store user profiles
os.makedirs("profiles", exist_ok=True)

# Ask for user input
name = input("Enter your name: ")

# Ask for profile picture path
picture_path = input("Enter the full path to your profile picture (e.g., /Users/marcusduggs/Desktop/photo.jpg): ")

# Create a folder for this user's profile
user_folder = os.path.join("profiles", name)
os.makedirs(user_folder, exist_ok=True)

# Save name in a text file
with open(os.path.join(user_folder, "info.txt"), "w") as file:
    file.write(f"Name: {name}\n")

# Copy the profile picture to the user's folder
if os.path.isfile(picture_path):
    picture_name = os.path.basename(picture_path)
    shutil.copy(picture_path, os.path.join(user_folder, picture_name))
    print(f"✅ Profile saved for {name}! Picture copied to {user_folder}.")
else:
    print("⚠️ Could not find the picture file. Please check the path and try again.")
