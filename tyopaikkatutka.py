#!/usr/bin/env python3
"""Työpaikkatutka.

Vakio-Pythonilla toimiva työpaikkavahti, pisteytys ja pieni
Windows-käyttöliittymä.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import logging
import os
import queue
import re
import shutil
import sqlite3
import ssl
import sys
import threading
import traceback
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Iterable


APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
DEFAULT_CONFIG_PATH = APP_DIR / "config.default.json"
APP_ICON_PNG_PATH = APP_DIR / "assets" / "tyopaikkatutka.png"
APP_ICON_ICO_PATH = APP_DIR / "assets" / "tyopaikkatutka.ico"
FINLAND_LOCATIONS_PATH = APP_DIR / "resources" / "finland_locations_2026.json"
FINLAND_OCCUPATIONS_PATH = (
    APP_DIR / "resources" / "finland_occupations_tk10.json"
)
DATA_DIR = APP_DIR / "data"
REPORT_DIR = APP_DIR / "raportit"
LOG_DIR = APP_DIR / "logs"
BACKUP_DIR = APP_DIR / "varmuuskopiot"
DB_PATH = DATA_DIR / "jobs.db"
LOG_PATH = LOG_DIR / "tyopaikkatutka.log"
APP_NAME = "Työpaikkatutka"
APP_VERSION = "1.6.3"
CONFIG_VERSION = 8
DEADLINE_HEADING = "Haku päättyy"
PROFILE_SELECTION_LIST_HEIGHT = 8

QUALIFICATION_STATE_LABELS = {
    "yes": "Kyllä",
    "no": "Ei",
    "unknown": "En tiedä",
}

QUALIFICATION_GROUPS = (
    (
        "Ajokortit ja kuljetus",
        (
            ("B-ajokortti", "B-ajokortti"),
            ("BE-ajokortti", "BE-ajokortti"),
            ("C-ajokortti", "C-ajokortti"),
            ("CE-ajokortti", "CE-ajokortti"),
            ("ADR-ajolupa", "ADR-ajolupa"),
            ("kuljettajan ammattipätevyys", "Kuljettajan ammattipätevyys"),
            ("digipiirturikortti", "Digipiirturikortti"),
        ),
    ),
    (
        "Turvallisuus, varasto ja työmaat",
        (
            ("trukkikortti", "Trukkikortti tai trukinajolupa"),
            ("työturvallisuuskortti", "Työturvallisuuskortti"),
            ("tulityökortti", "Tulityökortti"),
            ("Tieturva 1", "Tieturva 1"),
            (
                "sähkötyöturvallisuuskortti SFS 6002",
                "Sähkötyöturvallisuuskortti SFS 6002",
            ),
            ("henkilönostinkortti", "Henkilönostinkortti tai nostinlupa"),
            (
                "nosturinkuljettajan pätevyys",
                "Nosturinkuljettajan pätevyys",
            ),
        ),
    ),
    (
        "Palvelu, ensiapu ja turvallisuusala",
        (
            ("hygieniapassi", "Hygieniapassi"),
            ("anniskelupassi", "Anniskelupassi"),
            ("ensiapukortti EA1", "Ensiapukortti EA1"),
            ("hätäensiapukortti", "Hätäensiapukortti"),
            ("järjestyksenvalvojakortti", "Järjestyksenvalvojakortti"),
            ("vartijakortti", "Vartijakortti"),
        ),
    ),
)

TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "msclkid",
    "ref",
    "source",
}

def load_finland_location_data(
    path: Path = FINLAND_LOCATIONS_PATH,
) -> dict[str, tuple[str, ...]]:
    """Lue sovelluksen mukana toimitettava virallinen kunta–maakunta-jako."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_regions = payload["regions"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Suomen sijaintiluokitusta ei voitu lukea: {path}"
        ) from exc
    if not isinstance(raw_regions, dict):
        raise RuntimeError("Suomen sijaintiluokituksen maakunnat puuttuvat.")
    regions: dict[str, tuple[str, ...]] = {}
    for region, municipalities in raw_regions.items():
        if not isinstance(region, str) or not isinstance(municipalities, list):
            raise RuntimeError("Suomen sijaintiluokituksen rakenne on virheellinen.")
        cleaned = tuple(
            clean
            for municipality in municipalities
            if (clean := str(municipality).strip())
        )
        if cleaned:
            regions[region.strip()] = cleaned
    if sum(len(items) for items in regions.values()) != 308:
        raise RuntimeError("Suomen sijaintiluokituksessa täytyy olla 308 kuntaa.")
    return regions


def load_finland_occupation_data(
    path: Path = FINLAND_OCCUPATIONS_PATH,
) -> tuple[tuple[str, str], ...]:
    """Lue Suomessa käytössä olevat viralliset TK10-ammattiluokat."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_occupations = payload["occupations"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Suomen ammattiluokitusta ei voitu lukea: {path}"
        ) from exc
    if not isinstance(raw_occupations, list):
        raise RuntimeError("Suomen ammattiluokituksen ammatit puuttuvat.")
    occupations: list[tuple[str, str]] = []
    for item in raw_occupations:
        if not isinstance(item, dict):
            raise RuntimeError("Suomen ammattiluokituksen rakenne on virheellinen.")
        code = str(item.get("code", "")).strip()
        name = str(item.get("name", "")).strip()
        if not code or not name:
            raise RuntimeError("Suomen ammattiluokituksessa on puutteellinen luokka.")
        occupations.append((code, name))
    if len(occupations) != 481:
        raise RuntimeError("Suomen ammattiluokituksessa täytyy olla 481 luokkaa.")
    if len({code for code, _ in occupations}) != len(occupations):
        raise RuntimeError("Suomen ammattiluokituksessa on päällekkäisiä koodeja.")
    if len({name.casefold() for _, name in occupations}) != len(occupations):
        raise RuntimeError("Suomen ammattiluokituksessa on päällekkäisiä nimiä.")
    return tuple(occupations)


FINLAND_REGIONS = load_finland_location_data()
FINLAND_MUNICIPALITIES = tuple(sorted((
    municipality
    for region in FINLAND_REGIONS.values()
    for municipality in region
), key=str.casefold))
KNOWN_LOCATIONS = FINLAND_MUNICIPALITIES
LOCATION_CHOICES = (
    "Koko Suomi",
    *(f"{region} — maakunta" for region in FINLAND_REGIONS),
    *(f"{municipality} — kunta" for municipality in FINLAND_MUNICIPALITIES),
)
FINLAND_OCCUPATIONS = load_finland_occupation_data()
OCCUPATION_CHOICES = tuple(sorted(
    (name for _, name in FINLAND_OCCUPATIONS),
    key=str.casefold,
))

STRENGTH_CHOICES = tuple(sorted((
    "aamu-, ilta- ja vuorotyö sopivat",
    "ahkera",
    "aikataulujen noudattaminen",
    "ajanhallinta",
    "aloitekykyinen",
    "analyyttinen",
    "asiakaspalveluhenkinen",
    "asiakkaan tarpeiden tunnistaminen",
    "avulias",
    "datan käsittely",
    "empaattinen",
    "ennakointikykyinen",
    "ergonomian huomioiminen",
    "esiintymistaidot",
    "eri-ikäisten kanssa työskentely",
    "hyvä asenne",
    "hyvä fyysinen kunto",
    "hyvä hahmotuskyky",
    "hyvä keskittymiskyky",
    "hyvä kuuntelija",
    "hyvä muisti",
    "hyvä muisti ja hahmotuskyky",
    "hyvä paineensietokyky",
    "hyvä tilannetaju",
    "hyvät asiakaspalvelutaidot",
    "hyvät digitaidot",
    "hyvät neuvottelutaidot",
    "hyvät tietokonetaidot",
    "hyvät tiimityötaidot",
    "hyvät vuorovaikutustaidot",
    "huolellinen",
    "havainnointikykyinen",
    "itsenäinen työskentely",
    "joustava",
    "joustavuus työajoissa",
    "johtamistaidot",
    "järjestelmällinen",
    "järjestyksen ylläpitäminen",
    "kehitysehdotusten tekeminen",
    "kielitaito",
    "kirjallinen viestintä",
    "kokemusta asiakaspalvelusta",
    "kokemusta inventoinnista",
    "kokemusta kassatyöstä",
    "kokemusta keräilystä",
    "kokemusta kokoonpanosta",
    "kokemusta kuorman purkamisesta ja lastaamisesta",
    "kokemusta laitoshuollosta",
    "kokemusta lähettämötyöstä",
    "kokemusta myyntityöstä",
    "kokemusta pakkaamisesta",
    "kokemusta pihanhoidosta ja ruohonleikkuusta",
    "kokemusta siivoustyöstä",
    "kokemusta tavaran vastaanotosta",
    "kokemusta tuotantotyöstä",
    "kokemusta varasto-, logistiikka- ja siivoustehtävistä",
    "kokemusta varastotyöstä",
    "kokemusta vihertöistä",
    "kokemusta ulkotöistä",
    "koneiden ja laitteiden käyttötaito",
    "konfliktien ratkaiseminen",
    "kädentaidot",
    "kärsivällinen",
    "laadukas työjälki",
    "laadun huomioiminen",
    "laadunvalvontaosaaminen",
    "looginen päättelykyky",
    "luotettava",
    "luova",
    "matemaattinen osaaminen",
    "monen tehtävän hallinta",
    "monikulttuurinen yhteistyö",
    "motivoitunut",
    "muutosvalmis",
    "nopea oppimaan",
    "nopea työskentelytahti",
    "numerotarkkuus",
    "ohjeiden noudattaminen",
    "ohjelmointiosaaminen",
    "oma-aloitteinen",
    "ongelmanratkaisukykyinen",
    "oppimishaluinen",
    "organisointikykyinen",
    "palautteen vastaanottaminen",
    "palveluhenkinen",
    "perehdyttämistaidot",
    "pitkäjänteinen",
    "positiivinen",
    "priorisointikykyinen",
    "prosessien kehittäminen",
    "projektinhallintataidot",
    "rauhallinen",
    "rakentavan palautteen antaminen",
    "ratkaisukeskeinen",
    "rehellinen",
    "rohkea",
    "selkeä kirjallinen viestintä",
    "selkeä suullinen viestintä",
    "siisteyden ylläpitäminen",
    "sitoutunut",
    "sopeutumiskykyinen",
    "stressinsietokykyinen",
    "suunnitelmallinen",
    "suullinen viestintä",
    "tarkka",
    "tavoitteellinen",
    "tehokas",
    "tekninen ymmärrys",
    "tiedonhakutaidot",
    "tietoturvan huomioiminen",
    "tiimityöskentely",
    "tuloshakuinen",
    "tunnollinen",
    "turvallinen työskentelytapa",
    "työkalujen käyttötaito",
    "työskentely ilman jatkuvaa ohjausta",
    "työturvallisuuden huomioiminen",
    "täsmällinen",
    "uusien järjestelmien nopea omaksuminen",
    "valmis aamu- ja iltatyöhön",
    "valmis fyysiseen työhön",
    "valmis nostotyöhön",
    "valmis seisomatyöhön",
    "valmis ulkotyöhön",
    "valmis viikonlopputyöhön",
    "valmis vuorotyöhön",
    "valmis yötyöhön",
    "varastonhoitajan koulutus",
    "vastuullinen",
    "vuorovaikutustaidot",
    "yhteistyökykyinen",
    "yksityiskohtien huomioiminen",
    "ystävällinen",
), key=str.casefold))

EXCLUDED_PHRASE_CHOICES = (
    "pelkkä provisiopalkka",
    "ainoastaan provisio",
    "toimeksiantosopimus",
    "kevyt-yrittäjä",
    "kevytyrittäjä",
    "franchising-yrittäjä",
    "maksullinen koulutus",
)

LOCATION_ALIASES = {
    "Ahvenanmaa": ("Åland", "Ahvenanmaalla", "Ahvenanmaan"),
    "Espoo": ("Esbo",),
    "Hanko": ("Hangö",),
    "Helsinki": ("Helsingfors",),
    "Inkoo": ("Ingå",),
    "Kauniainen": ("Grankulla",),
    "Kirkkonummi": ("Kyrkslätt",),
    "Kokkola": ("Karleby",),
    "Loviisa": ("Lovisa",),
    "Maarianhamina - Mariehamn": ("Maarianhamina", "Mariehamn"),
    "Pietarsaari": ("Jakobstad",),
    "Porvoo": ("Borgå",),
    "Raasepori": ("Raseborg",),
    "Sipoo": ("Sibbo",),
    "Siuntio": ("Sjundeå",),
    "Uusikaarlepyy": ("Nykarleby",),
    "Lappi": ("Lapissa", "Lapin", "Lappiin", "Lapista"),
    "Satakunta": ("Satakunnassa", "Satakunnan", "Satakuntaan", "Satakunnasta"),
    "Uusimaa": (
        "Nyland",
        "Uudellamaalla",
        "Uudenmaan",
        "Uudellemaalle",
        "Uudeltamaalta",
    ),
    "Vaasa": ("Vasa",),
    "Vantaa": ("Vanda",),
}

CUSTOM_LOCATION_ALIASES = {
    "paakaupunkiseutu": (
        "pääkaupunkiseutu",
        "pääkaupunkiseudulla",
        "pääkaupunkiseudun",
        "pääkaupunkiseudulle",
        "pääkaupunkiseudulta",
        "Helsinki",
        "Espoo",
        "Vantaa",
        "Kauniainen",
    ),
}

AGGREGATOR_SOURCE_PREFIXES = (
    "duunitori",
    "jobly",
    "laura.fi",
    "helsinki rekry",
    "bolt.works",
)

SOURCE_FILTER_ALL = "Kaikki lähteet"
SOURCE_FILTER_OTHER = "Muut lähteet"
SOURCE_JOB_CATEGORIES = (
    "Yleiset työpaikkapalvelut",
    "Varasto ja logistiikka",
    "Siivous ja kiinteistöpalvelut",
    "Tuotanto ja rakentaminen",
    "Kauppa ja asiakaspalvelu",
    "Julkinen sektori",
    "Ravintola ja ruokapalvelut",
    SOURCE_FILTER_OTHER,
)
SOURCE_CATEGORIES_BY_NAME = {
    "Posti": ("Varasto ja logistiikka",),
    "Lassila & Tikanoja": (
        "Siivous ja kiinteistöpalvelut",
        "Tuotanto ja rakentaminen",
    ),
    "SOL": ("Siivous ja kiinteistöpalvelut",),
    "ISS": ("Siivous ja kiinteistöpalvelut",),
    "StaffPoint": (
        "Varasto ja logistiikka",
        "Siivous ja kiinteistöpalvelut",
        "Tuotanto ja rakentaminen",
        "Kauppa ja asiakaspalvelu",
        "Ravintola ja ruokapalvelut",
    ),
    "WorkPower": (
        "Varasto ja logistiikka",
        "Siivous ja kiinteistöpalvelut",
        "Tuotanto ja rakentaminen",
    ),
    "Duunitori": (
        "Yleiset työpaikkapalvelut",
        "Varasto ja logistiikka",
        "Siivous ja kiinteistöpalvelut",
        "Tuotanto ja rakentaminen",
        "Kauppa ja asiakaspalvelu",
    ),
    "Jobly": (
        "Yleiset työpaikkapalvelut",
        "Varasto ja logistiikka",
        "Siivous ja kiinteistöpalvelut",
        "Tuotanto ja rakentaminen",
        "Kauppa ja asiakaspalvelu",
    ),
    "S-ryhmä": (
        "Varasto ja logistiikka",
        "Kauppa ja asiakaspalvelu",
        "Ravintola ja ruokapalvelut",
    ),
    "Laura.fi – Uusimaa": (
        "Yleiset työpaikkapalvelut",
        "Varasto ja logistiikka",
        "Siivous ja kiinteistöpalvelut",
        "Tuotanto ja rakentaminen",
        "Kauppa ja asiakaspalvelu",
    ),
    "Kuntarekry": (
        "Yleiset työpaikkapalvelut",
        "Siivous ja kiinteistöpalvelut",
        "Julkinen sektori",
        "Ravintola ja ruokapalvelut",
    ),
    "Helsinki Rekry": (
        "Siivous ja kiinteistöpalvelut",
        "Julkinen sektori",
        "Ravintola ja ruokapalvelut",
    ),
    "Valtiolle.fi": (
        "Yleiset työpaikkapalvelut",
        "Julkinen sektori",
    ),
    "Bolt.Works": (
        "Varasto ja logistiikka",
        "Siivous ja kiinteistöpalvelut",
        "Tuotanto ja rakentaminen",
    ),
    "Seure": (
        "Siivous ja kiinteistöpalvelut",
        "Julkinen sektori",
        "Ravintola ja ruokapalvelut",
    ),
    "Kesko": (
        "Varasto ja logistiikka",
        "Kauppa ja asiakaspalvelu",
        "Ravintola ja ruokapalvelut",
    ),
    "Palmia": (
        "Siivous ja kiinteistöpalvelut",
        "Ravintola ja ruokapalvelut",
    ),
    "Vantti": (
        "Siivous ja kiinteistöpalvelut",
        "Julkinen sektori",
        "Ravintola ja ruokapalvelut",
    ),
    "Eezy": (
        "Varasto ja logistiikka",
        "Siivous ja kiinteistöpalvelut",
        "Tuotanto ja rakentaminen",
        "Kauppa ja asiakaspalvelu",
        "Ravintola ja ruokapalvelut",
    ),
    "Manpower": (
        "Varasto ja logistiikka",
        "Tuotanto ja rakentaminen",
        "Kauppa ja asiakaspalvelu",
    ),
    "Bondata": (
        "Varasto ja logistiikka",
        "Siivous ja kiinteistöpalvelut",
        "Tuotanto ja rakentaminen",
        "Kauppa ja asiakaspalvelu",
        "Ravintola ja ruokapalvelut",
    ),
    "Amiko": (
        "Varasto ja logistiikka",
        "Siivous ja kiinteistöpalvelut",
        "Tuotanto ja rakentaminen",
        "Kauppa ja asiakaspalvelu",
        "Ravintola ja ruokapalvelut",
    ),
    "Worker": (
        "Varasto ja logistiikka",
        "Siivous ja kiinteistöpalvelut",
        "Tuotanto ja rakentaminen",
        "Kauppa ja asiakaspalvelu",
        "Ravintola ja ruokapalvelut",
    ),
    "RTK-Henkilöstöpalvelu": (
        "Varasto ja logistiikka",
        "Siivous ja kiinteistöpalvelut",
        "Tuotanto ja rakentaminen",
        "Kauppa ja asiakaspalvelu",
        "Ravintola ja ruokapalvelut",
    ),
}


def settings_tab_dimensions(selected: bool) -> tuple[int, int, int]:
    """Palauta välilehden korkeus, fonttikoko ja vaakasuuntainen sisennys."""
    return (44, 10, 20) if selected else (36, 9, 15)


def rounded_polygon_points(
    left: int,
    top: int,
    right: int,
    bottom: int,
    radius: int,
) -> list[int]:
    """Pisteet Canvasin pehmeäkulmaiselle suorakulmiolle."""
    radius = max(0, min(radius, (right - left) // 2, (bottom - top) // 2))
    return [
        left + radius,
        top,
        right - radius,
        top,
        right,
        top,
        right,
        top + radius,
        right,
        bottom - radius,
        right,
        bottom,
        right - radius,
        bottom,
        left + radius,
        bottom,
        left,
        bottom,
        left,
        bottom - radius,
        left,
        top + radius,
        left,
        top,
    ]


class RoundedButtonControl:
    """Canvas-pohjainen pyöristetty painike ilman käyttöjärjestelmän kehystä."""

    def __init__(
        self,
        tk_module: Any,
        parent: Any,
        *,
        text: str,
        command: Callable[[], None],
        palette: dict[str, str],
        primary: bool = False,
        tab: bool = False,
        selected: bool = False,
        minimum_width: int = 0,
    ) -> None:
        self.tk = tk_module
        self.text = text
        self.command = command
        self.palette = palette
        self.primary = primary
        self.tab = tab
        self.selected = selected
        self.minimum_width = minimum_width
        self.state = "normal"
        self.hovered = False
        self.pressed = False
        self.canvas = tk_module.Canvas(
            parent,
            borderwidth=0,
            highlightthickness=0,
            relief="flat",
            takefocus=1,
            cursor="hand2",
        )
        self.canvas.bind("<Enter>", self._on_enter)
        self.canvas.bind("<Leave>", self._on_leave)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Return>", self._on_keyboard)
        self.canvas.bind("<space>", self._on_keyboard)
        self.canvas.bind("<Configure>", lambda event: self._redraw())
        self._resize()
        self._redraw()

    def _metrics(self) -> tuple[int, tuple[Any, ...], int]:
        if self.tab:
            height, font_size, horizontal_padding = settings_tab_dimensions(
                self.selected
            )
            return height, ("Segoe UI", font_size, "bold"), horizontal_padding
        return (
            38,
            ("Segoe UI", 10, "bold" if self.primary else "normal"),
            15,
        )

    def _resize(self) -> None:
        height, font, horizontal_padding = self._metrics()
        temporary = self.canvas.create_text(0, 0, text=self.text, font=font)
        bounds = self.canvas.bbox(temporary) or (0, 0, 0, 0)
        self.canvas.delete(temporary)
        width = max(
            self.minimum_width,
            bounds[2] - bounds[0] + horizontal_padding * 2,
        )
        self.canvas.configure(width=width, height=height)

    def _colours(self) -> tuple[str, str, str]:
        palette = self.palette
        if self.state == "disabled":
            return palette["button"], palette["disabled"], palette["button"]
        if self.tab and self.selected:
            fill = palette["primary_active"] if self.hovered else palette["primary"]
            return fill, palette["selection_foreground"], palette["accent"]
        if self.primary:
            fill = (
                palette["primary_active"]
                if self.hovered or self.pressed
                else palette["primary"]
            )
            return fill, palette["selection_foreground"], palette["accent"]
        fill = (
            palette["button_active"]
            if self.hovered or self.pressed
            else palette["button"]
        )
        foreground = (
            palette["accent_bright"] if self.hovered else palette["foreground"]
        )
        return fill, foreground, palette["button_border"]

    def _redraw(self) -> None:
        try:
            if not self.canvas.winfo_exists():
                return
            self.canvas.delete("surface")
            self.canvas.configure(background=self.palette["background"])
            width = max(1, self.canvas.winfo_width())
            height = max(1, self.canvas.winfo_height())
            fill, foreground, outline = self._colours()
            points = rounded_polygon_points(1, 1, width - 1, height - 1, 8)
            self.canvas.create_polygon(
                points,
                smooth=True,
                splinesteps=24,
                fill=fill,
                outline=outline,
                width=1,
                tags="surface",
            )
            _, font, _ = self._metrics()
            self.canvas.create_text(
                width // 2,
                height // 2,
                text=self.text,
                fill=foreground,
                font=font,
                tags="surface",
            )
            if self.tab and self.selected:
                self.canvas.create_line(
                    10,
                    height - 3,
                    width - 10,
                    height - 3,
                    fill=self.palette["accent_bright"],
                    width=3,
                    capstyle="round",
                    tags="surface",
                )
        except self.tk.TclError:
            return

    def _on_enter(self, event: Any) -> None:
        self.hovered = True
        self._redraw()

    def _on_leave(self, event: Any) -> None:
        self.hovered = False
        self.pressed = False
        self._redraw()

    def _on_press(self, event: Any) -> None:
        if self.state != "disabled":
            self.pressed = True
            self._redraw()

    def _on_release(self, event: Any) -> None:
        if self.state == "disabled":
            return
        should_run = self.pressed
        self.pressed = False
        self._redraw()
        if should_run:
            self.command()

    def _on_keyboard(self, event: Any) -> str:
        if self.state != "disabled":
            self.command()
        return "break"

    def update_palette(self, palette: dict[str, str]) -> None:
        self.palette = palette
        self._redraw()

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        self._resize()
        self._redraw()

    def configure(self, **options: Any) -> None:
        if "state" in options:
            self.state = str(options.pop("state"))
            self._redraw()
        if options:
            self.canvas.configure(**options)

    config = configure

    def pack(self, **options: Any) -> None:
        self.canvas.pack(**options)

    def grid(self, **options: Any) -> None:
        self.canvas.grid(**options)


class ThemedCheckbuttonControl:
    """Teemallinen valintaruutu, jossa on selkeä valintamerkki."""

    def __init__(
        self,
        tk_module: Any,
        parent: Any,
        *,
        text: str,
        variable: Any,
        palette: dict[str, str],
        command: Callable[[], None] | None = None,
    ) -> None:
        self.tk = tk_module
        self.text = text
        self.variable = variable
        self.palette = palette
        self.command = command
        self.hovered = False
        self.canvas = tk_module.Canvas(
            parent,
            height=30,
            borderwidth=0,
            highlightthickness=0,
            relief="flat",
            cursor="hand2",
            takefocus=1,
        )
        temporary = self.canvas.create_text(
            0,
            0,
            text=text,
            font=("Segoe UI", 10),
        )
        bounds = self.canvas.bbox(temporary) or (0, 0, 0, 0)
        self.canvas.delete(temporary)
        self.canvas.configure(width=bounds[2] - bounds[0] + 42)
        self.canvas.bind("<Enter>", self._on_enter)
        self.canvas.bind("<Leave>", self._on_leave)
        self.canvas.bind("<ButtonRelease-1>", self._toggle)
        self.canvas.bind("<Return>", self._toggle)
        self.canvas.bind("<space>", self._toggle)
        self.variable.trace_add("write", lambda *args: self._redraw())
        self._redraw()

    def _redraw(self) -> None:
        try:
            if not self.canvas.winfo_exists():
                return
            self.canvas.delete("control")
            self.canvas.configure(background=self.palette["background"])
            selected = bool(self.variable.get())
            fill = self.palette["primary"] if selected else self.palette["card"]
            outline = (
                self.palette["accent"]
                if selected or self.hovered
                else self.palette["button_border"]
            )
            self.canvas.create_polygon(
                rounded_polygon_points(2, 5, 22, 25, 5),
                smooth=True,
                splinesteps=20,
                fill=fill,
                outline=outline,
                width=2,
                tags="control",
            )
            if selected:
                self.canvas.create_line(
                    7,
                    15,
                    11,
                    20,
                    18,
                    10,
                    fill=self.palette["selection_foreground"],
                    width=3,
                    capstyle="round",
                    joinstyle="round",
                    tags="control",
                )
            self.canvas.create_text(
                32,
                15,
                text=self.text,
                anchor="w",
                fill=(
                    self.palette["accent_bright"]
                    if self.hovered
                    else self.palette["foreground"]
                ),
                font=("Segoe UI", 10),
                tags="control",
            )
        except self.tk.TclError:
            return

    def _on_enter(self, event: Any) -> None:
        self.hovered = True
        self._redraw()

    def _on_leave(self, event: Any) -> None:
        self.hovered = False
        self._redraw()

    def _toggle(self, event: Any) -> str:
        self.variable.set(not bool(self.variable.get()))
        if self.command is not None:
            self.command()
        return "break"

    def update_palette(self, palette: dict[str, str]) -> None:
        self.palette = palette
        self._redraw()

    def pack(self, **options: Any) -> None:
        self.canvas.pack(**options)

    def grid(self, **options: Any) -> None:
        self.canvas.grid(**options)


def windows_prefers_dark() -> bool:
    """Palauta Windowsin sovellusteeman valinta, turvallisesti vaaleaan palautuen."""
    if not sys.platform.startswith("win"):
        return False
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return int(value) == 0
    except (ImportError, OSError, TypeError, ValueError):
        return False


def windows_colorref(color: str) -> int:
    """Muunna #RRGGBB Windowsin COLORREF-muotoon."""
    value = color.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"Virheellinen väri: {color}")
    red, green, blue = (int(value[index : index + 2], 16) for index in (0, 2, 4))
    return red | (green << 8) | (blue << 16)


