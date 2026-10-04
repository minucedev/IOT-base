from gpiozero import LED, Button
from signal import pause

LED_PIN = 16
BUTTON_PIN = 18

led = LED(LED_PIN)
button = Button(BUTTON_PIN, bounce_time=0.05)

def toggle_led():
    led.toggle()

button.when_pressed = toggle_led

print("Chuong trinh dang chay...")

try:
    pause()
except KeyboardInterrupt:
    print("\nDa dung chuong trinh.")
finally:
    led.off()
    led.close()
    button.close()
