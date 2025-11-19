# Jak přidat další PMOD gadget

## Soubory
Zkopíruj si složku `template` v `pmod` a přejmenuj si jí pro tvůj gadget.

## KiCad
Vytvoř si složku `KiCad` pod svým gadgetem a do ní dej všechny soubory z KiCad projektu

## Dokumentace
V templatu jsou dva soubory `README.md` a `manual.md`.
Do `README.md` dejte popis co to je za modul, co děla, jak vypadá....
Do `manual.md` dejte návod na sestavení


## Navigace
Do `mkdocs.yml` úplně dole v sekci `nav` přidej název gadgety a umístění .md souborů. 

## Obrázek
V adresáři gadgetu musí být adresář `assets`. Tam musí existovat obrázek `default.png`!!
Vytvořze si složku `assets-large`, tam dávejte velké fotky, automaticky se zmenší na vhodnou velikost pro zmenšení velikosti repozitáře. Automaticky se vloží do složky `assets`.

## Poznámky, varování...
[Odkaz na dokumentaci](https://squidfunk.github.io/mkdocs-material/reference/admonitions/#usage)

Pokud není něco jasné koukni se do `IR` modulu, nebo napiš na discord.