def apply_windows_titlebar_theme(
    root: Any,
    dark: bool,
    palette: dict[str, str],
) -> bool:
    """Sovita Windowsin natiivi otsikkopalkki sovelluksen teemaan."""
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes

        root.update_idletasks()
        window_id = root.winfo_id()
        parent_id = ctypes.windll.user32.GetParent(window_id)
        window_handle = parent_id or window_id

        dark_value = ctypes.c_int(1 if dark else 0)
        for attribute in (20, 19):
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                window_handle,
                attribute,
                ctypes.byref(dark_value),
                ctypes.sizeof(dark_value),
            )
            if result == 0:
                break

        for attribute, key in (
            (34, "border"),
            (35, "caption"),
            (36, "caption_text"),
        ):
            color_value = ctypes.c_uint(windows_colorref(palette[key]))
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                window_handle,
                attribute,
                ctypes.byref(color_value),
                ctypes.sizeof(color_value),
            )
        return True
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def apply_windows_window_icon(
    root: Any,
    icon_path: Path = APP_ICON_ICO_PATH,
) -> tuple[int, int] | None:
    """Aseta ICO-kuvake suoraan Windows-ikkunan pieneen ja suureen ikonipaikkaan."""
    if not sys.platform.startswith("win") or not icon_path.exists():
        return None
    try:
        import ctypes

        root.update_idletasks()
        window_id = root.winfo_id()
        parent_id = ctypes.windll.user32.GetParent(window_id)
        window_handle = parent_id or window_id

        image_icon = 1
        load_from_file = 0x0010
        wm_seticon = 0x0080
        icon_small = 0
        icon_big = 1

        load_image = ctypes.windll.user32.LoadImageW
        try:
            load_image.restype = ctypes.c_void_p
        except AttributeError:
            pass
        small_handle = load_image(
            None,
            str(icon_path),
            image_icon,
            16,
            16,
            load_from_file,
        )
        big_handle = load_image(
            None,
            str(icon_path),
            image_icon,
            32,
            32,
            load_from_file,
        )
        if not small_handle or not big_handle:
            return None

        ctypes.windll.user32.SendMessageW(
            window_handle,
            wm_seticon,
            icon_small,
            small_handle,
        )
        ctypes.windll.user32.SendMessageW(
            window_handle,
            wm_seticon,
            icon_big,
            big_handle,
        )
        return int(small_handle), int(big_handle)
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def theme_palette(dark: bool) -> dict[str, str]:
    """Portfolion väreihin sovitettu vaalea tai tumma Windows-teema."""
    if dark:
        return {
            "background": "#06101d",
            "card": "#0a1a2c",
            "foreground": "#f5f9fd",
            "secondary": "#9eb4c8",
            "disabled": "#60788e",
            "accent": "#20d3f3",
            "accent_bright": "#53e3fb",
            "border": "#173b52",
            "button": "#0e2339",
            "button_active": "#12314e",
            "button_border": "#24627a",
            "heading": "#102a44",
            "primary": "#087fa8",
            "primary_active": "#069dd0",
            "selection": "#087fa8",
            "selection_foreground": "#ffffff",
            "trough": "#030a12",
            "caption": "#06101d",
            "caption_text": "#f5f9fd",
            "good_background": "#0d3836",
            "good_foreground": "#bcf4e2",
            "medium_background": "#3b3217",
            "medium_foreground": "#ffe7a3",
            "republished_background": "#0d3750",
            "republished_foreground": "#90e8ff",
            "applied_background": "#142f55",
            "applied_foreground": "#cae2ff",
            "ignored_background": "#0a1a2c",
            "ignored_foreground": "#60788e",
            "expired_background": "#4a2029",
            "expired_foreground": "#ffd0d5",
        }
    return {
        "background": "#edf6fa",
        "card": "#ffffff",
        "foreground": "#102235",
        "secondary": "#536d82",
        "disabled": "#8ca2b2",
        "accent": "#078fbe",
        "accent_bright": "#069dd0",
        "border": "#b5dbe8",
        "button": "#e6f4fa",
        "button_active": "#d1edf7",
        "button_border": "#8fc8dc",
        "heading": "#dceff6",
        "primary": "#087fa8",
        "primary_active": "#069dd0",
        "selection": "#087fa8",
        "selection_foreground": "#ffffff",
        "trough": "#d6e7ed",
        "caption": "#edf6fa",
        "caption_text": "#102235",
        "good_background": "#dff5ee",
        "good_foreground": "#123c35",
        "medium_background": "#fff4cf",
        "medium_foreground": "#5a4611",
        "republished_background": "#dff6ff",
        "republished_foreground": "#075b78",
        "applied_background": "#e7f0ff",
        "applied_foreground": "#173f70",
        "ignored_background": "#ffffff",
        "ignored_foreground": "#8ca2b2",
        "expired_background": "#ffe4e7",
        "expired_foreground": "#8f2632",
    }

TECHNICAL_SOURCE_MIGRATIONS = {
    "Laura.fi – Uusimaa",
    "Kuntarekry",
    "Helsinki Rekry",
    "Valtiolle.fi",
    "Bolt.Works",
}

EEZY_SOURCE_NAME = "Eezy"

ATS_DOMAINS = (
    "myworkdayjobs.com",
    "successfactors.eu",
    "talentadore.com",
    "reachmee.com",
    "teamtailor.com",
    "jobylon.com",
    "recright.com",
    "recman.no",
)


class SourceBlockedError(RuntimeError):
    """Sivusto vaatii oikean selaimen eikä sitä pidä käsitellä ohjelmavirheenä."""


def ensure_directories() -> None:
    for directory in (DATA_DIR, REPORT_DIR, LOG_DIR, BACKUP_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def configure_logging() -> None:
    ensure_directories()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def backup_file(path: Path, label: str) -> Path | None:
    if not path.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")
    destination = BACKUP_DIR / f"{label}_{stamp}{path.suffix}"
    shutil.copy2(path, destination)
    return destination


def merge_config_defaults(
    config: dict[str, Any], defaults: dict[str, Any]
) -> tuple[dict[str, Any], bool]:
    """Lisää uuden version puuttuvat asetukset muuttamatta käyttäjän valintoja."""
    changed = False
    original_app = config.get("app") if isinstance(config.get("app"), dict) else {}
    old_version = int(original_app.get("config_version", 1) or 1)

    def merge_dict(target: dict[str, Any], source: dict[str, Any]) -> None:
        nonlocal changed
        for key, value in source.items():
            if key == "sources":
                continue
            if key not in target:
                target[key] = value
                changed = True
            elif isinstance(value, dict) and isinstance(target.get(key), dict):
                merge_dict(target[key], value)

    merge_dict(config, defaults)

    current_sources = config.setdefault("sources", [])
    known_names = {
        fold_text(source.get("name"))
        for source in current_sources
        if isinstance(source, dict)
    }
    for source in defaults.get("sources", []):
        if isinstance(source, dict) and fold_text(source.get("name")) not in known_names:
            current_sources.append(source)
            known_names.add(fold_text(source.get("name")))
            changed = True

    # Version 1.3 sisälsi näille neljälle lähteelle oletetut sivustokartat,
    # joita palvelut eivät todellisuudessa tarjoa. Päivitetään vain tekniset
    # lähdeasetukset ja säilytetään käyttäjän käytössä/pois-valinta.
    if old_version < 4:
        defaults_by_name = {
            clean_space(source.get("name")): source
            for source in defaults.get("sources", [])
            if isinstance(source, dict)
        }
        for index, current in enumerate(current_sources):
            if not isinstance(current, dict):
                continue
            name = clean_space(current.get("name"))
            if name not in TECHNICAL_SOURCE_MIGRATIONS:
                continue
            replacement = defaults_by_name.get(name)
            if not replacement:
                continue
            enabled = current.get("enabled", True)
            current_sources[index] = {
                **replacement,
                "enabled": enabled,
            }
            changed = True

    # Eezy ei tarjoa työpaikkailmoituksia sivustokartassaan. Versiosta 1.6.1
    # alkaen lähde käyttää saman työpaikkahaun julkista rajapintaa, jota Eezyn
    # oma avoimien työpaikkojen sivu käyttää. Korjaus tehdään myös silloin, jos
    # config_version on jo ehtinyt päivittyä, mutta rikkinäinen lähdetyyppi on
    # jäänyt asetuksiin. Käyttäjän käytössä/pois-valinta säilytetään.
    defaults_by_name = {
        clean_space(source.get("name")): source
        for source in defaults.get("sources", [])
        if isinstance(source, dict)
    }
    eezy_replacement = defaults_by_name.get(EEZY_SOURCE_NAME)
    if eezy_replacement:
        for index, current in enumerate(current_sources):
            if not isinstance(current, dict):
                continue
            if clean_space(current.get("name")) != EEZY_SOURCE_NAME:
                continue
            if (
                current.get("type") == "eezy"
                and clean_space(current.get("api_url"))
            ):
                continue
            enabled = current.get("enabled", True)
            current_sources[index] = {
                **eezy_replacement,
                "enabled": enabled,
            }
            changed = True

    app = config.setdefault("app", {})
    if old_version < 2:
        if int(app.get("maximum_details_per_source", 35) or 35) == 35:
            app["maximum_details_per_source"] = 80
        qualifications = config.setdefault("profile", {}).setdefault("qualifications", {})
        # Vanhassa 1.1-asetuksessa B-ajokortin tila oli vielä "unknown".
        if qualifications.get("B-ajokortti") in {None, "", "unknown"}:
            qualifications["B-ajokortti"] = "no"
        changed = True
    if old_version < 5:
        if config.pop("email", None) is not None:
            changed = True
        if app.pop("email_on_first_run", None) is not None:
            changed = True
    if old_version < 6:
        profile = config.setdefault("profile", {})
        for key in ("name", "email", "phone", "portfolio", "home_city"):
            if profile.pop(key, None) is not None:
                changed = True
    filtered_sources = [
        source
        for source in current_sources
        if not (
            isinstance(source, dict)
            and (
                "barona" in fold_text(source.get("name"))
                or "baronacareers.com" in fold_text(source.get("url"))
            )
        )
    ]
    if len(filtered_sources) != len(current_sources):
        current_sources[:] = filtered_sources
        changed = True
    if old_version < CONFIG_VERSION:
        app["config_version"] = CONFIG_VERSION
        changed = True
    return config, changed


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    if not path.exists() and path == CONFIG_PATH and DEFAULT_CONFIG_PATH.exists():
        shutil.copy2(DEFAULT_CONFIG_PATH, path)

    try:
        config = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ValueError(f"Asetustiedostoa ei löytynyt: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"config.json sisältää kirjoitusvirheen rivillä {exc.lineno}, "
            f"sarakkeessa {exc.colno}: {exc.msg}"
        ) from exc

    if path == CONFIG_PATH and DEFAULT_CONFIG_PATH.exists():
        try:
            defaults = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Oletusasetuksia ei voitu lukea: {exc}") from exc
        config, changed = merge_config_defaults(config, defaults)
        if changed:
            backup_file(path, "config_ennen_paivitysta")
            temporary = path.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(config, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(path)

    for key in ("app", "profile", "sources"):
        if key not in config:
            raise ValueError(f"config.json-tiedostosta puuttuu osa: {key}")
    if not isinstance(config["sources"], list):
        raise ValueError("config.json: sources-arvon täytyy olla lista.")
    for index, source in enumerate(config["sources"], start=1):
        if not isinstance(source, dict) or not source.get("name") or not source.get("url"):
            raise ValueError(f"config.json: lähteen {index} nimi tai URL puuttuu.")
        for pattern in source.get("link_patterns", []):
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(
                    f"config.json: lähteen {source['name']} link_patterns sisältää "
                    f"virheen: {exc}"
                ) from exc
    return config


def fold_text(value: Any) -> str:
    text = html.unescape(str(value or "")).lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text).strip()


def clean_space(value: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def source_job_categories(source: dict[str, Any]) -> tuple[str, ...]:
    """Palauta lähteen tehtäväalaryhmät asetusten suodatusta varten."""
    configured = source.get("categories", [])
    if isinstance(configured, str):
        configured = [configured]
    categories = tuple(
        dict.fromkeys(
            clean_space(category)
            for category in configured
            if clean_space(category) in SOURCE_JOB_CATEGORIES
        )
    )
    if categories:
        return categories
    return SOURCE_CATEGORIES_BY_NAME.get(
        clean_space(source.get("name")),
        (SOURCE_FILTER_OTHER,),
    )


REGION_NAME_LOOKUP = {
    fold_text(region): region
    for region in FINLAND_REGIONS
}
MUNICIPALITY_NAME_LOOKUP = {
    fold_text(municipality): municipality
    for municipality in FINLAND_MUNICIPALITIES
}
MUNICIPALITY_TO_REGION = {
    fold_text(municipality): region
    for region, municipalities in FINLAND_REGIONS.items()
    for municipality in municipalities
}
OCCUPATION_NAME_LOOKUP = {
    fold_text(name): name
    for _, name in FINLAND_OCCUPATIONS
}


def normalize_location_choice(value: Any) -> str:
    """Poista valitsimen tyyppimerkintä ja palauta virallinen kirjoitusasu."""
    text = clean_space(value)
    text = re.sub(r"\s+—\s+(?:maakunta|kunta)$", "", text, flags=re.IGNORECASE)
    folded = fold_text(text)
    if folded in {"koko suomi", "suomi"}:
        return "Koko Suomi"
    return (
        REGION_NAME_LOOKUP.get(folded)
        or MUNICIPALITY_NAME_LOOKUP.get(folded)
        or text
    )


def normalize_occupation_choice(value: Any) -> str:
    """Palauta virallinen ammattiluokan nimi tai käyttäjän oma tehtävänimike."""
    text = clean_space(value)
    return OCCUPATION_NAME_LOOKUP.get(fold_text(text), text)


def normalize_excluded_phrase(value: Any) -> str:
    """Siisti käyttäjän kirjoittama poissulkeva ilmaus."""
    return clean_space(value)


def settings_occupation_list(value: Any) -> list[str]:
    raw_items = value if isinstance(value, list) else str(value or "").splitlines()
    return settings_list([
        normalize_occupation_choice(item)
        for item in raw_items
    ])


def role_search_terms(value: Any) -> list[str]:
    """Muodosta ammattiluokan monikkomuodosta käyttökelpoiset hakutermit."""
    role = fold_text(normalize_occupation_choice(value))
    if not role:
        return []
    terms = [role]
    parts = re.split(r"[,;/]|\b(?:ja|seka)\b", role)
    singular_exceptions = {
        "kokit": "kokki",
        "lapset": "lapsi",
        "miehet": "mies",
        "naiset": "nainen",
        "papit": "pappi",
        "tulkit": "tulkki",
    }
    for part in parts:
        clean = re.sub(r"\([^)]*\)", "", part)
        clean = re.sub(r"\bym\.?\b", "", clean)
        clean = re.sub(
            r"^muut(?:\s+muualla\s+luokittelemattomat)?\s+",
            "",
            clean,
        ).strip(" .-")
        if len(clean) < 3:
            continue
        terms.append(clean)
        words = clean.split()
        last = words[-1]
        singular = singular_exceptions.get(last)
        if singular is None and last.endswith("kot") and len(last) > 4:
            singular = last[:-3] + "kko"
        elif singular is None and last.endswith("t") and len(last) > 4:
            singular = last[:-1]
        if singular and singular != last:
            terms.append(" ".join((*words[:-1], singular)))
    return list(dict.fromkeys(term for term in terms if len(term) >= 3))


def role_matches_text(role: Any, text: Any) -> bool:
    haystack = fold_text(text)
    return any(term in haystack for term in role_search_terms(role))


def _normalized_location_phrase(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", fold_text(value)).strip()


def text_contains_location(text: Any, location: Any) -> bool:
    """Tunnista kokonainen paikan nimi ilman Ii-tyyppisiä osumavirheitä."""
    haystack = _normalized_location_phrase(text)
    needle = _normalized_location_phrase(location)
    if not needle:
        return False
    if f" {needle} " in f" {haystack} ":
        return True
    tokens = haystack.split()
    case_endings = {
        "n",
        "a",
        "ta",
        "ssa",
        "sta",
        "seen",
        "lla",
        "lta",
        "lle",
        "na",
        "ksi",
        "in",
        "an",
        "en",
        "ella",
        "elta",
        "elle",
        "essa",
        "esta",
        "issa",
        "ista",
        "illa",
        "ilta",
        "ille",
    }

    def token_matches(stem: str) -> bool:
        return any(
            token == stem
            or (
                token.startswith(stem)
                and token[len(stem) :] in case_endings
            )
            for token in tokens
        )

    if " " in needle:
        parts = needle.split()
        for index in range(0, len(tokens) - len(parts) + 1):
            window = tokens[index : index + len(parts)]
            if window[:-1] != parts[:-1]:
                continue
            if text_contains_location(window[-1], parts[-1]):
                return True
        return False
    if token_matches(needle):
        return True
    stems: list[str] = []
    if needle.endswith("i") and len(needle) >= 5:
        stems.append(needle[:-1] + "e")
    if needle.endswith("hti"):
        stems.append(needle[:-3] + "hd")
    if needle.endswith("nki"):
        stems.append(needle[:-2] + "g")
    if needle.endswith("nko"):
        stems.append(needle[:-2] + "g")
    if needle.endswith("joki"):
        stems.append(needle[:-2] + "e")
    if needle == "turku":
        stems.append("turu")
    return any(token_matches(stem) for stem in dict.fromkeys(stems))


def location_terms(location: Any) -> tuple[str, ...]:
    """Laajenna maakunta kuntiin; oma kirjoitettu sijainti säilyy sellaisenaan."""
    canonical = normalize_location_choice(location)
    folded = fold_text(canonical)
    if canonical == "Koko Suomi":
        return ("Koko Suomi",)
    region = REGION_NAME_LOOKUP.get(folded)
    if region:
        terms: list[str] = [region, *LOCATION_ALIASES.get(region, ())]
        for municipality in FINLAND_REGIONS[region]:
            terms.append(municipality)
            terms.extend(LOCATION_ALIASES.get(municipality, ()))
        return tuple(dict.fromkeys(terms))
    municipality = MUNICIPALITY_NAME_LOOKUP.get(folded)
    if municipality:
        return (
            municipality,
            *LOCATION_ALIASES.get(municipality, ()),
        )
    custom_aliases = CUSTOM_LOCATION_ALIASES.get(folded)
    if custom_aliases:
        return custom_aliases
    return (canonical,) if canonical else ()


def matching_location_choices(
    text: Any,
    choices: Iterable[Any],
) -> list[str]:
    """Palauta valitut kunnat tai maakunnat, joihin työpaikan teksti osuu."""
    matches: list[str] = []
    for raw_choice in choices:
        choice = normalize_location_choice(raw_choice)
        if not choice:
            continue
        if choice == "Koko Suomi" or any(
            text_contains_location(text, term)
            for term in location_terms(choice)
        ):
            matches.append(choice)
    return list(dict.fromkeys(matches))


def detect_finland_locations(text: Any) -> list[str]:
    """Tunnista tekstistä kaikki vuoden 2026 Suomen kunnat tai maakunnat."""
    municipalities = [
        municipality
        for municipality in FINLAND_MUNICIPALITIES
        if any(
            text_contains_location(text, term)
            for term in (
                municipality,
                *LOCATION_ALIASES.get(municipality, ()),
            )
        )
    ]
    if municipalities:
        return municipalities
    return [
        region
        for region in FINLAND_REGIONS
        if any(
            text_contains_location(text, term)
            for term in (region, *LOCATION_ALIASES.get(region, ()))
        )
    ]


def job_matches_location_filter(job: Any, config: dict[str, Any]) -> bool:
    """Rajaa tunnistetut työpaikat valittuihin kuntiin tai maakuntiin.

    Varsinainen sijaintikenttä on ensisijainen. Ilmoituksen kuvaus voi sisältää
    esimerkiksi yrityksen muiden toimipisteiden nimiä, eikä sellainen maininta
    saa päästää väärällä paikkakunnalla olevaa työtä sijaintisuodattimen läpi.
    """
    profile = config.get("profile", {})
    choices = (
        profile.get("preferred_locations", [])
        + profile.get("acceptable_locations", [])
    )
    choices = settings_location_list(choices)
    if not choices or "Koko Suomi" in choices:
        return True

    def field(name: str) -> Any:
        if isinstance(job, Job):
            return getattr(job, name, "")
        try:
            return job[name]
        except (KeyError, IndexError, TypeError):
            return ""

    title_text = clean_space(field("title"))
    location_text = clean_space(field("location"))
    description_text = clean_space(field("description"))
    title_locations = detect_finland_locations(title_text)
    location_locations = detect_finland_locations(location_text)

    # Jotkin HTML-sivut vuotavat sijaintikenttään koko sivun navigaatiosta
    # useita kuntia. Jos tehtävän nimessä on tällöin yksi selkeä paikkakunta,
    # se on luotettavampi kuin pitkä sijaintiluettelo.
    if len(location_locations) > 3 and 0 < len(title_locations) <= 2:
        return bool(matching_location_choices(title_text, choices))

    # Rakenteinen sijainti ratkaisee. Kuvauksessa mainittu Helsinki tai
    # Uusimaa ei näin hyväksy esimerkiksi Kouvolassa olevaa työpaikkaa.
    if location_locations:
        return bool(matching_location_choices(location_text, choices))

    # Käyttäjän oma sijaintinimi, kuten "pääkaupunkiseutu", ei välttämättä
    # kuulu viralliseen kuntaluetteloon mutta voidaan silti tunnistaa.
    if matching_location_choices(location_text, choices):
        return True

    if title_locations:
        return bool(matching_location_choices(title_text, choices))
    if matching_location_choices(title_text, choices):
        return True

    # Kuvausta käytetään vasta viimeisenä varavaihtoehtona, jos ilmoituksella
    # ei ole lainkaan tunnistettavaa sijaintia tai paikkakuntaa nimessä.
    if matching_location_choices(description_text, choices):
        return True
    # Täysin tunnistamaton sijainti jätetään näkyviin käyttäjän tarkistettavaksi.
    return not detect_finland_locations(description_text)


def settings_list(value: Any) -> list[str]:
    """Muunna asetuskentän rivit siistiksi listaksi ilman kaksoiskappaleita."""
    raw_items = value if isinstance(value, list) else str(value or "").splitlines()
    items: list[str] = []
    seen: set[str] = set()
    for raw_item in raw_items:
        item = clean_space(raw_item)
        folded = fold_text(item)
        if not item or folded in seen:
            continue
        items.append(item)
        seen.add(folded)
    return items


def settings_location_list(value: Any) -> list[str]:
    raw_items = value if isinstance(value, list) else str(value or "").splitlines()
    return settings_list([
        normalize_location_choice(item)
        for item in raw_items
    ])


def selectable_choice_matches(
    query: Any,
    choices: Iterable[str],
    limit: int = 100,
) -> list[str]:
    """Palauta kirjoitukseen sopivat valinnat parhaat osumat ensin."""
    folded_query = fold_text(clean_space(query))
    available = list(choices)
    if not folded_query:
        return available[:limit]
    starts_with: list[str] = []
    word_starts_with: list[str] = []
    contains: list[str] = []
    for choice in available:
        folded_choice = fold_text(choice)
        if folded_choice.startswith(folded_query):
            starts_with.append(choice)
        elif any(
            word.startswith(folded_query)
            for word in re.findall(r"[a-zåäö0-9]+", folded_choice)
        ):
            word_starts_with.append(choice)
        elif folded_query in folded_choice:
            contains.append(choice)
    return (starts_with + word_starts_with + contains)[:limit]


def _integer_setting(
    values: dict[str, Any],
    key: str,
    label: str,
    minimum: int,
    maximum: int,
) -> int:
    try:
        value = int(str(values.get(key, "")).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}: anna kokonaisluku.") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{label}: sallitut arvot ovat {minimum}–{maximum}.")
    return value


def update_config_from_settings(
    current: dict[str, Any],
    values: dict[str, Any],
    source_enabled: Iterable[bool],
) -> dict[str, Any]:
    """Rakenna lomakkeen arvoista uusi config muuttamatta teknisiä asetuksia."""
    updated = copy.deepcopy(current)
    profile = updated.setdefault("profile", {})
    app = updated.setdefault("app", {})

    for key in ("preferred_locations", "acceptable_locations"):
        profile[key] = settings_location_list(
            values.get(f"profile.{key}", profile.get(key, []))
        )
    profile["roles"] = settings_occupation_list(
        values.get("profile.roles", profile.get("roles", []))
    )
    for key in ("strengths", "excluded_phrases"):
        profile[key] = settings_list(
            values.get(f"profile.{key}", profile.get(key, []))
        )
    if not profile["roles"]:
        raise ValueError("Kiinnostavia työtehtäviä täytyy olla vähintään yksi.")

    app["minimum_score"] = _integer_setting(
        values,
        "app.minimum_score",
        "Pienin pistemäärä",
        0,
        100,
    )
    app["days_to_show"] = _integer_setting(
        values,
        "app.days_to_show",
        "Näytettävien päivien määrä",
        1,
        3650,
    )
    app["duplicate_window_days"] = _integer_setting(
        values,
        "app.duplicate_window_days",
        "Kaksoiskappaleiden vertailuaika",
        1,
        3650,
    )
    app["request_timeout_seconds"] = _integer_setting(
        values,
        "app.request_timeout_seconds",
        "Verkkopyynnön aikakatkaisu",
        5,
        120,
    )
    app["maximum_details_per_source"] = _integer_setting(
        values,
        "app.maximum_details_per_source",
        "Ilmoituksia lähdettä kohden",
        1,
        500,
    )
    qualifications = values.get(
        "profile.qualifications",
        profile.get("qualifications", {}),
    )
    if not isinstance(qualifications, dict):
        raise ValueError("Pätevyyksien asetuksia ei voitu tulkita.")
    valid_qualification_values = {"yes", "no", "unknown"}
    normalized_qualifications: dict[str, str] = {}
    for name, state in qualifications.items():
        if state not in valid_qualification_values:
            raise ValueError(f"Pätevyyden {name} tila ei ole kelvollinen.")
        normalized_qualifications[clean_space(name)] = state
    profile["qualifications"] = normalized_qualifications

    enabled_values = list(source_enabled)
    sources = updated.get("sources", [])
    if len(enabled_values) != len(sources):
        raise ValueError("Työpaikkalähteiden asetuksia ei voitu tallentaa.")
    for source, enabled in zip(sources, enabled_values):
        source["enabled"] = bool(enabled)
    return updated


def write_config_file(
    config: dict[str, Any],
    path: Path = CONFIG_PATH,
) -> Path:
    """Tallenna config atomisesti ja tee vanhasta tiedostosta varmuuskopio."""
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_file(path, "config_ennen_asetusmuutosta")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def canonical_url(value: Any) -> str:
    """Poistaa URL:stä seuranta-arvot, jotka eivät muuta itse ilmoitusta."""
    raw = clean_space(value)
    if not raw:
        return ""
    parsed = urllib.parse.urlsplit(raw)
    query = []
    for key, item in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        folded_key = fold_text(key)
        if folded_key.startswith("utm_") or folded_key in TRACKING_QUERY_KEYS:
            continue
        query.append((key, item))
    path = re.sub(r"/+$", "", parsed.path) or "/"
    return urllib.parse.urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            urllib.parse.urlencode(query, doseq=True),
            "",
        )
    )


