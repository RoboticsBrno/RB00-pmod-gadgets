# Manuál k modulu

## Součástky

| Označení | Typ                              | Hodnota    | Počet |
| -------- | -------------------------------- | ---------- | ----- |
| U1       | DRV8833PWP – řídicí obvod motoru | DRV8833PWP | 1     |
| D1       | dioda                            | —          | 1     |
| JP1      | jumper                           | —          | 1     |
| C1       | kondenzátor                      | 10 µF      | 1     |
| C4       | kondenzátor                      | 100 nF     | 1     |
| C3       | kondenzátor                      | 2.2 µF     | 1     |
| C2       | kondenzátor                      | 22 µF      | 1     |
| J2, J5   | konektor                         | —          | 2     |
| J1, J4   | pinový konektor 2.54 mm          | —          | 2     |
| R2       | rezistor                         | 1 kΩ       | 1     |
| R1       | rezistor                         | 10 kΩ      | 1     |
| Q1       | tranzistor                       | AO3401A    | 1     |

### 1. Prázdná deska

Prázdná deska připravená k osazování.

![](assets/steps/01-empty.png)

### 2. DRV8833PWP – řídicí obvod motoru

!!! warning "Pozor"
    **U1** (**DRV8833PWP**) — Zkontrolujte správnou orientaci součástky podle orientační značky nebo pinu 1 na pouzdře.

Zapájejte řídicí obvod **U1** (**DRV8833PWP**) na horní stranu desky plošných spojů.

![](assets/steps/02-driver.png)

### 3. Tranzistor

!!! warning "Pozor"
    **Q1** (tranzistor, **AO3401A**) — Tranzistor musí být správně orientovaný — zkontrolujte označení pouzdra.

Zapájejte tranzistor **Q1** (**AO3401A**) na horní stranu DPS.

![](assets/steps/03-mosfet.png)

### 4. Dioda

!!! danger "Pozor"
    **D1** (dioda) — Dioda je polarizovaná — zkontrolujte orientaci anody a katody před pájením.

Zapájejte **D1** (dioda) na horní stranu DPS.

![](assets/steps/04-led.png)

### 5. Rezistor

Zapájejte rezistor **R2** (rezistor, **1 kΩ**) na horní stranu DPS.

![](assets/steps/05-resistor-1k.png)

### 6. Rezistor

Zapájejte rezistor **R1** (rezistor, **10 kΩ**) na horní stranu DPS.

![](assets/steps/06-resistor-10k.png)

### 7. Kondenzátor

Zapájejte **C4** (kondenzátor, **100 nF**) na horní stranu DPS.

![](assets/steps/07-capacitor-100n.png)

### 8. Kondenzátor

Zapájejte kondenzátor **C1** (**10 µF**) na horní stranu DPS.

![](assets/steps/08-capacitor-10u.png)

### 9. Kondenzátor

Zapájejte **C3** (kondenzátor, **2.2 µF**) na horní stranu DPS.

![](assets/steps/09-capacitor-2.2u.png)

### 10. Kondenzátor

Zapájejte kondenzátor **C2** (**22 µF**) na horní stranu DPS.

![](assets/steps/10-capacitor-22u.png)

### 11. Pinový konektor 2.54 mm

Zapájejte pinový konektor **J1** na horní stranu DPS.

![](assets/steps/11-pmod-header.png)

### 12. Pinový konektor 2.54 mm, Jumper

Zapájejte pinový konektor **J4** a jumper **JP1** na horní stranu desky.

![](assets/steps/12-headers.png)

### 13. Konektory

Zapájejte **J2** a **J5** (konektor) na horní stranu desky.

![](assets/steps/13-terminals.png)
