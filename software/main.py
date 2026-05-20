import RPi.GPIO as GPIO
from mfrc522 import SimpleMFRC522
import requests
import time

# ─── Configuration ───────────────────────────────────────────
API_BASE_URL = "http://localhost:8000"
READER_ID    = "READER-PI-1"   # ID de ce lecteur dans l'API

# Ports BCM des LEDs Grove (ports D5 et D16 du Grove Base Hat)
LED_VERT  = 16   # Port D16
LED_ROUGE = 5    # Port D5

# ─── Init GPIO ───────────────────────────────────────────────
GPIO.setmode(GPIO.BCM)
GPIO.setup(LED_VERT,  GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(LED_ROUGE, GPIO.OUT, initial=GPIO.LOW)

# ─── Init lecteur RFID ───────────────────────────────────────
reader = SimpleMFRC522()


def flash_led(pin, duree=2):
    """Allume une LED pendant `duree` secondes puis l'éteint."""
    GPIO.output(pin, GPIO.HIGH)
    time.sleep(duree)
    GPIO.output(pin, GPIO.LOW)


def verifier_badge(card_id: str) -> bool:
    """Envoie le badge à l'API et retourne True si accès autorisé."""
    try:
        response = requests.post(
            f"{API_BASE_URL}/check",
            json={"cardId": str(card_id), "readerId": READER_ID},
            timeout=5
        )
        data = response.json()
        return data.get("valid", False)
    except requests.RequestException as e:
        print(f"[ERREUR API] {e}")
        return False


# ─── Boucle principale ───────────────────────────────────────
print("Lecteur prêt !")
print(f"API : {API_BASE_URL}")
print(f"Lecteur ID : {READER_ID}")
print("...\n")

try:
    while True:
        card_id, _ = reader.read()
        print(f"Badge détecté : {card_id}")

        if verifier_badge(card_id):
            print("Accès AUTORISÉ")
            flash_led(LED_VERT, duree=2)
        else:
            print("Accès REFUSÉ")
            flash_led(LED_ROUGE, duree=2)

        print("...\n")
        time.sleep(1)   # Petite pause pour éviter les double-lectures

finally:
    GPIO.cleanup()
    print("GPIO nettoyés.")