def canonical_company(value: Any) -> str:
    company = fold_text(value).replace("&", " ja ")
    company = re.sub(r"[^a-z0-9]+", " ", company)
    company = re.sub(
        r"\b(?:oyj?|ab|ltd|limited|finland|suomi|rekrytointi)\b", " ", company
    )
    company = clean_space(company)
    aliases = {
        "l t": "lassila ja tikanoja",
        "lassila tikanoja": "lassila ja tikanoja",
        "iss palvelut": "iss",
        "posti group": "posti",
        "workpower palvelut": "workpower",
        "workpower teollisuus": "workpower",
    }
    return aliases.get(company, company)


def canonical_location(value: Any) -> str:
    folded = fold_text(value)
    municipalities = [
        fold_text(location)
        for location in detect_finland_locations(value)
        if fold_text(location) in MUNICIPALITY_NAME_LOOKUP
    ]
    if municipalities:
        return "|".join(sorted(set(municipalities)))
    if "paakaupunkiseutu" in folded or "helsinki metropolitan area" in folded:
        return "paakaupunkiseutu"
    regions = [
        fold_text(region)
        for region in FINLAND_REGIONS
        if text_contains_location(value, region)
    ]
    if regions:
        return "|".join(sorted(set(regions)))
    return re.sub(r"[^a-z0-9]+", " ", folded).strip()


def canonical_title(value: Any) -> str:
    title = fold_text(value)
    title = re.sub(r"[\U00010000-\U0010ffff]", " ", title)
    location_forms: list[str] = []
    for location in detect_finland_locations(value):
        place = fold_text(location)
        location_forms.extend((place, place + "lle", place + "seen"))
    location_forms.extend(("paakaupunkiseutu", "helsinki metropolitan area"))
    for place in sorted(location_forms, key=len, reverse=True):
        title = re.sub(rf"\b{re.escape(place)}\b", " ", title)
    title = re.sub(r"\b(?:m|f|d)\b", " ", title)
    return re.sub(r"[^a-z0-9]+", " ", title).strip()


def source_link(source: Any, url: Any) -> dict[str, str]:
    return {"source": clean_space(source), "url": canonical_url(url)}


