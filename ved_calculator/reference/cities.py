"""Russian destination city normalisation (Latin and Cyrillic spellings)."""

from __future__ import annotations

import re

_CITY_ALIASES: dict[str, str] = {
    "moscow": "moscow",
    "москва": "moscow",
    "msk": "moscow",
    "мск": "moscow",
    "tyumen": "tyumen",
    "тюмень": "tyumen",
    "yekaterinburg": "yekaterinburg",
    "ekaterinburg": "yekaterinburg",
    "екатеринбург": "yekaterinburg",
    "novosibirsk": "novosibirsk",
    "новосибирск": "novosibirsk",
    "chelyabinsk": "chelyabinsk",
    "челябинск": "chelyabinsk",
    "omsk": "omsk",
    "омск": "omsk",
    "kazan": "kazan",
    "казань": "kazan",
    "saint_petersburg": "saint_petersburg",
    "saint-petersburg": "saint_petersburg",
    "st_petersburg": "saint_petersburg",
    "st.petersburg": "saint_petersburg",
    "st._petersburg": "saint_petersburg",
    "petersburg": "saint_petersburg",
    "spb": "saint_petersburg",
    "спб": "saint_petersburg",
    "санкт_петербург": "saint_petersburg",
    "санкт-петербург": "saint_petersburg",
    "петербург": "saint_petersburg",
    "krasnodar": "krasnodar",
    "краснодар": "krasnodar",
    "samara": "samara",
    "самара": "samara",
    "krasnoyarsk": "krasnoyarsk",
    "красноярск": "krasnoyarsk",
}

_WS = re.compile(r"[\s]+")


def normalize_city(name: str) -> str:
    """Return the canonical city key (``'tyumen'``) for any known spelling.

    Unknown cities are returned as a lower-cased slug so that they can be used
    as a stable key and matched against a fallback rate.
    """
    slug = _WS.sub("_", name.strip().casefold().replace("ё", "е"))
    return _CITY_ALIASES.get(slug, _CITY_ALIASES.get(slug.replace("-", "_"), slug))


def city_title(key: str) -> str:
    return " ".join(part.capitalize() for part in key.replace("_", " ").split())


__all__ = ["city_title", "normalize_city"]
