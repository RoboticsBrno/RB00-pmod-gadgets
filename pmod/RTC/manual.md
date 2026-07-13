# Manuál k modulu

## Součástky

| Označení | Typ                     | Hodnota | Počet |
| -------- | ----------------------- | ------- | ----- |
| J1       | pinový konektor 2.54 mm | 4pin    | 1     |
| —        | modul RTC-DS3231        | —       | 1     | 

### 1. Pinový konektor pro modul

Zapájejte 4-pinový konektor **J1** na horní stranu desky.

![](assets/steps/03-pmod-header.png)

### 2. RTC modul

Zapájejte RTC modul Vyčnívající z desky tak, aby piny seděly k sobě:

    | Deska | Modul |
    | ----- | ----- |
    | GND   | GND   |
    | VCC   | VCC   |
    | SDA   | SDA   |
    | SCL   | SCL   |