import RPi.GPIO as GPIO
from mfrc522 import SimpleMFRC522

# Initialiser le lecteur RFID
reader = SimpleMFRC522()

try:
    print("Approchez votre carte ou badge...")
    id = reader.read()[0] # le 1er element est l'id
    print(f"ID du badge: {id}")

finally:
    GPIO.cleanup()
