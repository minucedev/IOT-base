from gpiozero import DistanceSensor
from time import sleep

sensor = DistanceSensor(echo=23, trigger=24)

while True:
    print(f"Distance: {sensor.distance * 100:.2f} cm")
    sleep(1)