def merge_source_links(*groups: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            url = canonical_url(item.get("url"))
            if not url or url in seen:
                continue
            merged.append(source_link(item.get("source"), url))
            seen.add(url)
    return merged


def is_aggregator_source(value: Any) -> bool:
    source = fold_text(value)
    return any(source.startswith(prefix) for prefix in AGGREGATOR_SOURCE_PREFIXES)


def parse_job_date(value: Any) -> datetime | None:
    text = clean_space(value)
    if not text:
        return None
    match = re.search(r"\d{4}-\d{2}-\d{2}", text)
    if match:
        try:
            return datetime.strptime(match.group(0), "%Y-%m-%d")
        except ValueError:
            pass
    match = re.search(r"\d{1,2}[./]\d{1,2}[./]\d{2,4}", text)
    if match:
        for pattern in ("%d.%m.%Y", "%d.%m.%y", "%d/%m/%Y", "%d/%m/%y"):
            try:
                return datetime.strptime(match.group(0), pattern)
            except ValueError:
                continue
    return None


def format_job_date(value: Any) -> str:
    """Muotoile ilmoituksen päivämäärä ilman tarpeetonta kellonaikaa."""
    parsed = parse_job_date(value)
    return parsed.strftime("%d.%m.%Y") if parsed is not None else ""


def sort_jobs_by_deadline(
    rows: Iterable[Any],
    latest_first: bool,
) -> list[Any]:
    """Lajittele tulkittavat hakuajat ja jätä puuttuvat määräpäivät loppuun."""
    dated: list[tuple[datetime, Any]] = []
    missing: list[Any] = []
    for row in rows:
        deadline = parse_job_date(row["deadline"])
        if deadline is None:
            missing.append(row)
        else:
            dated.append((deadline, row))
    dated.sort(key=lambda item: item[0], reverse=latest_first)
    return [row for _, row in dated] + missing


def sort_jobs_by_score(
    rows: Iterable[Any],
    highest_first: bool,
) -> list[Any]:
    """Lajittele työpaikat pisteiden mukaan rikkomatta tasapisteiden järjestystä."""
    return sorted(
        rows,
        key=lambda row: int(row["score"] or 0),
        reverse=highest_first,
    )


def deadline_has_passed(value: Any, now: datetime | None = None) -> bool:
    """Palauttaa toden vain, kun ilmoituksen määräpäivä voidaan varmasti tulkita."""
    deadline = parse_job_date(value)
    if deadline is None:
        return False
    current = now or datetime.now()
    return deadline.date() < current.date()


def listing_dates_compatible(first: "Job", second: "Job") -> bool:
    first_published = parse_job_date(first.published)
    second_published = parse_job_date(second.published)
    if first_published and second_published:
        if abs((first_published - second_published).days) > 14:
            return False
    first_deadline = parse_job_date(first.deadline)
    second_deadline = parse_job_date(second.deadline)
    if first_deadline and second_deadline:
        if abs((first_deadline - second_deadline).days) > 14:
            return False
    return True


def listing_has_reopened(
    previous: "Job",
    current: "Job",
    now: datetime | None = None,
) -> bool:
    """Tunnistaa varmasti uuden hakuajan aiemmin päättyneelle ilmoitukselle."""
    previous_deadline = parse_job_date(previous.deadline)
    current_deadline = parse_job_date(current.deadline)
    if previous_deadline is None or current_deadline is None:
        return False
    today = (now or datetime.now()).date()
    return (
        previous_deadline.date() < today
        and current_deadline.date() >= today
        and current_deadline.date() > previous_deadline.date()
    )


def newer_job_date(previous: Any, current: Any) -> str:
    """Palauttaa myöhemmän päivämäärän alkuperäisessä tekstimuodossaan."""
    previous_text = clean_space(previous)
    current_text = clean_space(current)
    previous_date = parse_job_date(previous_text)
    current_date = parse_job_date(current_text)
    if current_date and (previous_date is None or current_date > previous_date):
        return current_text
    return previous_text or current_text


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self.hidden_depth:
            self.hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth and data.strip():
            self.parts.append(data)

    def text(self) -> str:
        return clean_space(" ".join(self.parts))


def strip_html(value: Any) -> str:
    parser = TextExtractor()
    try:
        parser.feed(str(value or ""))
        return parser.text()
    except Exception:
        return clean_space(re.sub(r"<[^>]+>", " ", str(value or "")))


class PageParser(HTMLParser):
    """Kerää tavallisesta sivusta linkit, otsikot, tekstin ja JSON-LD:n."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[dict[str, str]] = []
        self.text_parts: list[str] = []
        self.title_parts: list[str] = []
        self.h1_parts: list[str] = []
        self.meta_description = ""
        self.jsonld_blocks: list[str] = []
        self._anchor: dict[str, Any] | None = None
        self._in_title = 0
        self._in_h1 = 0
        self._hidden_depth = 0
        self._jsonld_depth = 0
        self._jsonld_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key.lower(): (value or "") for key, value in attrs}
        tag = tag.lower()

        if tag == "a":
            self._anchor = {
                "href": attrs_dict.get("href", ""),
                "parts": [],
                "before": " ".join(self.text_parts[-8:]),
            }
        elif tag == "title":
            self._in_title += 1
        elif tag == "h1":
            self._in_h1 += 1
        elif tag == "meta":
            name = (
                attrs_dict.get("name") or attrs_dict.get("property") or ""
            ).lower()
            if name in {"description", "og:description"} and not self.meta_description:
                self.meta_description = attrs_dict.get("content", "")
        elif tag == "script":
            script_type = attrs_dict.get("type", "").lower()
            if "ld+json" in script_type:
                self._jsonld_depth += 1
                self._jsonld_parts = []
            else:
                self._hidden_depth += 1
        elif tag in {"style", "noscript", "svg"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "a" and self._anchor is not None:
            self.anchors.append(
                {
                    "href": self._anchor["href"],
                    "text": clean_space(" ".join(self._anchor["parts"])),
                    "context": clean_space(self._anchor["before"]),
                }
            )
            self._anchor = None
        elif tag == "title" and self._in_title:
            self._in_title -= 1
        elif tag == "h1" and self._in_h1:
            self._in_h1 -= 1
        elif tag == "script":
            if self._jsonld_depth:
                self.jsonld_blocks.append("".join(self._jsonld_parts))
                self._jsonld_parts = []
                self._jsonld_depth -= 1
            elif self._hidden_depth:
                self._hidden_depth -= 1
        elif tag in {"style", "noscript", "svg"} and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._jsonld_depth:
            self._jsonld_parts.append(data)
            return
        if self._hidden_depth or not data.strip():
            return
        self.text_parts.append(data)
        if self._anchor is not None:
            self._anchor["parts"].append(data)
        if self._in_title:
            self.title_parts.append(data)
        if self._in_h1:
            self.h1_parts.append(data)

    @property
    def title(self) -> str:
        return clean_space(" ".join(self.title_parts))

    @property
    def h1(self) -> str:
        return clean_space(" ".join(self.h1_parts))

    @property
    def text(self) -> str:
        return clean_space(" ".join(self.text_parts))


def parse_page(raw_html: str) -> PageParser:
    parser = PageParser()
    parser.feed(raw_html)
    return parser


@dataclass
class Job:
    title: str
    company: str
    location: str
    url: str
    source: str
    description: str = ""
    deadline: str = ""
    published: str = ""
    score: int = 0
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    matched_roles: list[str] = field(default_factory=list)
    links: list[dict[str, str]] = field(default_factory=list)
    is_new: bool = False

    @property
    def fingerprint(self) -> str:
        base = canonical_url(self.url)
        if not base:
            base = f"{self.company}|{self.title}|{self.location}".lower()
        return hashlib.sha256(base.encode("utf-8")).hexdigest()[:32]

    @property
    def canonical_key(self) -> str:
        base = "|".join(
            (
                canonical_company(self.company),
                canonical_title(self.title),
                canonical_location(f"{self.location} {self.title}"),
            )
        )
        return hashlib.sha256(base.encode("utf-8")).hexdigest()[:32]

    def source_links(self) -> list[dict[str, str]]:
        return merge_source_links(
            [source_link(self.source, self.url)],
            self.links,
        )


def iter_json_objects(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from iter_json_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_json_objects(child)


def jsonld_job_objects(parser: PageParser) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for block in parser.jsonld_blocks:
        block = block.strip()
        if not block:
            continue
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            # Jotkin sivut sisältävät peräkkäisiä objekteja tai lopussa puolipisteen.
            try:
                payload = json.loads(block.rstrip(";"))
            except json.JSONDecodeError:
                continue
        for obj in iter_json_objects(payload):
            kind = obj.get("@type", "")
            kinds = kind if isinstance(kind, list) else [kind]
            if any(str(item).lower() == "jobposting" for item in kinds):
                found.append(obj)
    return found


def location_from_jsonld(value: Any) -> str:
    locations: list[str] = []
    values = value if isinstance(value, list) else [value]
    for item in values:
        if isinstance(item, str):
            locations.append(item)
            continue
        if not isinstance(item, dict):
            continue
        address = item.get("address", item)
        if isinstance(address, str):
            locations.append(address)
            continue
        if isinstance(address, dict):
            parts = [
                address.get("addressLocality"),
                address.get("addressRegion"),
                address.get("addressCountry"),
            ]
            joined = ", ".join(clean_space(part) for part in parts if clean_space(part))
            if joined:
                locations.append(joined)
        if item.get("name"):
            locations.append(clean_space(item["name"]))
    return " / ".join(dict.fromkeys(filter(None, locations)))


def job_from_jsonld(obj: dict[str, Any], source: dict[str, Any], base_url: str) -> Job:
    organization = obj.get("hiringOrganization") or {}
    if isinstance(organization, dict):
        company = clean_space(organization.get("name"))
    else:
        company = clean_space(organization)
    company = company or source["name"]
    url = clean_space(obj.get("url")) or base_url
    url = urllib.parse.urljoin(base_url, url)
    return Job(
        title=clean_space(obj.get("title") or obj.get("name") or "Nimetön työpaikka"),
        company=company,
        location=location_from_jsonld(obj.get("jobLocation")),
        url=url,
        source=source["name"],
        description=strip_html(obj.get("description") or obj.get("responsibilities") or ""),
        deadline=clean_space(obj.get("validThrough")),
        published=clean_space(obj.get("datePosted")),
    )


class HttpClient:
    def __init__(self, timeout: int = 25) -> None:
        self.timeout = timeout
        self.context = ssl.create_default_context()
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/124 Safari/537.36 "
                f"Tyopaikkatutka/{APP_VERSION}"
            ),
            # Workday hyväksyy tästä vain yhden locale-arvon. Tavallinen
            # selainten pilkuilla eroteltu kielilista aiheuttaa HTTP 400:n.
            "Accept-Language": "fi-FI",
        }

    def request(
        self,
        url: str,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[bytes, str, dict[str, str]]:
        data = None
        headers = dict(self.headers)
        if extra_headers:
            headers.update(extra_headers)
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
            headers["Accept"] = "application/json"
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout, context=self.context
            ) as response:
                body = response.read()
                final_url = response.geturl()
                response_headers = {key.lower(): value for key, value in response.headers.items()}
                return body, final_url, response_headers
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read(800).decode("utf-8", errors="replace")
            except Exception:
                pass
            if exc.code == 403 and (
                "just a moment" in fold_text(detail)
                or "cloudflare" in fold_text(detail)
                or "enable javascript and cookies" in fold_text(detail)
            ):
                raise SourceBlockedError(
                    "sivusto vaatii selaimen Cloudflare-tarkistuksen; "
                    "automaattinen tarkistus ohitettiin"
                ) from exc
            raise RuntimeError(f"HTTP {exc.code}: {url} {detail}".strip()) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Yhteys epäonnistui: {url} ({exc.reason})") from exc

    def get_text(self, url: str) -> tuple[str, str]:
        body, final_url, headers = self.request(url)
        if "botchallenge" in fold_text(final_url):
            raise SourceBlockedError(
                "sivusto vaatii selaimen bottitarkistuksen; automaattinen tarkistus ohitettiin"
            )
        content_type = headers.get("content-type", "")
        charset_match = re.search(r"charset=([A-Za-z0-9._-]+)", content_type)
        encoding = charset_match.group(1) if charset_match else "utf-8"
        try:
            return body.decode(encoding, errors="replace"), final_url
        except LookupError:
            return body.decode("utf-8", errors="replace"), final_url

    def get_json(self, url: str) -> Any:
        body, _, _ = self.request(url, extra_headers={"Accept": "application/json"})
        return json.loads(body.decode("utf-8-sig"))

    def post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        body, _, _ = self.request(url, method="POST", payload=payload)
        return json.loads(body.decode("utf-8-sig"))


def find_location(text: str, config: dict[str, Any]) -> str:
    del config
    return ", ".join(detect_finland_locations(text))


def find_deadline(text: str) -> str:
    patterns = [
        r"(?:haku(?:aika)? (?:päättyy|paattyy)|hae viimeistään|hae viimeistaan)\s*:?\s*"
        r"(\d{1,2}[./]\d{1,2}[./]\d{2,4})",
        r"(?:haku(?:aika)? (?:päättyy|paattyy)|hae viimeistään|hae viimeistaan)\s*:?\s*"
        r"(\d{4}-\d{2}-\d{2})",
        r"(?:valid through|application deadline)\s*:?\s*(\d{4}-\d{2}-\d{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, fold_text(text), re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def detail_job(
    client: HttpClient,
    url: str,
    source: dict[str, Any],
    fallback_title: str,
    config: dict[str, Any],
) -> Job:
    raw_html, final_url = client.get_text(url)
    parser = parse_page(raw_html)
    objects = jsonld_job_objects(parser)
    if objects:
        job = job_from_jsonld(objects[0], source, final_url)
        if not job.title or job.title == "Nimetön työpaikka":
            job.title = fallback_title
        return job

    page_text = parser.text[:20000]
    title = parser.h1 or fallback_title or parser.title
    if len(title) > 180 or fold_text(title) in {"jobs", "avoimet tyopaikat"}:
        title = fallback_title
    description = parser.meta_description
    if len(page_text) > len(description):
        description = page_text
    return Job(
        title=clean_space(title) or "Nimetön työpaikka",
        company=source["name"],
        location=find_location(page_text, config),
        url=final_url,
        source=source["name"],
        description=description,
        deadline=find_deadline(page_text),
    )


def html_source_jobs(
    client: HttpClient,
    source: dict[str, Any],
    config: dict[str, Any],
    progress: Callable[[str], None],
) -> list[Job]:
    patterns = [re.compile(pattern, re.IGNORECASE) for pattern in source.get("link_patterns", [])]
    excludes = [fold_text(item) for item in source.get("exclude_titles", [])]
    candidates: dict[str, tuple[str, str]] = {}
    jobs: list[Job] = []
    listing_urls = list(
        dict.fromkeys(
            [source["url"]]
            + [
                clean_space(url)
                for url in source.get("urls", [])
                if clean_space(url)
            ]
        )
    )
    listing_errors: list[str] = []
    listing_exceptions: list[Exception] = []

    for listing_url in listing_urls:
        try:
            raw_html, final_url = client.get_text(listing_url)
        except Exception as exc:
            listing_errors.append(f"{listing_url}: {exc}")
            listing_exceptions.append(exc)
            continue
        parser = parse_page(raw_html)
        jobs.extend(
            job_from_jsonld(obj, source, final_url)
            for obj in jsonld_job_objects(parser)
        )

        for anchor in parser.anchors:
            href = anchor.get("href", "").strip()
            title = clean_space(anchor.get("text"))
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            absolute = urllib.parse.urljoin(final_url, href)
            folded_title = fold_text(title)
            if any(excluded in folded_title for excluded in excludes):
                continue
            explicit_match = any(pattern.search(absolute) for pattern in patterns)
            ats_match = any(
                domain in urllib.parse.urlparse(absolute).netloc
                for domain in ATS_DOMAINS
            )
            if not (explicit_match or ats_match):
                continue
            if len(title) < 3:
                continue
            candidates.setdefault(
                canonical_url(absolute),
                (title, anchor.get("context", "")),
            )

    if listing_errors and len(listing_errors) == len(listing_urls):
        if all(isinstance(exc, SourceBlockedError) for exc in listing_exceptions):
            raise SourceBlockedError(str(listing_exceptions[0]))
        raise RuntimeError("; ".join(listing_errors))
    for message in listing_errors:
        logging.warning("%s: listasivun avaaminen epäonnistui: %s", source["name"], message)

    # Haun kannalta kiinnostavat otsikot ensin, jotta detaljiraja ei huku
    # asiantuntijatehtäviin.
    roles = config["profile"].get("roles", [])

    def priority(item: tuple[str, tuple[str, str]]) -> tuple[int, str]:
        title = fold_text(item[1][0])
        return (
            0 if any(role_matches_text(role, title) for role in roles) else 1,
            title,
        )

    max_details = int(config["app"].get("maximum_details_per_source", 35))
    known_urls = {canonical_url(job.url) for job in jobs}
    for index, (url, (title, context)) in enumerate(sorted(candidates.items(), key=priority)):
        if canonical_url(url) in known_urls:
            continue
        if index < max_details:
            try:
                job = detail_job(client, url, source, title, config)
            except Exception as exc:
                if "HTTP 404" in str(exc) or "HTTP 410" in str(exc):
                    logging.info("%s: poistunut ilmoitus ohitettiin: %s", source["name"], url)
                    continue
                logging.warning("%s: ilmoituksen avaaminen epäonnistui: %s", source["name"], exc)
                job = Job(
                    title=title,
                    company=source["name"],
                    location=find_location(context, config),
                    url=url,
                    source=source["name"],
                    description=context,
                    deadline=find_deadline(context),
                )
        else:
            job = Job(
                title=title,
                company=source["name"],
                location=find_location(context, config),
                url=url,
                source=source["name"],
                description=context,
                deadline=find_deadline(context),
            )
        jobs.append(job)

    progress(f"{source['name']}: löytyi {len(jobs)} ilmoitusta")
    return deduplicate_jobs(jobs)


EEZY_JOBS_QUERY = """
query EEZY_JOBS($from: Float, $to: Float, $locations: [String!]!) {
  elasticJobs(
    filter: {
      searchStringArr: []
      locations: $locations
      isTraining: false
      from: $from
      to: $to
      tags: []
      fieldOfWorks: []
    }
  ) {
    pageResults {
      available
      from
      to
    }
    jobs {
      id
      name
      customer
      customerDescription
      hideCustomer
      descriptionPlain
      endTime
      startTime
      fieldOfWorks
      workLocations {
        name
      }
    }
  }
}
"""


def eezy_source_jobs(
    client: HttpClient,
    source: dict[str, Any],
    config: dict[str, Any],
    progress: Callable[[str], None],
) -> list[Job]:
    """Hae Eezyn avoimet paikat sen oman työpaikkasivun rajapinnasta."""
    del config
    api_url = clean_space(source.get("api_url"))
    if not api_url:
        raise RuntimeError("Eezy-lähteeltä puuttuu api_url.")

    try:
        maximum_jobs = max(1, min(int(source.get("maximum_api_jobs", 500)), 1000))
        page_size = max(1, min(int(source.get("api_page_size", 100)), 200))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Eezy-lähteen rajapintaraja ei ole numero.") from exc

    excludes = [fold_text(item) for item in source.get("exclude_titles", [])]
    jobs: list[Job] = []
    offset = 0
    available = maximum_jobs

    while offset < min(available, maximum_jobs):
        page_end = min(offset + page_size, maximum_jobs)
        response = client.post_json(
            api_url,
            {
                "query": EEZY_JOBS_QUERY,
                "variables": {
                    "from": offset,
                    "to": page_end,
                    "locations": [],
                },
            },
        )
        if response.get("errors"):
            messages = [
                clean_space(item.get("message"))
                for item in response["errors"]
                if isinstance(item, dict) and clean_space(item.get("message"))
            ]
            raise RuntimeError(
                "Eezyn työpaikkahaku palautti virheen"
                + (f": {'; '.join(messages)}" if messages else ".")
            )

        elastic_jobs = (
            response.get("data", {}).get("elasticJobs")
            if isinstance(response.get("data"), dict)
            else None
        )
        if not isinstance(elastic_jobs, dict):
            raise RuntimeError("Eezyn työpaikkahaun vastaus oli odottamaton.")

        page_results = elastic_jobs.get("pageResults")
        if isinstance(page_results, dict):
            try:
                available = max(0, int(page_results.get("available", 0)))
            except (TypeError, ValueError):
                available = maximum_jobs

        items = elastic_jobs.get("jobs")
        if not isinstance(items, list):
            raise RuntimeError("Eezyn työpaikkahaun vastauksesta puuttui jobs-lista.")

        for item in items:
            if not isinstance(item, dict):
                continue
            job_id = clean_space(item.get("id"))
            title = clean_space(item.get("name"))
            if not job_id or not title:
                continue
            folded_title = fold_text(title)
            if any(excluded in folded_title for excluded in excludes):
                continue

            locations: list[str] = []
            for location in item.get("workLocations") or []:
                if isinstance(location, dict):
                    name = clean_space(location.get("name"))
                else:
                    name = clean_space(location)
                if name and name not in locations:
                    locations.append(name)

            fields = [
                clean_space(value)
                for value in item.get("fieldOfWorks") or []
                if clean_space(value)
            ]
            description = strip_html(
                item.get("descriptionPlain")
                or item.get("customerDescription")
                or " ".join(fields)
            )
            company = (
                source["name"]
                if item.get("hideCustomer")
                else clean_space(item.get("customer")) or source["name"]
            )
            jobs.append(
                Job(
                    title=title,
                    company=company,
                    location=", ".join(locations),
                    url=urllib.parse.urljoin(
                        source["url"],
                        f"/tyopaikat/{urllib.parse.quote(job_id, safe='')}",
                    ),
                    source=source["name"],
                    description=description,
                    deadline=clean_space(item.get("endTime")),
                    published=clean_space(item.get("startTime")),
                )
            )

        if not items or page_end >= available:
            break
        offset = page_end

    progress(f"{source['name']}: löytyi {len(jobs)} ilmoitusta")
    return deduplicate_jobs(jobs)


def parse_sitemap(raw_xml: str, base_url: str) -> tuple[list[tuple[str, str]], bool]:
    """Lukee URL:t XML-sivustokartasta ja tunnistaa mahdollisen karttaindeksin."""
    try:
        root = ET.fromstring(raw_xml.lstrip("\ufeff \t\r\n"))
    except ET.ParseError as exc:
        raise RuntimeError(f"Sivustokartta ei ollut kelvollista XML:ää: {exc}") from exc

    root_name = root.tag.rsplit("}", 1)[-1].lower()
    entries: list[tuple[str, str]] = []
    for item in root:
        location = ""
        last_modified = ""
        for child in item:
            name = child.tag.rsplit("}", 1)[-1].lower()
            if name == "loc":
                location = clean_space(child.text)
            elif name == "lastmod":
                last_modified = clean_space(child.text)
        if location:
            entries.append((urllib.parse.urljoin(base_url, location), last_modified))
    return entries, root_name == "sitemapindex"


def sitemap_source_jobs(
    client: HttpClient,
    source: dict[str, Any],
    config: dict[str, Any],
    progress: Callable[[str], None],
) -> list[Job]:
    """Hakee JS-listasivujen julkiset ilmoitusosoitteet XML-sivustokartoista."""
    # Monet sivustot tarjoavat samalla tavallisen HTML-listan. Se on nopeampi
    # ja sisältää vain avoimet paikat, joten käytetään sitä ensisijaisesti.
    html_error: Exception | None = None
    try:
        listed_jobs = html_source_jobs(client, source, config, lambda message: None)
        if listed_jobs:
            progress(f"{source['name']}: löytyi {len(listed_jobs)} ilmoitusta")
            return listed_jobs
    except Exception as exc:
        html_error = exc
        logging.info("%s: HTML-lista ei ollut käytettävissä: %s", source["name"], exc)

    patterns = [
        re.compile(pattern, re.IGNORECASE)
        for pattern in source.get("link_patterns", [])
    ]
    if not patterns:
        raise RuntimeError("Sivustokarttalähteeltä puuttuu link_patterns.")
    excludes = [fold_text(item) for item in source.get("exclude_titles", [])]
    initial_maps = [
        clean_space(item)
        for item in (
            source.get("sitemap_urls")
            or ([source.get("sitemap_url")] if source.get("sitemap_url") else [])
        )
        if clean_space(item)
    ]
    if not initial_maps:
        raise RuntimeError("Sivustokarttalähteeltä puuttuu sitemap_url.")

    queued: list[tuple[str, int]] = [(url, 0) for url in initial_maps]
    visited_maps: set[str] = set()
    candidates: dict[str, str] = {}
    map_errors: list[str] = []
    max_maps = int(source.get("maximum_sitemap_files", 30))

    while queued and len(visited_maps) < max_maps:
        map_url, depth = queued.pop(0)
        canonical_map = canonical_url(map_url)
        if canonical_map in visited_maps:
            continue
        visited_maps.add(canonical_map)
        try:
            raw_xml, final_url = client.get_text(map_url)
            entries, is_index = parse_sitemap(raw_xml, final_url)
        except Exception as exc:
            map_errors.append(f"{map_url}: {exc}")
            continue
        if is_index and depth < 2:
            for child_url, _ in entries:
                if canonical_url(child_url) not in visited_maps:
                    queued.append((child_url, depth + 1))
            continue
        for job_url, last_modified in entries:
            if any(pattern.search(job_url) for pattern in patterns):
                candidates[canonical_url(job_url)] = last_modified

    if not candidates:
        details = "; ".join(map_errors[:3])
        if html_error:
            details = f"HTML-lista: {html_error}; {details}".strip("; ")
        raise RuntimeError(
            "Sivustokartoista ei löytynyt ilmoitusosoitteita"
            + (f": {details}" if details else ".")
        )

    roles = config["profile"].get("roles", [])

    def candidate_priority(item: tuple[str, str]) -> tuple[int, int, str]:
        url, last_modified = item
        slug = fold_text(urllib.parse.urlparse(url).path.replace("-", " "))
        role_rank = (
            0 if any(role_matches_text(role, slug) for role in roles) else 1
        )
        parsed_date = parse_job_date(last_modified)
        newest_first = -(parsed_date.toordinal() if parsed_date else 0)
        return (role_rank, newest_first, url)

    app_limit = int(config["app"].get("maximum_details_per_source", 80))
    source_limit = int(source.get("maximum_sitemap_details", app_limit))
    detail_limit = min(app_limit, source_limit)
    jobs: list[Job] = []
    for url, last_modified in sorted(candidates.items(), key=candidate_priority)[
        :detail_limit
    ]:
        fallback_title = clean_space(
            urllib.parse.unquote(urllib.parse.urlparse(url).path)
            .rstrip("/")
            .rsplit("/", 1)[-1]
            .replace("-", " ")
        )
        try:
            job = detail_job(client, url, source, fallback_title, config)
        except Exception as exc:
            logging.warning("%s: ilmoituksen avaaminen epäonnistui: %s", source["name"], exc)
            continue
        if not job.published:
            job.published = last_modified
        folded_title = fold_text(job.title)
        if any(excluded in folded_title for excluded in excludes):
            continue
        jobs.append(job)

    progress(f"{source['name']}: löytyi {len(jobs)} ilmoitusta")
    return deduplicate_jobs(jobs)


def xml_local_name(tag: Any) -> str:
    return clean_space(tag).rsplit("}", 1)[-1].lower()


def feed_value(element: ET.Element, names: Iterable[str]) -> str:
    wanted = {fold_text(name) for name in names}
    for child in element.iter():
        if xml_local_name(child.tag) not in wanted:
            continue
        value = clean_space(child.text)
        if value:
            return value
    return ""


def feed_link(element: ET.Element, base_url: str) -> str:
    for child in element.iter():
        if xml_local_name(child.tag) != "link":
            continue
        value = clean_space(child.attrib.get("href") or child.text)
        if value:
            return urllib.parse.urljoin(base_url, value)
    guid = feed_value(element, ("guid", "id"))
    if guid.startswith(("http://", "https://")):
        return guid
    return ""


def parse_job_feed(
    raw_xml: str,
    final_url: str,
    source: dict[str, Any],
    config: dict[str, Any],
) -> list[Job]:
    """Muuttaa tavallisen RSS-, Atom- tai työpaikka-XML-syötteen ilmoituksiksi."""
    try:
        root = ET.fromstring(raw_xml.lstrip("\ufeff \t\r\n"))
    except ET.ParseError as exc:
        raise RuntimeError(f"Työpaikkasyöte ei ollut kelvollista XML:ää: {exc}") from exc

    entries = [
        item
        for item in root.iter()
        if xml_local_name(item.tag) in {"item", "entry", "job", "vacancy"}
    ]
    excludes = [fold_text(item) for item in source.get("exclude_titles", [])]
    patterns = [
        re.compile(pattern, re.IGNORECASE)
        for pattern in source.get("link_patterns", [])
    ]
    jobs: list[Job] = []

    for entry in entries:
        title = feed_value(entry, ("title", "jobtitle", "positiontitle", "name"))
        url = canonical_url(feed_link(entry, final_url))
        if not title or not url:
            continue
        if patterns and not any(pattern.search(url) for pattern in patterns):
            continue
        if any(excluded in fold_text(title) for excluded in excludes):
            continue

        description = strip_html(
            feed_value(
                entry,
                (
                    "description",
                    "summary",
                    "content",
                    "jobdescription",
                ),
            )
        )
        company = feed_value(
            entry,
            (
                "company",
                "employer",
                "organization",
                "organisation",
                "hiringorganization",
                "author",
            ),
        )
        location = feed_value(
            entry,
            (
                "location",
                "city",
                "municipality",
                "worklocation",
                "joblocation",
            ),
        )
        location = location or find_location(f"{title} {description}", config)
        deadline = feed_value(
            entry,
            (
                "validthrough",
                "deadline",
                "enddate",
                "expirationdate",
                "applicationdeadline",
            ),
        )
        deadline = deadline or find_deadline(description)
        published = feed_value(
            entry,
            (
                "pubdate",
                "published",
                "updated",
                "dateposted",
                "publish_from",
            ),
        )
        jobs.append(
            Job(
                title=title,
                company=company or source["name"],
                location=location,
                url=url,
                source=source["name"],
                description=description,
                deadline=deadline,
                published=published,
            )
        )
    return deduplicate_jobs(jobs)


def feed_source_jobs(
    client: HttpClient,
    source: dict[str, Any],
    config: dict[str, Any],
    progress: Callable[[str], None],
) -> list[Job]:
    """Hakee työpaikkoja palvelun omista julkisista RSS/XML-syötteistä."""
    feed_urls = [
        clean_space(url)
        for url in source.get("feed_urls", [])
        if clean_space(url)
    ]
    if not feed_urls:
        separator = "&" if "?" in source["url"] else "?"
        feed_urls = [source["url"] + separator + "format=rss"]

    jobs: list[Job] = []
    errors: list[str] = []
    successful_feeds = 0
    for feed_url in dict.fromkeys(feed_urls):
        try:
            raw_xml, final_url = client.get_text(feed_url)
            jobs.extend(parse_job_feed(raw_xml, final_url, source, config))
            successful_feeds += 1
        except Exception as exc:
            errors.append(f"{feed_url}: {exc}")

    if not successful_feeds:
        raise RuntimeError(
            "Julkisten työpaikkasyötteiden avaaminen epäonnistui: "
            + "; ".join(errors)
        )
    for message in errors:
        logging.warning("%s: työpaikkasyötteen avaaminen epäonnistui: %s", source["name"], message)

    candidates = deduplicate_jobs(jobs)
    roles = config["profile"].get("roles", [])
    locations = (
        config["profile"].get("preferred_locations", [])
        + config["profile"].get("acceptable_locations", [])
    )

    def priority(job: Job) -> tuple[int, int, str]:
        title = fold_text(job.title)
        full_text = fold_text(f"{job.title} {job.location} {job.description}")
        role_rank = (
            0 if any(role_matches_text(role, title) for role in roles) else 1
        )
        location_rank = (
            0 if matching_location_choices(full_text, locations) else 1
        )
        return (role_rank, location_rank, title)

    maximum_details = int(config["app"].get("maximum_details_per_source", 80))
    detailed_jobs: list[Job] = []
    for index, base_job in enumerate(sorted(candidates, key=priority)):
        job = base_job
        if index < maximum_details:
            try:
                job = detail_job(
                    client,
                    base_job.url,
                    source,
                    base_job.title,
                    config,
                )
                if job.company == source["name"] and base_job.company != source["name"]:
                    job.company = base_job.company
                job.location = job.location or base_job.location
                job.description = job.description or base_job.description
                job.deadline = job.deadline or base_job.deadline
                job.published = job.published or base_job.published
            except Exception as exc:
                if "HTTP 404" in str(exc) or "HTTP 410" in str(exc):
                    continue
                logging.warning(
                    "%s: syötteen ilmoituksen avaaminen epäonnistui: %s",
                    source["name"],
                    exc,
                )
        detailed_jobs.append(job)

    result = deduplicate_jobs(detailed_jobs)
    progress(f"{source['name']}: löytyi {len(result)} ilmoitusta")
    return result


def wordpress_source_jobs(
    client: HttpClient,
    source: dict[str, Any],
    config: dict[str, Any],
    progress: Callable[[str], None],
) -> list[Job]:
    """Hakee julkiset työpaikat WordPressin omasta REST-rajapinnasta."""
    endpoint = clean_space(source.get("api_url"))
    if not endpoint:
        endpoint = urllib.parse.urljoin(source["url"], "/wp-json/wp/v2/job")
    per_page = 100
    jobs: list[Job] = []

    for page in range(1, 6):
        query = urllib.parse.urlencode(
            {
                "per_page": per_page,
                "page": page,
                "_fields": "id,date,link,title,content,meta",
            }
        )
        try:
            payload = client.get_json(endpoint + "?" + query)
        except RuntimeError as exc:
            if page > 1 and "HTTP 400" in str(exc):
                break
            raise
        if not isinstance(payload, list):
            raise RuntimeError("WordPress-rajapinta palautti odottamattoman vastauksen.")
        for item in payload:
            if not isinstance(item, dict):
                continue
            title_value = item.get("title") or {}
            content_value = item.get("content") or {}
            meta_value = item.get("meta") or {}
            title = clean_space(
                title_value.get("rendered")
                if isinstance(title_value, dict)
                else title_value
            )
            description = strip_html(
                content_value.get("rendered")
                if isinstance(content_value, dict)
                else content_value
            )
            listing_text = ""
            if isinstance(meta_value, dict):
                listing_text = strip_html(meta_value.get("rendered_listing") or "")
            combined = clean_space(f"{title} {description} {listing_text}")
            link = canonical_url(item.get("link"))
            if not title or not link:
                continue
            jobs.append(
                Job(
                    title=title,
                    company=source["name"],
                    location=find_location(combined, config),
                    url=link,
                    source=source["name"],
                    description=description,
                    deadline=find_deadline(listing_text or combined),
                    published=clean_space(item.get("date")),
                )
            )
        if len(payload) < per_page:
            break

    progress(f"{source['name']}: löytyi {len(jobs)} ilmoitusta")
    return deduplicate_jobs(jobs)


def workday_source_jobs(
    client: HttpClient,
    source: dict[str, Any],
    config: dict[str, Any],
    progress: Callable[[str], None],
) -> list[Job]:
    parsed = urllib.parse.urlparse(source["url"])
    tenant = parsed.hostname.split(".")[0] if parsed.hostname else ""
    site = parsed.path.strip("/").split("/")[0]
    if not tenant or not site:
        raise RuntimeError("Workday-osoitteesta ei voitu päätellä tenant- ja site-arvoja.")

    root = f"{parsed.scheme}://{parsed.netloc}"
    api_root = f"{root}/wday/cxs/{tenant}/{site}"
    listing_url = f"{api_root}/jobs"
    offset = 0
    # Workdayn julkinen CXS-haku hylkää tällä sivustolla yli 20:n sivukoon
    # HTTP 400 -virheellä.
    limit = 20
    listings: list[dict[str, Any]] = []

    while offset < 500:
        payload = {
            "appliedFacets": {},
            "limit": limit,
            "offset": offset,
            "searchText": "",
        }
        result = client.post_json(listing_url, payload)
        page = result.get("jobPostings", [])
        if not isinstance(page, list):
            break
        listings.extend(item for item in page if isinstance(item, dict))
        total = int(result.get("total", len(listings)) or len(listings))
        offset += len(page)
        if not page or offset >= total:
            break

    roles = config["profile"].get("roles", [])

    def priority(item: dict[str, Any]) -> tuple[int, str]:
        title = fold_text(item.get("title", ""))
        return (
            0 if any(role_matches_text(role, title) for role in roles) else 1,
            title,
        )

    jobs: list[Job] = []
    max_details = int(config["app"].get("maximum_details_per_source", 35))
    for index, item in enumerate(sorted(listings, key=priority)):
        external_path = clean_space(item.get("externalPath"))
        public_url = urllib.parse.urljoin(source["url"].rstrip("/") + "/", external_path.lstrip("/"))
        title = clean_space(item.get("title")) or "Nimetön työpaikka"
        job = Job(
            title=title,
            company=source["name"],
            location=clean_space(item.get("locationsText")),
            url=public_url,
            source=source["name"],
            published=clean_space(item.get("postedOn")),
        )
        if external_path and index < max_details:
            try:
                detail = client.get_json(api_root + external_path)
                info = detail.get("jobPostingInfo", detail)
                if isinstance(info, dict):
                    job.title = clean_space(info.get("title")) or job.title
                    job.company = (
                        clean_space(info.get("company"))
                        or clean_space(info.get("companyName"))
                        or job.company
                    )
                    job.location = (
                        clean_space(info.get("location"))
                        or clean_space(info.get("locationText"))
                        or job.location
                    )
                    job.description = strip_html(
                        info.get("jobDescription") or info.get("description") or ""
                    )
                    job.deadline = clean_space(
                        info.get("endDate") or info.get("applicationDeadline") or ""
                    )
                    job.published = clean_space(info.get("startDate")) or job.published
                    job.url = clean_space(info.get("externalUrl")) or job.url
            except Exception as exc:
                logging.warning("Workday-detalji epäonnistui (%s): %s", title, exc)
        jobs.append(job)

    progress(f"{source['name']}: löytyi {len(jobs)} ilmoitusta")
    return deduplicate_jobs(jobs)


def merge_duplicate_job(existing: Job, candidate: Job) -> Job:
    links = merge_source_links(existing.source_links(), candidate.source_links())
    if len(candidate.description) > len(existing.description):
        existing.description = candidate.description
    existing.deadline = newer_job_date(existing.deadline, candidate.deadline)
    existing.published = newer_job_date(existing.published, candidate.published)
    existing.company = existing.company or candidate.company
    existing.location = existing.location or candidate.location
    existing.links = links

    direct_links = [
        item for item in links if not is_aggregator_source(item.get("source"))
    ]
    primary = direct_links[0] if direct_links else (links[0] if links else None)
    if primary:
        existing.url = primary["url"]
    source_names = [
        clean_space(item.get("source"))
        for item in links
        if clean_space(item.get("source"))
    ]
    existing.source = " + ".join(dict.fromkeys(source_names)) or existing.source
    return existing


def deduplicate_jobs(jobs: Iterable[Job]) -> list[Job]:
    by_url: dict[str, Job] = {}
    by_listing: dict[str, Job] = {}
    ordered: list[Job] = []
    for job in jobs:
        if not job.title or not job.url:
            continue
        url_key = canonical_url(job.url)
        listing_key = job.canonical_key
        existing = by_url.get(url_key)
        if existing is None:
            candidate = by_listing.get(listing_key)
            if candidate is not None and listing_dates_compatible(candidate, job):
                existing = candidate
        if existing is None:
            job.url = url_key
            job.links = job.source_links()
            ordered.append(job)
            existing = job
        else:
            merge_duplicate_job(existing, job)
        for item in existing.source_links():
            by_url[canonical_url(item["url"])] = existing
        by_listing[existing.canonical_key] = existing
    return ordered


QUALIFICATION_PATTERNS: dict[str, list[str]] = {
    "B-ajokortti": [
        "b-ajokortti",
        "b luokan ajokortti",
        "b-luokan ajokortti",
        "voimassa oleva ajokortti",
    ],
    "BE-ajokortti": ["be-ajokortti", "be luokan ajokortti", "be-luokan ajokortti"],
    "C-ajokortti": ["c-ajokortti", "c luokan ajokortti", "c-luokan ajokortti"],
    "CE-ajokortti": [
        "ce-ajokortti",
        "ce luokan ajokortti",
        "ce-luokan ajokortti",
    ],
    "ADR-ajolupa": ["adr-ajolupa", "adr lupa", "adr-kortti", "adr kortti"],
    "kuljettajan ammattipätevyys": [
        "kuljettajan ammattipätevyys",
        "kuljettajan ammattipatevyys",
        "ammattipätevyys voimassa",
    ],
    "digipiirturikortti": ["digipiirturikortti", "kuljettajakortti"],
    "trukkikortti": ["trukkikortti", "trukinajolupa"],
    "työturvallisuuskortti": ["työturvallisuuskortti"],
    "tulityökortti": ["tulityökortti"],
    "Tieturva 1": ["tieturva 1", "tieturva1"],
    "sähkötyöturvallisuuskortti SFS 6002": [
        "sfs 6002",
        "sähkötyöturvallisuuskortti",
    ],
    "henkilönostinkortti": [
        "henkilönostinkortti",
        "henkilönostimen käyttölupa",
        "nostinlupa",
    ],
    "nosturinkuljettajan pätevyys": [
        "nosturinkuljettajan pätevyys",
        "nosturinkuljettajan patevyys",
        "nosturinkuljettajakortti",
    ],
    "hygieniapassi": ["hygieniapassi"],
    "anniskelupassi": ["anniskelupassi"],
    "ensiapukortti EA1": [
        "ea1",
        "ea 1",
        "ensiapu 1",
        "ensiapukortti ea1",
        "ensiapukortti ea 1",
    ],
    "hätäensiapukortti": ["hätäensiapukortti", "hataensiapukortti"],
    "järjestyksenvalvojakortti": [
        "järjestyksenvalvojakortti",
        "järjestyksenvalvojan hyväksyntä",
    ],
    "vartijakortti": ["vartijakortti", "vartijaksi hyväksytty"],
}


def score_job(job: Job, config: dict[str, Any]) -> Job:
    profile = config["profile"]
    full_text = fold_text(
        " ".join((job.title, job.company, job.location, job.description))
    )
    title_text = fold_text(job.title)
    score = 15
    reasons: list[str] = []
    warnings: list[str] = []

    matched_roles: list[str] = []
    for role in profile.get("roles", []):
        if role_matches_text(role, title_text) or role_matches_text(role, full_text):
            matched_roles.append(role)
    matched_roles = list(dict.fromkeys(matched_roles))
    if matched_roles:
        role_points = min(42, 22 + 6 * (len(matched_roles) - 1))
        score += role_points
        reasons.append(f"Sopiva työnkuva: {', '.join(matched_roles[:3])}")
    else:
        score -= 25
        warnings.append("Kiinnostavaa tehtävänimikettä ei tunnistettu")

    preferred = matching_location_choices(
        full_text,
        profile.get("preferred_locations", []),
    )
    acceptable = matching_location_choices(
        full_text,
        profile.get("acceptable_locations", []),
    )
    if preferred:
        score += 25
        reasons.append(f"Toivottu sijainti: {', '.join(preferred)}")
    elif acceptable:
        score += 15
        reasons.append(f"Mahdollinen sijainti: {', '.join(acceptable)}")
    elif not job.location:
        score += 3
        warnings.append("Sijaintia ei pystytty tunnistamaan – tarkista ilmoitus")
    else:
        score -= 22
        warnings.append(f"Sijainti ei vaikuta ensisijaiselta: {job.location}")

    skill_matches: list[str] = []
    skill_terms = {
        "varasto- ja logistiikkakokemus": ["varasto", "logisti", "keräily", "pakka"],
        "siivouskokemus": ["siivous", "puhtaus", "laitoshuol"],
        "pihatyökokemus": ["pihatyö", "viherrak", "ruohonleik", "ulkoalue"],
        "tietokonetaidot": ["tietokone", "järjestelmä", "scanner", "päätelaite"],
        "fyysinen työ": ["fyysinen", "nosto", "kuorm", "purku"],
    }
    for label, terms in skill_terms.items():
        if any(term in full_text for term in terms):
            skill_matches.append(label)
    if skill_matches:
        score += min(12, len(skill_matches) * 3)
        reasons.append(f"Vahvuus osuu: {', '.join(skill_matches[:3])}")

    for qualification, patterns in QUALIFICATION_PATTERNS.items():
        if not any(fold_text(pattern) in full_text for pattern in patterns):
            continue
        status = fold_text(profile.get("qualifications", {}).get(qualification, "unknown"))
        if status in {"yes", "kylla", "kyllä", "true"}:
            score += 4
            reasons.append(f"Pätevyys löytyy: {qualification}")
        elif status in {"no", "ei", "false"}:
            score -= 35
            warnings.append(f"Ilmoitus näyttää vaativan puuttuvan pätevyyden: {qualification}")
        else:
            score -= 5
            warnings.append(f"Tarkista, vaaditaanko {qualification}")

    for phrase in profile.get("excluded_phrases", []):
        if fold_text(phrase) in full_text:
            score -= 45
            warnings.append(f"Ei-toivottu ehto: {phrase}")

    if re.search(r"\b(?:esihenkilö|paallikko|päällikkö|johtaja|manager|engineer)\b", full_text):
        if not matched_roles:
            score -= 15

    job.score = max(0, min(100, score))
    job.reasons = reasons
    job.warnings = warnings
    job.matched_roles = matched_roles
    return job


class JobDatabase:
    def __init__(self, path: Path = DB_PATH, duplicate_window_days: int = 60) -> None:
        ensure_directories()
        self.connection = sqlite3.connect(path, timeout=20)
        self.connection.row_factory = sqlite3.Row
        self.duplicate_window_days = duplicate_window_days
        existing_columns = self._job_columns()
        if existing_columns and (
            "canonical_key" not in existing_columns or "links_json" not in existing_columns
        ):
            self.connection.close()
            backup_file(path, "jobs_ennen_v1.2")
            self.connection = sqlite3.connect(path, timeout=20)
            self.connection.row_factory = sqlite3.Row
        self._create_schema()

    def _job_columns(self) -> set[str]:
        table = self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'jobs'"
        ).fetchone()
        if not table:
            return set()
        return {
            str(row["name"])
            for row in self.connection.execute("PRAGMA table_info(jobs)").fetchall()
        }

    def _create_schema(self) -> None:
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                fingerprint TEXT PRIMARY KEY,
                canonical_key TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                company TEXT,
                location TEXT,
                source TEXT,
                links_json TEXT NOT NULL DEFAULT '[]',
                description TEXT,
                deadline TEXT,
                published TEXT,
                score INTEGER NOT NULL DEFAULT 0,
                reasons_json TEXT NOT NULL DEFAULT '[]',
                warnings_json TEXT NOT NULL DEFAULT '[]',
                matched_roles_json TEXT NOT NULL DEFAULT '[]',
                draft TEXT,
                status TEXT NOT NULL DEFAULT 'new',
                applied_at TEXT,
                applied_once INTEGER NOT NULL DEFAULT 0,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL
            )
            """
        )
        columns = self._job_columns()
        if "canonical_key" not in columns:
            self.connection.execute(
                "ALTER TABLE jobs ADD COLUMN canonical_key TEXT NOT NULL DEFAULT ''"
            )
        if "links_json" not in columns:
            self.connection.execute(
                "ALTER TABLE jobs ADD COLUMN links_json TEXT NOT NULL DEFAULT '[]'"
            )
        if "applied_at" not in columns:
            self.connection.execute(
                "ALTER TABLE jobs ADD COLUMN applied_at TEXT"
            )
        if "applied_once" not in columns:
            self.connection.execute(
                "ALTER TABLE jobs ADD COLUMN applied_once INTEGER NOT NULL DEFAULT 0"
            )
        # Vanhoissa versioissa oli vain Haettu-tila, ei erillistä hakupäivää.
        # applied_once säilyttää vanhat merkinnät historiassa myös silloin, jos
        # käyttäjä poistaa ilmoituksen myöhemmin tavallisesta listasta.
        self.connection.execute(
            "UPDATE jobs SET applied_once = 1 WHERE status = 'applied'"
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                found_count INTEGER NOT NULL DEFAULT 0,
                new_count INTEGER NOT NULL DEFAULT 0,
                errors_json TEXT NOT NULL DEFAULT '[]'
            )
            """
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_canonical_key "
            "ON jobs (canonical_key, last_seen)"
        )
        self._migrate_existing_rows()
        self.connection.commit()

    def _migrate_existing_rows(self) -> None:
        rows = self.connection.execute(
            """
            SELECT fingerprint, title, company, location, source, url,
                   canonical_key, links_json
            FROM jobs
            WHERE canonical_key = '' OR canonical_key IS NULL
               OR links_json = '[]' OR links_json IS NULL
            """
        ).fetchall()
        for row in rows:
            job = Job(
                title=row["title"],
                company=row["company"] or "",
                location=row["location"] or "",
                url=row["url"],
                source=row["source"] or "",
            )
            links = merge_source_links(
                [source_link(row["source"], row["url"])],
                self._read_links(row["links_json"]),
            )
            self.connection.execute(
                """
                UPDATE jobs SET canonical_key = ?, links_json = ?
                WHERE fingerprint = ?
                """,
                (
                    job.canonical_key,
                    json.dumps(links, ensure_ascii=False),
                    row["fingerprint"],
                ),
            )

    @staticmethod
    def _read_links(value: Any) -> list[dict[str, str]]:
        try:
            payload = json.loads(value or "[]")
        except (TypeError, json.JSONDecodeError):
            return []
        if not isinstance(payload, list):
            return []
        return [
            source_link(item.get("source"), item.get("url"))
            for item in payload
            if isinstance(item, dict) and clean_space(item.get("url"))
        ]

    def _row_job(self, row: sqlite3.Row) -> Job:
        return Job(
            title=row["title"],
            company=row["company"] or "",
            location=row["location"] or "",
            url=row["url"],
            source=row["source"] or "",
            description=row["description"] or "",
            deadline=row["deadline"] or "",
            published=row["published"] or "",
            score=int(row["score"] or 0),
            links=self._read_links(row["links_json"]),
        )

    def close(self) -> None:
        self.connection.close()

    def count(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])

    def upsert(self, job: Job) -> bool:
        now = datetime.now().isoformat(timespec="seconds")
        existing = self.connection.execute(
            "SELECT * FROM jobs WHERE fingerprint = ?", (job.fingerprint,)
        ).fetchone()
        if existing is None:
            cutoff = (
                datetime.now() - timedelta(days=self.duplicate_window_days)
            ).isoformat(timespec="seconds")
            candidates = self.connection.execute(
                """
                SELECT * FROM jobs
                WHERE canonical_key = ? AND last_seen >= ?
                ORDER BY CASE status WHEN 'applied' THEN 0 ELSE 1 END, last_seen DESC
                """,
                (job.canonical_key, cutoff),
            ).fetchall()
            existing = next(
                (
                    row
                    for row in candidates
                    if listing_dates_compatible(self._row_job(row), job)
                ),
                None,
            )
        if existing:
            previous_job = self._row_job(existing)
            reopened = listing_has_reopened(previous_job, job)
            merged = merge_duplicate_job(previous_job, job)
            links = merged.source_links()
            status = existing["status"]
            if reopened and status != "applied":
                status = "republished"
            self.connection.execute(
                """
                UPDATE jobs SET
                    canonical_key = ?, url = ?, title = ?, company = ?,
                    location = ?, source = ?, links_json = ?, description = ?,
                    deadline = ?, published = ?, score = ?,
                    reasons_json = ?, warnings_json = ?, matched_roles_json = ?,
                    status = ?, last_seen = ?
                WHERE fingerprint = ?
                """,
                (
                    merged.canonical_key,
                    merged.url,
                    merged.title,
                    merged.company,
                    merged.location,
                    merged.source,
                    json.dumps(links, ensure_ascii=False),
                    merged.description,
                    merged.deadline,
                    merged.published,
                    job.score,
                    json.dumps(job.reasons, ensure_ascii=False),
                    json.dumps(job.warnings, ensure_ascii=False),
                    json.dumps(job.matched_roles, ensure_ascii=False),
                    status,
                    now,
                    existing["fingerprint"],
                ),
            )
            is_new = reopened and existing["status"] != "applied"
        else:
            links = job.source_links()
            self.connection.execute(
                """
                INSERT INTO jobs (
                    fingerprint, canonical_key, url, title, company, location,
                    source, links_json, description, deadline, published, score,
                    reasons_json, warnings_json, matched_roles_json, status,
                    first_seen, last_seen
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?)
                """,
                (
                    job.fingerprint,
                    job.canonical_key,
                    job.url,
                    job.title,
                    job.company,
                    job.location,
                    job.source,
                    json.dumps(links, ensure_ascii=False),
                    job.description,
                    job.deadline,
                    job.published,
                    job.score,
                    json.dumps(job.reasons, ensure_ascii=False),
                    json.dumps(job.warnings, ensure_ascii=False),
                    json.dumps(job.matched_roles, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            is_new = True
        self.connection.commit()
        return is_new

    def list_jobs(
        self, minimum_score: int = 0, days: int = 60, include_ignored: bool = False
    ) -> list[sqlite3.Row]:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        status_clause = "" if include_ignored else "AND status != 'ignored'"
        query = f"""
            SELECT * FROM jobs
            WHERE score >= ? {status_clause}
            ORDER BY
                CASE status WHEN 'republished' THEN 0 WHEN 'new' THEN 1
                            WHEN 'seen' THEN 2 WHEN 'applied' THEN 3 ELSE 4 END,
                score DESC, first_seen DESC
        """
        rows = self.connection.execute(query, (minimum_score,)).fetchall()
        # Tavalliset vanhat ilmoitukset voidaan edelleen piilottaa days_to_show-
        # asetuksen mukaan. Päättyneet ilmoitukset pysyvät näkyvissä, kunnes
        # käyttäjä poistaa ne listasta.
        return [
            row
            for row in rows
            if row["last_seen"] >= cutoff or deadline_has_passed(row["deadline"])
        ]

    def get_job(self, fingerprint: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM jobs WHERE fingerprint = ?", (fingerprint,)
        ).fetchone()

    def list_applied_jobs(self) -> list[sqlite3.Row]:
        """Palauta koko hakuhistoria uusimmasta hakupäivästä alkaen."""
        return self.connection.execute(
            """
            SELECT * FROM jobs
            WHERE applied_once = 1
            ORDER BY
                CASE WHEN applied_at IS NULL THEN 1 ELSE 0 END,
                applied_at DESC,
                company COLLATE NOCASE,
                title COLLATE NOCASE
            """
        ).fetchall()

    def set_status(self, fingerprint: str, status: str) -> None:
        allowed = {"new", "republished", "seen", "applied", "ignored"}
        if status not in allowed:
            raise ValueError(f"Tuntematon tila: {status}")
        if status == "applied":
            self.connection.execute(
                """
                UPDATE jobs
                SET status = ?, applied_at = COALESCE(applied_at, ?),
                    applied_once = 1
                WHERE fingerprint = ?
                """,
                (
                    status,
                    datetime.now().isoformat(timespec="seconds"),
                    fingerprint,
                ),
            )
        else:
            self.connection.execute(
                "UPDATE jobs SET status = ? WHERE fingerprint = ?",
                (status, fingerprint),
            )
        self.connection.commit()

    def start_run(self) -> int:
        cursor = self.connection.execute(
            "INSERT INTO runs (started_at) VALUES (?)",
            (datetime.now().isoformat(timespec="seconds"),),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def finish_run(self, run_id: int, found: int, new: int, errors: list[str]) -> None:
        self.connection.execute(
            """
            UPDATE runs SET finished_at = ?, found_count = ?, new_count = ?,
                            errors_json = ?
            WHERE id = ?
            """,
            (
                datetime.now().isoformat(timespec="seconds"),
                found,
                new,
                json.dumps(errors, ensure_ascii=False),
                run_id,
            ),
        )
        self.connection.commit()


def write_report(jobs: list[Job], errors: list[str]) -> Path:
    ensure_directories()
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    path = REPORT_DIR / f"tyopaikat_{stamp}.html"
    cards: list[str] = []
    for job in sorted(jobs, key=lambda item: item.score, reverse=True):
        reason_items = "".join(f"<li>{html.escape(item)}</li>" for item in job.reasons)
        warning_items = "".join(f"<li>{html.escape(item)}</li>" for item in job.warnings)
        deadline = format_job_date(job.deadline)
        deadline_line = f"{DEADLINE_HEADING}: {deadline}" if deadline else ""
        cards.append(
            f"""
            <article class="job">
              <div class="score">{job.score}</div>
              <div>
                <h2>{html.escape(job.title)}</h2>
                <p class="meta">{html.escape(job.company)} ·
                   {html.escape(job.location or "Sijainti tarkistettava")}</p>
                <p>{html.escape(deadline_line)}</p>
                <ul>{reason_items}</ul>
                <ul class="warnings">{warning_items}</ul>
                <p><a href="{html.escape(job.url, quote=True)}">Avaa hakuilmoitus</a></p>
              </div>
            </article>
            """
        )
    error_html = ""
    if errors:
        error_html = (
            "<section class='errors'><h2>Lähteiden virheet</h2><ul>"
            + "".join(f"<li>{html.escape(item)}</li>" for item in errors)
            + "</ul></section>"
        )

    document = f"""<!doctype html>
