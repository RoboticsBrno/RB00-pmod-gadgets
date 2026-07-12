# Manuál k modulu

## Součástky

| Označení | Typ                     | Hodnota | Počet |
| -------- | ----------------------- | ------- | ----- |
| J2, J3   | JST SH konektor         | —       | 2     |
| J4       | pinový konektor 2.54 mm | —       | 1     |
| —        | Modul MPU6050           | —       | 1     |

### 1. Prázdná deska

Prázdná deska připravená k osazování.

![](assets/steps/01-empty.png)

### 2. JST SH konektory

Zapájejte **J2** a **J3** (JST SH konektor) na horní stranu desky.

![](assets/steps/02-usup-connector.png)

### 3. Pinový konektor 2.54 mm

Zapájejte pinový konektor **J4** na horní stranu desky.

![](assets/steps/03-gyro-header.png)

### 4. Modul MPU6050 - gyroskop + akcelerometr

Jsou dvě možnosti jak zapájet modul na desku

1. Na desku tak aby překrýval většinu desky. Vypadá tak lépe, ale zakryje díry na přidělání

2. Vyčnívající z desky tak, aby piny seděly k sobě:

    | Deska | Modul |
    | ----- | ----- |
    | 3V3   | VCC   |
    | GND   | GND   |
    | SCL   | SCL   |
    | SDA   | SDA   |