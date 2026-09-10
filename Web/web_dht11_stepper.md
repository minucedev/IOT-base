# Tạo server điều khiển stepper: thuận/ nghịch/ góc quay và theo dõi giá trị dht11


# Sơ đồ lắp mạch

## Raspberry Pi → ULN2003

| Raspberry Pi | ULN2003 |
|---|---|
| GPIO17 (Pin 11) | IN1 |
| GPIO18 (Pin 12) | IN2 |
| GPIO27 (Pin 13) | IN3 |
| GPIO22 (Pin 15) | IN4 |
| 5V | VCC |
| GND | GND |

**ULN2003 → 28BYJ-48:** cắm motor trực tiếp vào cổng MOTOR.

## DHT11 → Raspberry Pi

| DHT11 | Raspberry Pi |
|---|---|
| VCC | 3.3V |
| DATA | GPIO4 (Pin 7) |
| GND | GND |

## Sơ đồ

```text
Raspberry Pi          ULN2003          28BYJ-48
GPIO17 ─────────────> IN1
GPIO18 ─────────────> IN2
GPIO27 ─────────────> IN3
GPIO22 ─────────────> IN4
5V ─────────────────> VCC
GND ────────────────> GND ──────────> Motor

GPIO4 ───────────────────────────────> DHT11 DATA
3.3V ────────────────────────────────> DHT11 VCC
GND ─────────────────────────────────> DHT11 GND