<html lang="fi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Työpaikkatutkan kooste</title>
  <style>
    body {{ font: 16px/1.5 system-ui, sans-serif; margin: 0; background: #f4f6f8; color: #18212b; }}
    main {{ max-width: 900px; margin: 32px auto; padding: 0 20px; }}
    .job {{ display: grid; grid-template-columns: 72px 1fr; gap: 20px; background: white;
            padding: 22px; margin: 16px 0; border-radius: 14px; box-shadow: 0 3px 16px #0001; }}
    .score {{ width: 64px; height: 64px; display: grid; place-items: center; border-radius: 50%;
              background: #087f5b; color: white; font-size: 24px; font-weight: 700; }}
    h1, h2 {{ line-height: 1.2; }} h2 {{ margin-top: 0; }}
    .meta {{ font-weight: 650; }} .warnings {{ color: #a23b18; }}
    a {{ color: #075fb5; font-weight: 650; }} .errors {{ background: #fff3cd; padding: 18px; border-radius: 12px; }}
  </style>
</head>
<body><main>
  <h1>Työpaikkatutkan kooste</h1>
  <p>{datetime.now().strftime("%d.%m.%Y klo %H.%M")} · {len(jobs)} sopivaa uutta paikkaa</p>
  {error_html}
  {''.join(cards) if cards else '<p>Uusia riittävän hyvin sopivia paikkoja ei löytynyt.</p>'}
</main></body></html>"""
    path.write_text(document, encoding="utf-8")
    return path


@dataclass
class ScanResult:
    found_count: int
    stored_count: int
    new_matches: list[Job]
    errors: list[str]
    report_path: Path


class JobScanner:
    def __init__(
        self,
        config: dict[str, Any],
        progress: Callable[[str], None] | None = None,
        database_path: Path = DB_PATH,
    ) -> None:
        self.config = config
        self.progress = progress or (lambda message: logging.info(message))
        timeout = int(config["app"].get("request_timeout_seconds", 25))
        self.client = HttpClient(timeout)
        self.database_path = database_path

    def scan(self) -> ScanResult:
        duplicate_window = int(
            self.config["app"].get("duplicate_window_days", 60)
        )
        database = JobDatabase(self.database_path, duplicate_window)
        run_id = database.start_run()
        errors: list[str] = []
        found: list[Job] = []
        stored_count = 0
        new_matches: list[Job] = []
        minimum = int(self.config["app"].get("minimum_score", 38))

        try:
            enabled_sources = [
                source for source in self.config["sources"] if source.get("enabled", True)
            ]
            for source in enabled_sources:
                self.progress(f"Tarkistetaan: {source['name']}…")
                try:
                    source_type = source.get("type", "html").lower()
                    if source_type == "workday":
                        jobs = workday_source_jobs(
                            self.client, source, self.config, self.progress
                        )
                    elif source_type == "wordpress":
                        jobs = wordpress_source_jobs(
                            self.client, source, self.config, self.progress
                        )
                    elif source_type == "feed":
                        jobs = feed_source_jobs(
                            self.client, source, self.config, self.progress
                        )
                    elif source_type == "html":
                        jobs = html_source_jobs(
                            self.client, source, self.config, self.progress
                        )
                    elif source_type == "sitemap":
                        jobs = sitemap_source_jobs(
                            self.client, source, self.config, self.progress
                        )
                    elif source_type == "eezy":
                        jobs = eezy_source_jobs(
                            self.client, source, self.config, self.progress
                        )
                    else:
                        raise RuntimeError(f"Tuntematon lähdetyyppi: {source_type}")
                    found.extend(jobs)
                except SourceBlockedError as exc:
                    logging.info("%s ohitettiin: %s", source["name"], exc)
                    self.progress(f"Ohitetaan {source['name']}: sivusto vaatii selaimen")
                except Exception as exc:
                    message = f"{source['name']}: {exc}"
                    errors.append(message)
                    logging.exception("Lähteen tarkistus epäonnistui: %s", source["name"])
                    self.progress(f"Virhe lähteessä {source['name']} – jatketaan")

            found = deduplicate_jobs(found)
            for job in found:
                if not job_matches_location_filter(job, self.config):
                    continue
                score_job(job, self.config)
                # Tallennetaan myös hieman kynnyksen alle jäävät, jotta käyttäjä
                # voi tarkastaa pisteytyksen käyttöliittymässä.
                if job.score < max(1, minimum - 12):
                    continue
                job.is_new = database.upsert(job)
                stored_count += 1
                # Päättynyt paikka tallennetaan punaista listanäkymää varten,
                # mutta sitä ei käsitellä uutena sopivana hakuilmoituksena.
                if (
                    job.is_new
                    and job.score >= minimum
                    and not deadline_has_passed(job.deadline)
                ):
                    new_matches.append(job)

            report_path = write_report(new_matches, errors)
            database.finish_run(run_id, len(found), len(new_matches), errors)
            self.progress(
                f"Valmis: {len(found)} ilmoitusta, {len(new_matches)} uutta sopivaa"
            )
            return ScanResult(
                found_count=len(found),
                stored_count=stored_count,
                new_matches=new_matches,
                errors=errors,
                report_path=report_path,
            )
        except Exception:
            database.finish_run(run_id, len(found), len(new_matches), errors)
            raise
        finally:
            database.close()


def open_file(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        import subprocess

        subprocess.Popen(["open", str(path)])
    else:
        import subprocess

        subprocess.Popen(["xdg-open", str(path)])


class TyopaikkatutkaGUI:
    def __init__(self, config: dict[str, Any]) -> None:
        import tkinter as tk
        from tkinter import messagebox, ttk

        self.tk = tk
        self.ttk = ttk
        self.messagebox = messagebox
        self.config = config
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.dark_mode = windows_prefers_dark()
        self.deadline_latest_first: bool | None = None
        self.score_highest_first: bool | None = None
        self.settings_window: Any | None = None
        self.applied_window: Any | None = None
        self.applied_tree: Any | None = None
        self.applied_status_text: Any | None = None
        self.applied_custom_controls: list[Any] = []
        self.settings_vars: dict[str, Any] = {}
        self.settings_texts: dict[str, Any] = {}
        self.settings_selection_lists: dict[str, Any] = {}
        self.settings_qualification_vars: dict[str, Any] = {}
        self.settings_source_vars: list[Any] = []
        self.settings_source_entries: list[dict[str, Any]] = []
        self.settings_source_filter_var: Any | None = None
        self.settings_source_status_var: Any | None = None
        self.settings_native_widgets: list[tuple[Any, str]] = []
        self.custom_controls: list[Any] = []
        self.settings_custom_controls: list[Any] = []
        self.settings_tab_buttons: dict[str, RoundedButtonControl] = {}
        self.settings_tab_frames: dict[str, Any] = {}
        self.app_icon: Any | None = None
        self.native_icon_handles: dict[str, tuple[int, int]] = {}

        self.root = tk.Tk()
        self._apply_application_icon(self.root)
        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.root.geometry("1180x720")
        self.root.minsize(900, 560)
        self._configure_style()
        self._build_ui()
        self.refresh_jobs()
        self.root.after(150, self._poll_events)
        if sys.platform.startswith("win"):
            self._apply_windows_titlebar_theme()
            self.root.after(250, self._apply_windows_titlebar_theme)
            self.root.after(2000, self._sync_windows_theme)

    def _apply_application_icon(self, window: Any) -> None:
        """Aseta Työpaikkatutkan kuvake pää- ja asetusikkunoihin."""
        try:
            if self.app_icon is None and APP_ICON_PNG_PATH.exists():
                self.app_icon = self.tk.PhotoImage(file=str(APP_ICON_PNG_PATH))
            if self.app_icon is not None:
                window.iconphoto(True, self.app_icon)
            if sys.platform.startswith("win") and APP_ICON_ICO_PATH.exists():
                window.iconbitmap(default=str(APP_ICON_ICO_PATH))
        except (OSError, self.tk.TclError):
            logging.warning("Sovelluskuvaketta ei voitu ottaa käyttöön.", exc_info=True)

    def _rounded_button(
        self,
        parent: Any,
        *,
        text: str,
        command: Callable[[], None],
        primary: bool = False,
        tab: bool = False,
        selected: bool = False,
        minimum_width: int = 0,
        settings_control: bool = False,
    ) -> RoundedButtonControl:
        control = RoundedButtonControl(
            self.tk,
            parent,
            text=text,
            command=command,
            palette=self.palette,
            primary=primary,
            tab=tab,
            selected=selected,
            minimum_width=minimum_width,
        )
        self.custom_controls.append(control)
        if settings_control:
            self.settings_custom_controls.append(control)
        return control

    def _themed_checkbutton(
        self,
        parent: Any,
        *,
        text: str,
        variable: Any,
        command: Callable[[], None] | None = None,
        settings_control: bool = False,
    ) -> ThemedCheckbuttonControl:
        control = ThemedCheckbuttonControl(
            self.tk,
            parent,
            text=text,
            variable=variable,
            palette=self.palette,
            command=command,
        )
        self.custom_controls.append(control)
        if settings_control:
            self.settings_custom_controls.append(control)
        return control

    def _configure_style(self) -> None:
        style = self.ttk.Style()
        self.palette = theme_palette(self.dark_mode)
        palette = self.palette
        self.root.option_add(
            "*TCombobox*Listbox.background",
            palette["card"],
        )
        self.root.option_add(
            "*TCombobox*Listbox.foreground",
            palette["foreground"],
        )
        self.root.option_add(
            "*TCombobox*Listbox.selectBackground",
            palette["selection"],
        )
        self.root.option_add(
            "*TCombobox*Listbox.selectForeground",
            palette["selection_foreground"],
        )
        try:
            style.theme_use("clam")
        except self.tk.TclError:
            pass
        self.root.configure(bg=palette["background"])
        style.configure("TFrame", background=palette["background"])
        style.configure("Card.TFrame", background=palette["border"])
        style.configure(
            "TLabel",
            background=palette["background"],
            foreground=palette["foreground"],
        )
        style.configure(
            "Title.TLabel",
            background=palette["background"],
            foreground=palette["foreground"],
            font=("Segoe UI", 20, "bold"),
        )
        style.configure(
            "Sub.TLabel",
            background=palette["background"],
            foreground=palette["secondary"],
            font=("Segoe UI", 10),
        )
        style.configure(
            "Section.TLabel",
            background=palette["background"],
            foreground=palette["accent"],
            font=("Segoe UI", 12, "bold"),
        )
        style.configure(
            "Help.TLabel",
            background=palette["background"],
            foreground=palette["secondary"],
            font=("Segoe UI", 9),
        )
        style.configure(
            "TNotebook",
            background=palette["background"],
            bordercolor=palette["background"],
            darkcolor=palette["background"],
            lightcolor=palette["background"],
            borderwidth=0,
            tabmargins=(0, 0, 0, 0),
        )
        style.configure(
            "TNotebook.Tab",
            background=palette["button"],
            foreground=palette["foreground"],
            bordercolor=palette["border"],
            darkcolor=palette["button"],
            lightcolor=palette["button"],
            font=("Segoe UI", 10, "bold"),
            padding=(16, 10),
        )
        style.map(
            "TNotebook.Tab",
            background=[
                ("selected", palette["primary"]),
                ("active", palette["button_active"]),
            ],
            foreground=[
                ("selected", palette["selection_foreground"]),
                ("active", palette["accent_bright"]),
            ],
            bordercolor=[
                ("selected", palette["accent"]),
                ("active", palette["accent"]),
            ],
        )
        for entry_style in ("TEntry", "TSpinbox"):
            style.configure(
                entry_style,
                fieldbackground=palette["card"],
                foreground=palette["foreground"],
                bordercolor=palette["button_border"],
                darkcolor=palette["card"],
                lightcolor=palette["card"],
                insertcolor=palette["accent"],
                padding=7,
            )
            style.map(
                entry_style,
                bordercolor=[("focus", palette["accent"])],
                fieldbackground=[
                    ("disabled", palette["button"]),
                    ("readonly", palette["card"]),
                ],
                foreground=[("disabled", palette["disabled"])],
            )
        style.configure(
            "TCombobox",
            fieldbackground=palette["card"],
            background=palette["button"],
            foreground=palette["foreground"],
            arrowcolor=palette["accent"],
            bordercolor=palette["button_border"],
            darkcolor=palette["card"],
            lightcolor=palette["card"],
            padding=7,
        )
        style.map(
            "TCombobox",
            fieldbackground=[
                ("readonly", palette["card"]),
                ("disabled", palette["button"]),
            ],
            foreground=[
                ("readonly", palette["foreground"]),
                ("disabled", palette["disabled"]),
            ],
            bordercolor=[("focus", palette["accent"])],
            arrowcolor=[("active", palette["accent_bright"])],
            selectbackground=[("readonly", palette["selection"])],
            selectforeground=[
                ("readonly", palette["selection_foreground"])
            ],
        )
        style.configure(
            "TLabelframe",
            background=palette["background"],
            bordercolor=palette["border"],
            darkcolor=palette["background"],
            lightcolor=palette["background"],
            relief="flat",
        )
        style.configure(
            "TLabelframe.Label",
            background=palette["background"],
            foreground=palette["accent"],
            font=("Segoe UI", 10, "bold"),
        )
        style.configure(
            "TButton",
            background=palette["button"],
            foreground=palette["foreground"],
            bordercolor=palette["button_border"],
            darkcolor=palette["button"],
            lightcolor=palette["button"],
            borderwidth=1,
            relief="flat",
            font=("Segoe UI", 10),
            padding=(12, 8),
        )
        style.map(
            "TButton",
            background=[
                ("pressed", palette["button_active"]),
                ("active", palette["button_active"]),
            ],
            foreground=[
                ("disabled", palette["disabled"]),
                ("active", palette["accent_bright"]),
            ],
            bordercolor=[
                ("focus", palette["accent"]),
                ("active", palette["accent"]),
            ],
            darkcolor=[
                ("pressed", palette["button_active"]),
                ("active", palette["button_active"]),
            ],
            lightcolor=[
                ("pressed", palette["button_active"]),
                ("active", palette["button_active"]),
            ],
        )
        style.configure(
            "Primary.TButton",
            background=palette["primary"],
            foreground=palette["selection_foreground"],
            bordercolor=palette["accent"],
            darkcolor=palette["primary"],
            lightcolor=palette["primary"],
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "Primary.TButton",
            background=[
                ("pressed", palette["primary_active"]),
                ("active", palette["primary_active"]),
            ],
            foreground=[
                ("disabled", palette["disabled"]),
                ("!disabled", palette["selection_foreground"]),
            ],
            bordercolor=[
                ("focus", palette["accent_bright"]),
                ("active", palette["accent_bright"]),
            ],
            darkcolor=[
                ("pressed", palette["primary_active"]),
                ("active", palette["primary_active"]),
            ],
            lightcolor=[
                ("pressed", palette["primary_active"]),
                ("active", palette["primary_active"]),
            ],
        )
        style.configure(
            "TCheckbutton",
            background=palette["background"],
            foreground=palette["foreground"],
            indicatorbackground=palette["card"],
            indicatorforeground=palette["selection_foreground"],
            bordercolor=palette["button_border"],
        )
        style.map(
            "TCheckbutton",
            background=[("active", palette["background"])],
            foreground=[
                ("disabled", palette["disabled"]),
                ("active", palette["accent_bright"]),
            ],
            indicatorbackground=[
                ("selected", palette["primary"]),
                ("!selected", palette["card"]),
            ],
            bordercolor=[
                ("focus", palette["accent"]),
                ("active", palette["accent"]),
            ],
        )
        style.configure(
            "Treeview",
            font=("Segoe UI", 10),
            rowheight=34,
            background=palette["card"],
            foreground=palette["foreground"],
            fieldbackground=palette["card"],
            bordercolor=palette["card"],
            darkcolor=palette["card"],
            lightcolor=palette["card"],
            borderwidth=0,
            relief="flat",
            highlightthickness=0,
        )
        try:
            style.layout(
                "Treeview",
                [("Treeview.treearea", {"sticky": "nswe"})],
            )
        except self.tk.TclError:
            pass
        style.map(
            "Treeview",
            background=[("selected", palette["selection"])],
            foreground=[("selected", palette["selection_foreground"])],
        )
        style.configure(
            "Treeview.Heading",
            background=palette["heading"],
            foreground=palette["foreground"],
            bordercolor=palette["border"],
            darkcolor=palette["border"],
            lightcolor=palette["border"],
            relief="flat",
            font=("Segoe UI", 10, "bold"),
            padding=(6, 8),
        )
        style.map(
            "Treeview.Heading",
            background=[("active", palette["button_active"])],
            foreground=[("active", palette["accent_bright"])],
            bordercolor=[("active", palette["accent"])],
        )
        style.configure(
            "TScrollbar",
            background=palette["button"],
            troughcolor=palette["trough"],
            arrowcolor=palette["foreground"],
            bordercolor=palette["border"],
            darkcolor=palette["button"],
            lightcolor=palette["button"],
        )
        style.map(
            "TScrollbar",
            background=[("active", palette["button_active"])],
            arrowcolor=[("active", palette["accent_bright"])],
        )
        style.configure(
            "TProgressbar",
            background=palette["accent"],
            troughcolor=palette["trough"],
            bordercolor=palette["background"],
            lightcolor=palette["accent"],
            darkcolor=palette["accent"],
        )
        for control in self.custom_controls:
            control.update_palette(palette)
        self._refresh_settings_native_colours()

    def _refresh_settings_native_colours(self) -> None:
        palette = self.palette
        window = self.settings_window
        try:
            if window is not None and window.winfo_exists():
                window.configure(bg=palette["background"])
        except self.tk.TclError:
            pass
        active_widgets: list[tuple[Any, str]] = []
        for widget, kind in self.settings_native_widgets:
            try:
                if not widget.winfo_exists():
                    continue
                if kind == "text":
                    widget.configure(
                        background=palette["card"],
                        foreground=palette["foreground"],
                        insertbackground=palette["accent"],
                        selectbackground=palette["selection"],
                        selectforeground=palette["selection_foreground"],
                        highlightbackground=palette["button_border"],
                        highlightcolor=palette["accent"],
                    )
                elif kind == "canvas":
                    widget.configure(
                        background=palette["background"],
                        highlightbackground=palette["background"],
                    )
                elif kind == "listbox":
                    widget.configure(
                        background=palette["card"],
                        foreground=palette["foreground"],
                        selectbackground=palette["selection"],
                        selectforeground=palette["selection_foreground"],
                        highlightbackground=palette["button_border"],
                        highlightcolor=palette["accent"],
                    )
                active_widgets.append((widget, kind))
            except self.tk.TclError:
                continue
        self.settings_native_widgets = active_widgets

    def _configure_tree_tags(self) -> None:
        palette = self.palette
        for tag in ("good", "medium", "republished", "applied", "ignored", "expired"):
            self.tree.tag_configure(
                tag,
                background=palette[f"{tag}_background"],
                foreground=palette[f"{tag}_foreground"],
            )

    def _sync_windows_theme(self) -> None:
        dark_mode = windows_prefers_dark()
        if dark_mode != self.dark_mode:
            self.dark_mode = dark_mode
            self._configure_style()
            self._configure_tree_tags()
            self.refresh_applied_jobs()
            self._apply_windows_titlebar_theme()
        self.root.after(2000, self._sync_windows_theme)

    def _apply_windows_titlebar_theme(self) -> None:
        apply_windows_titlebar_theme(self.root, self.dark_mode, self.palette)
        root_handles = apply_windows_window_icon(self.root)
        if root_handles is not None:
            self.native_icon_handles[str(self.root)] = root_handles
        for child_window in (self.settings_window, self.applied_window):
            try:
                if child_window is None or not child_window.winfo_exists():
                    continue
                apply_windows_titlebar_theme(
                    child_window,
                    self.dark_mode,
                    self.palette,
                )
                child_handles = apply_windows_window_icon(child_window)
                if child_handles is not None:
                    self.native_icon_handles[str(child_window)] = child_handles
            except self.tk.TclError:
                continue

    def _build_ui(self) -> None:
        header = self.ttk.Frame(self.root, padding=(24, 20, 24, 10))
        header.pack(fill="x")
        self.ttk.Label(
            header,
            text=f"{APP_NAME} {APP_VERSION}",
            style="Title.TLabel",
        ).pack(
            anchor="w"
        )
        self.ttk.Label(
            header,
            text=(
                "Etsii sopivia paikkoja, pisteyttää ne ja pitää kirjaa hakemisesta."
            ),
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        toolbar = self.ttk.Frame(self.root, padding=(24, 8))
        toolbar.pack(fill="x")
        self.scan_button = self._rounded_button(
            toolbar,
            text="Etsi työpaikkoja",
            command=self.start_scan,
            primary=True,
        )
        self.scan_button.pack(side="left")
        for text, command in (
            ("Avaa ilmoitus", self.open_selected),
            ("Lähdelinkit", self.show_selected_source_links),
            ("Merkitse haetuksi", lambda: self.set_selected_status("applied")),
            ("Haetut työpaikat", self.open_applied_jobs),
            ("Poista listasta", lambda: self.set_selected_status("ignored")),
            ("Avaa asetukset", self.open_settings),
        ):
            self._rounded_button(
                toolbar,
                text=text,
                command=command,
            ).pack(
                side="left", padx=(8, 0)
            )

        self.show_ignored = self.tk.BooleanVar(value=False)
        self._themed_checkbutton(
            toolbar,
            text="Näytä poistetut",
            variable=self.show_ignored,
            command=self.refresh_jobs,
        ).pack(side="right")

        table_frame = self.ttk.Frame(self.root, style="Card.TFrame", padding=1)
        table_frame.pack(fill="both", expand=True, padx=24, pady=(8, 12))
        columns = ("score", "status", "title", "company", "location", "deadline")
        self.tree = self.ttk.Treeview(
            table_frame, columns=columns, show="headings", selectmode="browse"
        )
        headings = {
            "score": "Pisteet",
            "status": "Tila",
            "title": "Tehtävä",
            "company": "Yritys",
            "location": "Sijainti",
            "deadline": DEADLINE_HEADING,
        }
        widths = {
            "score": 70,
            "status": 160,
            "title": 330,
            "company": 180,
            "location": 180,
            "deadline": 120,
        }
        for column in columns:
            heading_options: dict[str, Any] = {"text": headings[column]}
            if column == "score":
                heading_options["command"] = self.toggle_score_sort
            elif column == "deadline":
                heading_options["command"] = self.toggle_deadline_sort
            self.tree.heading(column, **heading_options)
            self.tree.column(
                column,
                width=widths[column],
                minwidth=60,
                anchor="center" if column in {"score", "status", "deadline"} else "w",
            )
        scrollbar = self.ttk.Scrollbar(
            table_frame, orient="vertical", command=self.tree.yview
        )
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self._configure_tree_tags()
        self.tree.bind("<Double-1>", lambda event: self.open_selected())
        self.tree.bind("<Return>", lambda event: self.open_selected())
        self.tree.bind("<<TreeviewSelect>>", self._mark_seen)

        self.status_text = self.tk.StringVar(value="Valmis")
        status = self.ttk.Frame(self.root, padding=(24, 0, 24, 18))
        status.pack(fill="x")
        self.progress = self.ttk.Progressbar(status, mode="indeterminate", length=180)
        self.progress.pack(side="left")
        self.ttk.Label(status, textvariable=self.status_text, style="Sub.TLabel").pack(
            side="left", padx=(12, 0)
        )

    def _close_settings(self) -> None:
        window = self.settings_window
        self.settings_window = None
        self.settings_vars = {}
        self.settings_texts = {}
        self.settings_selection_lists = {}
        self.settings_qualification_vars = {}
        self.settings_source_vars = []
        self.settings_source_entries = []
        self.settings_source_filter_var = None
        self.settings_source_status_var = None
        self.settings_native_widgets = []
        for control in self.settings_custom_controls:
            if control in self.custom_controls:
                self.custom_controls.remove(control)
        self.settings_custom_controls = []
        self.settings_tab_buttons = {}
        self.settings_tab_frames = {}
        if window is None:
            return
        try:
            self.root.unbind_all("<MouseWheel>")
            window.grab_release()
            window.destroy()
        except self.tk.TclError:
            pass

    def _scrollable_settings_panel(self, parent: Any) -> tuple[Any, Any]:
        container = self.ttk.Frame(parent)
        canvas = self.tk.Canvas(
            container,
            background=self.palette["background"],
            borderwidth=0,
            highlightthickness=0,
        )
        scrollbar = self.ttk.Scrollbar(
            container,
            orient="vertical",
            command=canvas.yview,
        )
        content = self.ttk.Frame(canvas, padding=(18, 18, 30, 18))
        canvas_window = canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        content.bind(
            "<Configure>",
            lambda event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(canvas_window, width=event.width),
        )

        def scroll(event: Any) -> None:
            if event.delta:
                canvas.yview_scroll(int(-event.delta / 120), "units")

        canvas.bind(
            "<Enter>",
            lambda event: canvas.bind_all("<MouseWheel>", scroll),
        )
        canvas.bind(
            "<Leave>",
            lambda event: canvas.unbind_all("<MouseWheel>"),
        )
        self.settings_native_widgets.append((canvas, "canvas"))
        return container, content

    def _settings_entry(
        self,
        parent: Any,
        row: int,
        label_column: int,
        label: str,
        key: str,
        value: Any,
        *,
        show: str | None = None,
    ) -> Any:
        self.ttk.Label(parent, text=label).grid(
            row=row,
            column=label_column,
            sticky="w",
            padx=(0, 8),
            pady=6,
        )
        variable = self.tk.StringVar(value=str(value or ""))
        self.settings_vars[key] = variable
        options: dict[str, Any] = {
            "textvariable": variable,
            "width": 34,
        }
        if show:
            options["show"] = show
        entry = self.ttk.Entry(parent, **options)
        entry.grid(
            row=row,
            column=label_column + 1,
            sticky="ew",
            padx=(0, 18 if label_column == 0 else 0),
            pady=6,
        )
        return entry

    def _settings_spinbox(
        self,
        parent: Any,
        row: int,
        label: str,
        key: str,
        value: Any,
        minimum: int,
        maximum: int,
    ) -> None:
        self.ttk.Label(parent, text=label).grid(
            row=row,
            column=0,
            sticky="w",
            padx=(0, 16),
            pady=7,
        )
        variable = self.tk.StringVar(value=str(value))
        self.settings_vars[key] = variable
        self.ttk.Spinbox(
            parent,
            from_=minimum,
            to=maximum,
            textvariable=variable,
            width=12,
        ).grid(row=row, column=1, sticky="w", pady=7)

    def _settings_text_box(
        self,
        parent: Any,
        row: int,
        column: int,
        label: str,
        key: str,
        values: Iterable[Any],
        height: int,
    ) -> None:
        frame = self.ttk.LabelFrame(parent, text=label, padding=8)
        frame.grid(
            row=row,
            column=column,
            columnspan=2,
            sticky="nsew",
            padx=0,
            pady=10,
        )
        text = self.tk.Text(
            frame,
            height=height,
            wrap="word",
            undo=True,
            borderwidth=0,
            highlightthickness=1,
            font=("Segoe UI", 10),
        )
        scrollbar = self.ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.insert("1.0", "\n".join(str(item) for item in values))
        text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.settings_texts[key] = text
        self.settings_native_widgets.append((text, "text"))
        self._refresh_settings_native_colours()

    def _settings_choice_box(
        self,
        parent: Any,
        row: int,
        column: int,
        label: str,
        key: str,
        values: Iterable[Any],
        choices: Iterable[str],
        normalizer: Callable[[Any], str],
        help_text: str,
        *,
        height: int = PROFILE_SELECTION_LIST_HEIGHT,
    ) -> None:
        available_choices = tuple(choices)
        frame = self.ttk.LabelFrame(parent, text=label, padding=10)
        frame.grid(
            row=row,
            column=column,
            columnspan=2,
            sticky="nsew",
            padx=0,
            pady=10,
        )
        frame.columnconfigure(0, weight=1)
        self.ttk.Label(
            frame,
            text=help_text,
            style="Help.TLabel",
            wraplength=900,
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 7))

        search_variable = self.tk.StringVar()
        selector = self.ttk.Combobox(
            frame,
            textvariable=search_variable,
            values=available_choices,
            state="normal",
        )
        selector.grid(row=1, column=0, sticky="ew", padx=(0, 8))

        suggestion_frame = self.ttk.Frame(frame)
        suggestion_frame.grid(
            row=2,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(5, 0),
        )
        suggestion_frame.columnconfigure(0, weight=1)
        suggestion_list = self.tk.Listbox(
            suggestion_frame,
            height=5,
            selectmode="browse",
            exportselection=False,
            borderwidth=0,
            highlightthickness=1,
            font=("Segoe UI", 10),
        )
        suggestion_scrollbar = self.ttk.Scrollbar(
            suggestion_frame,
            orient="vertical",
            command=suggestion_list.yview,
        )
        suggestion_list.configure(yscrollcommand=suggestion_scrollbar.set)
        suggestion_list.grid(row=0, column=0, sticky="ew")
        suggestion_scrollbar.grid(row=0, column=1, sticky="ns")
        self._bind_nested_vertical_scroll(
            suggestion_list,
            suggestion_scrollbar,
        )
        suggestion_frame.grid_remove()
        self.settings_native_widgets.append((suggestion_list, "listbox"))

        list_frame = self.ttk.Frame(frame)
        list_frame.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(9, 0))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        selection_list = self.tk.Listbox(
            list_frame,
            height=height,
            selectmode="extended",
            exportselection=False,
            borderwidth=0,
            highlightthickness=1,
            font=("Segoe UI", 10),
        )
        scrollbar = self.ttk.Scrollbar(
            list_frame,
            orient="vertical",
            command=selection_list.yview,
        )
        horizontal_scrollbar = self.ttk.Scrollbar(
            list_frame,
            orient="horizontal",
            command=selection_list.xview,
        )
        selection_list.configure(
            yscrollcommand=scrollbar.set,
            xscrollcommand=horizontal_scrollbar.set,
        )
        selection_list.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        horizontal_scrollbar.grid(row=1, column=0, sticky="ew")
        self._bind_nested_vertical_scroll(
            selection_list,
            scrollbar,
            horizontal_scrollbar,
        )
        for value in settings_list([normalizer(item) for item in values]):
            selection_list.insert("end", value)
        self.settings_selection_lists[key] = selection_list
        self.settings_native_widgets.append((selection_list, "listbox"))

        def hide_suggestions() -> None:
            suggestion_frame.grid_remove()
            suggestion_list.delete(0, "end")

        def add_current() -> None:
            value = normalizer(search_variable.get())
            if not value:
                return
            current = list(selection_list.get(0, "end"))
            if fold_text(value) not in {fold_text(item) for item in current}:
                selection_list.insert("end", value)
            search_variable.set("")
            selector.configure(values=available_choices)
            hide_suggestions()
            selector.focus_set()

        def remove_selected() -> None:
            for index in reversed(selection_list.curselection()):
                selection_list.delete(index)

        def use_suggestion(*, add: bool = False) -> None:
            selected = suggestion_list.curselection()
            if not selected:
                return
            search_variable.set(suggestion_list.get(selected[0]))
            hide_suggestions()
            selector.focus_set()
            if add:
                add_current()

        def filter_choices(event: Any) -> None:
            if event.keysym in {
                "Return",
                "KP_Enter",
                "Up",
                "Down",
                "Left",
                "Right",
                "Escape",
            }:
                return
            query = fold_text(search_variable.get())
            if not query:
                selector.configure(values=available_choices)
                hide_suggestions()
                return
            matches = selectable_choice_matches(
                search_variable.get(),
                available_choices,
                limit=20,
            )
            selector.configure(values=matches)
            suggestion_list.delete(0, "end")
            for match in matches:
                suggestion_list.insert("end", match)
            if matches:
                suggestion_list.configure(height=min(5, len(matches)))
                suggestion_frame.grid()
            else:
                suggestion_frame.grid_remove()

        def focus_suggestions(event: Any) -> str | None:
            if suggestion_frame.winfo_ismapped() and suggestion_list.size():
                suggestion_list.selection_clear(0, "end")
                suggestion_list.selection_set(0)
                suggestion_list.activate(0)
                suggestion_list.focus_set()
                return "break"
            return None

        def suggestion_up(event: Any) -> str | None:
            selected = suggestion_list.curselection()
            if selected and selected[0] == 0:
                selector.focus_set()
                selector.icursor("end")
                return "break"
            return None

        self._rounded_button(
            frame,
            text="Lisää",
            command=add_current,
            primary=True,
            settings_control=True,
        ).grid(row=1, column=1, sticky="e")
        self._rounded_button(
            frame,
            text="Poista valitut",
            command=remove_selected,
            settings_control=True,
        ).grid(row=4, column=0, columnspan=2, sticky="e", pady=(8, 0))
        selector.bind("<KeyRelease>", filter_choices)
        selector.bind("<Return>", lambda event: (add_current(), "break")[1])
        selector.bind("<Down>", focus_suggestions)
        selector.bind("<Escape>", lambda event: hide_suggestions())
        selector.bind("<<ComboboxSelected>>", lambda event: add_current())
        suggestion_list.bind(
            "<ButtonRelease-1>",
            lambda event: suggestion_list.after_idle(use_suggestion),
        )
        suggestion_list.bind(
            "<Double-1>",
            lambda event: suggestion_list.after_idle(
                lambda: use_suggestion(add=True)
            ),
        )
        suggestion_list.bind(
            "<Return>",
            lambda event: (use_suggestion(add=True), "break")[1],
        )
        suggestion_list.bind("<Up>", suggestion_up)
        selection_list.bind("<Delete>", lambda event: remove_selected())
        self._refresh_settings_native_colours()

    def _bind_nested_vertical_scroll(
        self,
        listbox: Any,
        *related_widgets: Any,
    ) -> None:
        """Vieritä sisäistä listaa liikuttamatta asetussivua."""

        def scroll_list(event: Any) -> str:
            button = getattr(event, "num", None)
            if button == 4:
                units = -1
            elif button == 5:
                units = 1
            else:
                delta = int(getattr(event, "delta", 0) or 0)
                if delta == 0:
                    return "break"
                steps = max(1, abs(delta) // 120)
                units = -steps if delta > 0 else steps
            listbox.yview_scroll(units, "units")
            return "break"

        for widget in (listbox, *related_widgets):
            widget.bind("<MouseWheel>", scroll_list)
            widget.bind("<Button-4>", scroll_list)
            widget.bind("<Button-5>", scroll_list)

    def _settings_location_box(
        self,
        parent: Any,
        row: int,
        column: int,
        label: str,
        key: str,
        values: Iterable[Any],
    ) -> None:
        self._settings_choice_box(
            parent,
            row,
            column,
            label,
            key,
            values,
            LOCATION_CHOICES,
            normalize_location_choice,
            "Kirjoita kunta tai maakunta ja valitse näkyvä ehdotus. "
            "Jos sijaintia ei löydy, voit lisätä kirjoittamasi oman sijainnin.",
        )

    def _settings_strength_box(
        self,
        parent: Any,
        row: int,
        column: int,
        label: str,
        key: str,
        values: Iterable[Any],
    ) -> None:
        self._settings_choice_box(
            parent,
            row,
            column,
            label,
            key,
            values,
            STRENGTH_CHOICES,
            lambda value: clean_space(value),
            "Kirjoita vahvuus ja valitse näkyvä ehdotus. "
            "Jos vahvuutta ei löydy, voit lisätä kirjoittamasi oman vahvuuden.",
            height=PROFILE_SELECTION_LIST_HEIGHT,
        )

    def _settings_occupation_box(
        self,
        parent: Any,
        row: int,
        column: int,
        label: str,
        key: str,
        values: Iterable[Any],
    ) -> None:
        self._settings_choice_box(
            parent,
            row,
            column,
            label,
            key,
            values,
            OCCUPATION_CHOICES,
            normalize_occupation_choice,
            "Kirjoita työtehtävä ja valitse näkyvä ehdotus 481 Suomessa "
            "käytössä olevasta ammattiluokasta. Jos tehtävää ei löydy, "
            "voit lisätä kirjoittamasi oman tehtävänimikkeen.",
            height=PROFILE_SELECTION_LIST_HEIGHT,
        )

    def _settings_excluded_phrase_box(
        self,
        parent: Any,
        row: int,
        column: int,
        label: str,
        key: str,
        values: Iterable[Any],
    ) -> None:
        self._settings_choice_box(
            parent,
            row,
            column,
            label,
            key,
            values,
            EXCLUDED_PHRASE_CHOICES,
            normalize_excluded_phrase,
            "Valitse jokin nykyisistä ilmauksista tai kirjoita oma "
            "poissulkeva ilmaus. Valmiita ehdotuksia ei lisätä nykyisten lisäksi.",
            height=PROFILE_SELECTION_LIST_HEIGHT,
        )

    def _build_profile_settings(self, content: Any) -> None:
        profile = self.config["profile"]
        content.columnconfigure(0, weight=1)
        content.columnconfigure(1, weight=1)
        self.ttk.Label(
            content,
            text="Valitse sopivat arvot luetteloista tai lisää oma arvo.",
            style="Help.TLabel",
            wraplength=760,
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))

        lists = self.ttk.Frame(content)
        lists.grid(row=1, column=0, columnspan=2, sticky="nsew")
        lists.columnconfigure(0, weight=1)
        lists.columnconfigure(1, weight=1)
        self._settings_location_box(
            lists,
            0,
            0,
            "Parhaat sijainnit",
            "profile.preferred_locations",
            profile.get("preferred_locations", []),
        )
        self._settings_location_box(
            lists,
            1,
            0,
            "Muut sopivat sijainnit",
            "profile.acceptable_locations",
            profile.get("acceptable_locations", []),
        )
        self._settings_occupation_box(
            lists,
            2,
            0,
            "Kiinnostavat työtehtävät",
            "profile.roles",
            profile.get("roles", []),
        )
        self._settings_strength_box(
            lists,
            3,
            0,
            "Vahvuudet",
            "profile.strengths",
            profile.get("strengths", []),
        )
        self._settings_excluded_phrase_box(
            lists,
            4,
            0,
            "Poissulkevat ilmaukset",
            "profile.excluded_phrases",
            profile.get("excluded_phrases", []),
        )

    def _build_search_settings(self, parent: Any) -> None:
        app = self.config["app"]
        parent.columnconfigure(0, weight=1)

        search_frame = self.ttk.LabelFrame(
            parent,
            text="Työpaikkojen haku",
            padding=16,
        )
        search_frame.grid(row=0, column=0, sticky="new")
        search_frame.columnconfigure(0, weight=1)
        self._settings_spinbox(
            search_frame,
            0,
            "Pienin sopivaksi laskettava pistemäärä",
            "app.minimum_score",
            app.get("minimum_score", 38),
            0,
            100,
        )
        self._settings_spinbox(
            search_frame,
            1,
            "Kuinka monen päivän työpaikat näytetään",
            "app.days_to_show",
            app.get("days_to_show", 60),
            1,
            3650,
        )
        self._settings_spinbox(
            search_frame,
            2,
            "Kaksoiskappaleiden vertailuaika päivinä",
            "app.duplicate_window_days",
            app.get("duplicate_window_days", 60),
            1,
            3650,
        )
        self._settings_spinbox(
            search_frame,
            3,
            "Verkkopyynnön aikakatkaisu sekunteina",
            "app.request_timeout_seconds",
            app.get("request_timeout_seconds", 25),
            5,
            120,
        )
        self._settings_spinbox(
            search_frame,
            4,
            "Enimmäismäärä ilmoituksia lähdettä kohden",
            "app.maximum_details_per_source",
            app.get("maximum_details_per_source", 80),
            1,
            500,
        )

    def _build_qualification_settings(self, parent: Any) -> None:
        profile = self.config["profile"]
        states = tuple(QUALIFICATION_STATE_LABELS.values())
        current = profile.get("qualifications", {})
        parent.columnconfigure(0, weight=1)
        self.ttk.Label(
            parent,
            text="Pätevyydet ja kortit",
            style="Section.TLabel",
        ).grid(row=0, column=0, sticky="w")
        self.ttk.Label(
            parent,
            text=(
                "Valitse jokaiselle kortille tai pätevyydelle Kyllä, Ei tai "
                "En tiedä. Valintoja käytetään työpaikkojen pisteytyksessä."
            ),
            style="Help.TLabel",
            wraplength=820,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(4, 12))

        for group_row, (group_name, qualifications) in enumerate(
            QUALIFICATION_GROUPS,
            start=2,
        ):
            group = self.ttk.LabelFrame(parent, text=group_name, padding=14)
            group.grid(row=group_row, column=0, sticky="ew", pady=(0, 14))
            group.columnconfigure(0, weight=1)
            group.columnconfigure(1, weight=1)
            group.columnconfigure(2, weight=1)
            group.columnconfigure(3, weight=1)
            for index, (key, label) in enumerate(qualifications):
                column_group = index % 2
                row = index // 2
                label_column = column_group * 2
                self.ttk.Label(group, text=label).grid(
                    row=row,
                    column=label_column,
                    sticky="w",
                    padx=(0, 10),
                    pady=6,
                )
                variable = self.tk.StringVar(
                    value=QUALIFICATION_STATE_LABELS.get(
                        current.get(key, "unknown"),
                        "En tiedä",
                    )
                )
                self.settings_qualification_vars[key] = variable
                self.ttk.Combobox(
                    group,
                    textvariable=variable,
                    values=states,
                    state="readonly",
                    width=12,
                ).grid(
                    row=row,
                    column=label_column + 1,
                    sticky="ew",
                    padx=(0, 18) if column_group == 0 else 0,
                    pady=6,
                )

    def _build_source_settings(self, content: Any) -> None:
        content.columnconfigure(0, weight=1)
        controls = self.ttk.Frame(content)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self.ttk.Label(
            controls,
            text="Työpaikkalähteet",
            style="Section.TLabel",
        ).pack(side="left")
        self._rounded_button(
            controls,
            text="Poista kaikki valinnat",
            command=lambda: self._set_all_settings_sources(False),
            settings_control=True,
        ).pack(side="right", padx=(5, 0))
        self.ttk.Label(
            content,
            text=(
                "Rajaa luettelo tehtäväalan mukaan ja ota käyttöön vain lähteet, "
                "jotka haluat tarkistaa. Uusia lähteitä ei oteta automaattisesti "
                "käyttöön."
            ),
            style="Help.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(0, 12))

        filter_row = self.ttk.Frame(content)
        filter_row.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self.ttk.Label(filter_row, text="Näytä tehtäväala:").pack(
            side="left",
            padx=(0, 8),
        )
        self.settings_source_filter_var = self.tk.StringVar(
            value=SOURCE_FILTER_ALL
        )
        filter_box = self.ttk.Combobox(
            filter_row,
            textvariable=self.settings_source_filter_var,
            values=(SOURCE_FILTER_ALL, *SOURCE_JOB_CATEGORIES),
            state="readonly",
            width=31,
        )
        filter_box.pack(side="left")
        filter_box.bind(
            "<<ComboboxSelected>>",
            self._filter_settings_sources,
        )
        self._rounded_button(
            filter_row,
            text="Poista näkyvät",
            command=lambda: self._set_visible_settings_sources(False),
            settings_control=True,
        ).pack(side="right", padx=(5, 0))
        self._rounded_button(
            filter_row,
            text="Valitse näkyvät",
            command=lambda: self._set_visible_settings_sources(True),
            primary=True,
            settings_control=True,
        ).pack(side="right", padx=(5, 0))

        self.settings_source_status_var = self.tk.StringVar()
        self.ttk.Label(
            content,
            textvariable=self.settings_source_status_var,
            style="Help.TLabel",
        ).grid(row=3, column=0, sticky="w", pady=(0, 8))

        for row, source in enumerate(self.config["sources"], start=4):
            source_frame = self.ttk.Frame(content, padding=(4, 7))
            source_frame.grid(row=row, column=0, sticky="ew")
            source_frame.columnconfigure(0, weight=1)
            variable = self.tk.BooleanVar(value=bool(source.get("enabled", True)))
            self.settings_source_vars.append(variable)
            categories = source_job_categories(source)
            self.settings_source_entries.append(
                {
                    "frame": source_frame,
                    "variable": variable,
                    "categories": categories,
                }
            )
            self._themed_checkbutton(
                source_frame,
                text=source.get("name", "Nimetön lähde"),
                variable=variable,
                command=self._update_settings_source_status,
                settings_control=True,
            ).grid(row=0, column=0, sticky="w")
            self.ttk.Label(
                source_frame,
                text=(
                    f"{' · '.join(categories)}\n"
                    f"{source.get('type', 'lähde')} · {source.get('url', '')}"
                ),
                style="Help.TLabel",
                wraplength=820,
                justify="left",
            ).grid(row=1, column=0, sticky="w", padx=(34, 0), pady=(2, 0))
        self._filter_settings_sources()

    def _set_all_settings_sources(self, enabled: bool) -> None:
        for variable in self.settings_source_vars:
            variable.set(enabled)
        self._update_settings_source_status()

    def _visible_source_entry(self, entry: dict[str, Any]) -> bool:
        selected = (
            self.settings_source_filter_var.get()
            if self.settings_source_filter_var is not None
            else SOURCE_FILTER_ALL
        )
        return (
            selected == SOURCE_FILTER_ALL
            or selected in entry.get("categories", ())
        )

    def _filter_settings_sources(self, event: Any | None = None) -> None:
        del event
        for entry in self.settings_source_entries:
            frame = entry["frame"]
            if self._visible_source_entry(entry):
                frame.grid()
            else:
                frame.grid_remove()
        self._update_settings_source_status()

    def _set_visible_settings_sources(self, enabled: bool) -> None:
        for entry in self.settings_source_entries:
            if self._visible_source_entry(entry):
                entry["variable"].set(enabled)
        self._update_settings_source_status()

    def _update_settings_source_status(self) -> None:
        if self.settings_source_status_var is None:
            return
        try:
            enabled_count = sum(
                bool(variable.get())
                for variable in self.settings_source_vars
            )
            visible_count = sum(
                self._visible_source_entry(entry)
                for entry in self.settings_source_entries
            )
            self.settings_source_status_var.set(
                f"Käytössä {enabled_count}/{len(self.settings_source_vars)} lähdettä"
                f" · Näkyvissä {visible_count}"
            )
        except self.tk.TclError:
            return

    def _show_settings_tab(self, name: str) -> None:
        frame = self.settings_tab_frames.get(name)
        if frame is None:
            return
        frame.tkraise()
        for tab_name, button in self.settings_tab_buttons.items():
            button.set_selected(tab_name == name)

    def open_settings(self) -> None:
        try:
            if self.settings_window is not None and self.settings_window.winfo_exists():
                self.settings_window.lift()
                self.settings_window.focus_force()
                return
        except self.tk.TclError:
            self.settings_window = None

        self.settings_vars = {}
        self.settings_texts = {}
        self.settings_selection_lists = {}
        self.settings_qualification_vars = {}
        self.settings_source_vars = []
        self.settings_source_entries = []
        self.settings_source_filter_var = None
        self.settings_source_status_var = None
        self.settings_native_widgets = []
        self.settings_custom_controls = []
        self.settings_tab_buttons = {}
        self.settings_tab_frames = {}

        window = self.tk.Toplevel(self.root)
        self.settings_window = window
        self._apply_application_icon(window)
        window.title(f"Asetukset – {APP_NAME} {APP_VERSION}")
        window.geometry("960x720")
        window.minsize(820, 620)
        window.configure(bg=self.palette["background"])
        window.transient(self.root)
        window.protocol("WM_DELETE_WINDOW", self._close_settings)

        body = self.ttk.Frame(window, padding=(22, 18))
        body.pack(fill="both", expand=True)
        header = self.ttk.Frame(body)
        header.pack(fill="x", pady=(0, 12))
        header.columnconfigure(0, weight=1)

        heading = self.ttk.Frame(header)
        heading.grid(row=0, column=0, sticky="nw")
        self.ttk.Label(
            heading,
            text="Asetukset",
            style="Title.TLabel",
        ).pack(anchor="w")
        self.ttk.Label(
            heading,
            text="Muokkaa sovelluksen toimintaa ilman JSON-koodia.",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(3, 0))

        save_area = self.ttk.Frame(header)
        save_area.grid(row=0, column=1, sticky="ne", padx=(18, 0))
        self._rounded_button(
            save_area,
            text="Tallenna asetukset",
            command=self._save_settings,
            primary=True,
            minimum_width=158,
            settings_control=True,
        ).pack(anchor="e")
        self.ttk.Label(
            save_area,
            text="Tallenna ennen sivun sulkemista.",
            style="Help.TLabel",
        ).pack(anchor="e", pady=(5, 0))

        tab_bar = self.ttk.Frame(body, height=52)
        tab_bar.pack(fill="x", pady=(0, 10))
        tab_bar.pack_propagate(False)

        content_host = self.ttk.Frame(body)
        content_host.pack(fill="both", expand=True)
        content_host.rowconfigure(0, weight=1)
        content_host.columnconfigure(0, weight=1)

        profile_panel, profile_content = self._scrollable_settings_panel(
            content_host
        )
        profile_panel.grid(row=0, column=0, sticky="nsew")
        self._build_profile_settings(profile_content)

        search_panel = self.ttk.Frame(content_host, padding=20)
        search_panel.grid(row=0, column=0, sticky="nsew")
        self._build_search_settings(search_panel)

        qualification_panel, qualification_content = (
            self._scrollable_settings_panel(content_host)
        )
        qualification_panel.grid(row=0, column=0, sticky="nsew")
        self._build_qualification_settings(qualification_content)

        source_panel, source_content = self._scrollable_settings_panel(
            content_host
        )
        source_panel.grid(row=0, column=0, sticky="nsew")
        self._build_source_settings(source_content)

        self.settings_tab_frames = {
            "Profiili": profile_panel,
            "Haku": search_panel,
            "Pätevyydet ja kortit": qualification_panel,
            "Työpaikkalähteet": source_panel,
        }
        for name in self.settings_tab_frames:
            button = self._rounded_button(
                tab_bar,
                text=name,
                command=lambda tab_name=name: self._show_settings_tab(tab_name),
                tab=True,
                selected=name == "Profiili",
                settings_control=True,
            )
            button.pack(side="left", anchor="s", padx=3)
            self.settings_tab_buttons[name] = button
        self._show_settings_tab("Profiili")

        self._refresh_settings_native_colours()
        self._apply_windows_titlebar_theme()
        window.after(250, self._apply_windows_titlebar_theme)
        window.grab_set()
        window.focus_force()

    def _save_settings(self) -> None:
        try:
            values = {
                key: variable.get()
                for key, variable in self.settings_vars.items()
            }
            for key, text in self.settings_texts.items():
                values[key] = text.get("1.0", "end-1c")
            for key, selection_list in self.settings_selection_lists.items():
                values[key] = list(selection_list.get(0, "end"))
            qualification_by_label = {
                label: state
                for state, label in QUALIFICATION_STATE_LABELS.items()
            }
            values["profile.qualifications"] = {
                name: qualification_by_label.get(variable.get(), "unknown")
                for name, variable in self.settings_qualification_vars.items()
            }
            updated = update_config_from_settings(
                self.config,
                values,
                [variable.get() for variable in self.settings_source_vars],
            )
            write_config_file(updated)
            self.config = updated
            self.refresh_jobs()
            self.status_text.set("Asetukset tallennettu")
            self._close_settings()
            self.messagebox.showinfo(
                APP_NAME,
                "Asetukset tallennettiin onnistuneesti.",
                parent=self.root,
            )
        except (OSError, ValueError) as exc:
            self.messagebox.showerror(
                "Asetuksia ei voitu tallentaa",
                str(exc),
                parent=self.settings_window or self.root,
            )

    def selected_id(self) -> str | None:
        selection = self.tree.selection()
        return selection[0] if selection else None

    def toggle_deadline_sort(self) -> None:
        if self.deadline_latest_first is None:
            self.deadline_latest_first = False
        else:
            self.deadline_latest_first = not self.deadline_latest_first
        self.score_highest_first = None
        arrow = "↓" if self.deadline_latest_first else "↑"
        self.tree.heading("score", text="Pisteet")
        self.tree.heading("deadline", text=f"{DEADLINE_HEADING} {arrow}")
        self.refresh_jobs()

    def toggle_score_sort(self) -> None:
        if self.score_highest_first is None:
            self.score_highest_first = True
        else:
            self.score_highest_first = not self.score_highest_first
        self.deadline_latest_first = None
        arrow = "↓" if self.score_highest_first else "↑"
        self.tree.heading("score", text=f"Pisteet {arrow}")
        self.tree.heading("deadline", text=DEADLINE_HEADING)
        self.refresh_jobs()

    def refresh_jobs(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        database = JobDatabase()
        try:
            minimum = max(0, int(self.config["app"].get("minimum_score", 38)) - 12)
            days = int(self.config["app"].get("days_to_show", 60))
            rows = database.list_jobs(
                minimum_score=minimum,
                days=days,
                include_ignored=self.show_ignored.get(),
            )
            rows = [
                row
                for row in rows
                if job_matches_location_filter(row, self.config)
            ]
            if self.score_highest_first is not None:
                rows = sort_jobs_by_score(
                    rows,
                    highest_first=self.score_highest_first,
                )
            elif self.deadline_latest_first is not None:
                rows = sort_jobs_by_deadline(
                    rows,
                    latest_first=self.deadline_latest_first,
                )
            status_names = {
                "new": "Uusi",
                "republished": "Uudelleen julkaistu",
                "seen": "Katsottu",
                "applied": "Haettu",
                "ignored": "Poistettu",
            }
            for row in rows:
                expired = deadline_has_passed(row["deadline"])
                visible_status = status_names.get(row["status"], row["status"])
                if expired:
                    tag = "expired"
                    visible_status = f"{visible_status} · Päättynyt"
                elif row["status"] == "republished":
                    tag = "republished"
                elif row["status"] == "applied":
                    tag = "applied"
                elif row["status"] == "ignored":
                    tag = "ignored"
                elif row["score"] >= 65:
                    tag = "good"
                else:
                    tag = "medium"
                self.tree.insert(
                    "",
                    "end",
                    iid=row["fingerprint"],
                    values=(
                        f"{row['score']}/100",
                        visible_status,
                        row["title"],
                        row["company"],
                        row["location"] or "Tarkista",
                        format_job_date(row["deadline"]) or "–",
                    ),
                    tags=(tag,),
                )
            sort_note = ""
            if self.score_highest_first is True:
                sort_note = " · eniten pisteitä ensin"
            elif self.score_highest_first is False:
                sort_note = " · vähiten pisteitä ensin"
            elif self.deadline_latest_first is True:
                sort_note = " · myöhemmin päättyvät ensin"
            elif self.deadline_latest_first is False:
                sort_note = " · aikaisimmin päättyvät ensin"
            self.status_text.set(f"Näytetään {len(rows)} työpaikkaa{sort_note}")
        finally:
            database.close()

    def start_scan(self) -> None:
        self.scan_button.configure(state="disabled")
        self.progress.start(12)
        self.status_text.set("Aloitetaan tarkistus…")

        def worker() -> None:
            try:
                result = JobScanner(
                    self.config,
                    progress=lambda message: self.events.put(("progress", message)),
                ).scan()
                self.events.put(("done", result))
            except Exception as exc:
                logging.exception("Tarkistus epäonnistui")
                self.events.put(("error", f"{exc}\n\n{traceback.format_exc(limit=2)}"))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "progress":
                    self.status_text.set(str(payload))
                elif kind == "done":
                    self.progress.stop()
                    self.scan_button.configure(state="normal")
                    self.refresh_jobs()
                    result: ScanResult = payload
                    message = (
                        f"Tarkistus valmis.\n\n"
                        f"Löytyi yhteensä {result.found_count} ilmoitusta.\n"
                        f"Uusia sopivia paikkoja: {len(result.new_matches)}."
                    )
                    if result.errors:
                        message += (
                            f"\n\n{len(result.errors)} lähdettä tai toimintoa antoi virheen. "
                            "Muut lähteet tarkistettiin normaalisti."
                        )
                    if self.messagebox.askyesno(
                        APP_NAME, message + "\n\nAvataanko kooste?"
                    ):
                        open_file(result.report_path)
                elif kind == "error":
                    self.progress.stop()
                    self.scan_button.configure(state="normal")
                    self.status_text.set("Tarkistus epäonnistui")
                    self.messagebox.showerror(APP_NAME, str(payload))
        except queue.Empty:
            pass
        self.root.after(150, self._poll_events)

    def _row(self) -> sqlite3.Row | None:
        fingerprint = self.selected_id()
        if not fingerprint:
            self.messagebox.showinfo(APP_NAME, "Valitse ensin työpaikka.")
            return None
        database = JobDatabase()
        try:
            return database.get_job(fingerprint)
        finally:
            database.close()

    def open_selected(self) -> None:
        row = self._row()
        if row:
            webbrowser.open(row["url"])

    def show_source_links(self, row: sqlite3.Row) -> None:
        links = JobDatabase._read_links(row["links_json"])
        if not links:
            webbrowser.open(row["url"])
            return
        window = self.tk.Toplevel(self.root)
        window.title(f"Lähdelinkit – {row['title']}")
        window.configure(bg=self.palette["background"])
        frame = self.ttk.Frame(window, padding=18)
        frame.pack(fill="both", expand=True)
        self.ttk.Label(
            frame,
            text="Sama ilmoitus löytyi näistä lähteistä:",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", pady=(0, 10))
        for item in links:
            label = item.get("source") or "Avaa ilmoitus"
            self.ttk.Button(
                frame,
                text=label,
                command=lambda url=item["url"]: webbrowser.open(url),
            ).pack(fill="x", pady=3)

    def show_selected_source_links(self) -> None:
        row = self._row()
        if row:
            self.show_source_links(row)

    def _close_applied_jobs(self) -> None:
        window = self.applied_window
        self.applied_window = None
        self.applied_tree = None
        self.applied_status_text = None
        for control in self.applied_custom_controls:
            if control in self.custom_controls:
                self.custom_controls.remove(control)
        self.applied_custom_controls = []
        if window is None:
            return
        try:
            window.destroy()
        except self.tk.TclError:
            pass

    def _applied_selected_id(self) -> str | None:
        if self.applied_tree is None:
            return None
        try:
            selection = self.applied_tree.selection()
        except self.tk.TclError:
            return None
        return selection[0] if selection else None

    def open_applied_selected(self) -> None:
        fingerprint = self._applied_selected_id()
        if not fingerprint:
            self.messagebox.showinfo(
                APP_NAME,
                "Valitse ensin haettu työpaikka.",
                parent=self.applied_window or self.root,
            )
            return
        database = JobDatabase()
        try:
            row = database.get_job(fingerprint)
        finally:
            database.close()
        if row:
            webbrowser.open(row["url"])

    def refresh_applied_jobs(self) -> None:
        tree = self.applied_tree
        if tree is None:
            return
        try:
            for item in tree.get_children():
                tree.delete(item)
        except self.tk.TclError:
            return

        database = JobDatabase()
        try:
            rows = database.list_applied_jobs()
        finally:
            database.close()

        for row in rows:
            tree.insert(
                "",
                "end",
                iid=row["fingerprint"],
                values=(
                    row["company"] or "Tuntematon työnantaja",
                    row["title"],
                    format_job_date(row["applied_at"]) or "Ei tallennettu",
                ),
                tags=("applied",),
            )
        tree.tag_configure(
            "applied",
            background=self.palette["applied_background"],
            foreground=self.palette["applied_foreground"],
        )
        if self.applied_status_text is not None:
            self.applied_status_text.set(
                f"Näytetään {len(rows)} haettua työpaikkaa"
            )

    def open_applied_jobs(self) -> None:
        try:
            if self.applied_window is not None and self.applied_window.winfo_exists():
                self.refresh_applied_jobs()
                self.applied_window.lift()
                self.applied_window.focus_force()
                return
        except self.tk.TclError:
            self.applied_window = None

        window = self.tk.Toplevel(self.root)
        self.applied_window = window
        self._apply_application_icon(window)
        window.title(f"Haetut työpaikat – {APP_NAME} {APP_VERSION}")
        window.geometry("820x540")
        window.minsize(680, 420)
        window.configure(bg=self.palette["background"])
        window.transient(self.root)
        window.protocol("WM_DELETE_WINDOW", self._close_applied_jobs)

        body = self.ttk.Frame(window, padding=(22, 18))
        body.pack(fill="both", expand=True)

        self.ttk.Label(
            body,
            text="Haetut työpaikat",
            style="Title.TLabel",
        ).pack(anchor="w")
        self.ttk.Label(
            body,
            text=(
                "Näet tässä työnantajan, työtehtävän ja päivän, jolloin paikka "
                "merkittiin haetuksi."
            ),
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(4, 14))

        toolbar = self.ttk.Frame(body)
        toolbar.pack(fill="x", pady=(0, 10))
        open_button = self._rounded_button(
            toolbar,
            text="Avaa ilmoitus",
            command=self.open_applied_selected,
        )
        self.applied_custom_controls.append(open_button)
        open_button.pack(side="left")
        close_button = self._rounded_button(
            toolbar,
            text="Sulje",
            command=self._close_applied_jobs,
        )
        self.applied_custom_controls.append(close_button)
        close_button.pack(side="right")

        table_frame = self.ttk.Frame(body, style="Card.TFrame", padding=1)
        table_frame.pack(fill="both", expand=True)
        columns = ("company", "title", "applied_at")
        tree = self.ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        self.applied_tree = tree
        for column, heading, width in (
            ("company", "Työnantaja", 230),
            ("title", "Työtehtävä", 390),
            ("applied_at", "Hakupäivä", 130),
        ):
            tree.heading(column, text=heading)
            tree.column(
                column,
                width=width,
                minwidth=100,
                anchor="center" if column == "applied_at" else "w",
            )
        scrollbar = self.ttk.Scrollbar(
            table_frame,
            orient="vertical",
            command=tree.yview,
        )
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        tree.bind("<Double-1>", lambda event: self.open_applied_selected())
        tree.bind("<Return>", lambda event: self.open_applied_selected())

        self.applied_status_text = self.tk.StringVar(value="")
        self.ttk.Label(
            body,
            textvariable=self.applied_status_text,
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(10, 0))

        self.refresh_applied_jobs()
        if sys.platform.startswith("win"):
            self.root.after(50, self._apply_windows_titlebar_theme)

    def set_status(self, fingerprint: str, status: str) -> None:
        database = JobDatabase()
        try:
            database.set_status(fingerprint, status)
        finally:
            database.close()
        self.refresh_jobs()
        try:
            if self.applied_window is not None and self.applied_window.winfo_exists():
                self.refresh_applied_jobs()
        except self.tk.TclError:
            self.applied_window = None

    def set_selected_status(self, status: str) -> None:
        fingerprint = self.selected_id()
        if not fingerprint:
            self.messagebox.showinfo(APP_NAME, "Valitse ensin työpaikka.")
            return
        self.set_status(fingerprint, status)

    def _mark_seen(self, event: Any = None) -> None:
        fingerprint = self.selected_id()
        if not fingerprint:
            return
        database = JobDatabase()
        try:
            row = database.get_job(fingerprint)
            if row and row["status"] in {"new", "republished"}:
                database.set_status(fingerprint, "seen")
        finally:
            database.close()

    def run(self) -> None:
        self.root.mainloop()


def run_cli_scan(config: dict[str, Any]) -> int:
    result = JobScanner(config).scan()
    print()
    print(f"Löytyi yhteensä: {result.found_count}")
    print(f"Tallennettiin: {result.stored_count}")
    print(f"Uusia sopivia: {len(result.new_matches)}")
    print(f"Raportti: {result.report_path}")
    if result.errors:
        print("Virheet:")
        for error in result.errors:
            print(f"- {error}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--scan", action="store_true", help="Tarkista työpaikat ilman GUI:ta")
    parser.add_argument(
        "--check-config", action="store_true", help="Tarkista config.json ja lopeta"
    )
    args = parser.parse_args()

    configure_logging()
    try:
        config = load_config()
    except ValueError as exc:
        if args.scan or args.check_config:
            print(f"ASETUSVIRHE: {exc}", file=sys.stderr)
        else:
            try:
                import tkinter as tk
                from tkinter import messagebox

                root = tk.Tk()
                root.withdraw()
                messagebox.showerror(f"{APP_NAME} – asetusvirhe", str(exc))
                root.destroy()
            except Exception:
                print(f"ASETUSVIRHE: {exc}", file=sys.stderr)
        return 2

    if args.check_config:
        print("config.json on kunnossa.")
        return 0
    if args.scan:
        return run_cli_scan(config)

    try:
        TyopaikkatutkaGUI(config).run()
        return 0
    except Exception as exc:
        logging.exception("Käyttöliittymän käynnistys epäonnistui")
        print(f"Käyttöliittymän käynnistys epäonnistui: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
