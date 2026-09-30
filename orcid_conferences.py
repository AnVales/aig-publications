#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ORCID Conference Publications Pipeline
=======================================

Flujo:

    researchers1.json
          |
          v
       ORCID API
          |
          v
   normalización de autores
          |
          +----> author_registry.json
          |
          +----> author_overrides.json
          |
          v
   normalización publicaciones
          |
          v
   deduplicación publicaciones
          |
          +----> publication_review.json
          |
          v
   conference_publications.json
          |
          +----> conference_publications.bib
          +----> conference_publications.html
          +----> author_variants.json
          +----> author_review.json
          +----> conference_publications_excluded.json

La fuente de verdad NO es el .bib.
La información persistente de autores se guarda en:

    author_registry.json
    author_overrides.json

Los casos dudosos de publicaciones se guardan en:

    publication_review.json
"""

import os
import re
import json
import html
import unicodedata
import hashlib
import difflib
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


# ============================================================================
# CONFIGURACIÓN
# ============================================================================

INPUT_FILE = "researchers1.json"

OUTPUT_JSON = "conference_publications.json"
OUTPUT_ALL = "conference_publications_all_orcid.json"
OUTPUT_EXCLUDED = "conference_publications_excluded.json"
OUTPUT_HTML = "conference_publications.html"
OUTPUT_BIB = "conference_publications.bib"

OUTPUT_AUTHOR_VARIANTS = "author_variants.json"
OUTPUT_AUTHOR_REVIEW = "author_review.json"
OUTPUT_AUTHOR_REGISTRY = "author_registry.json"
OUTPUT_AUTHOR_OVERRIDES = "author_overrides.json"

OUTPUT_PUBLICATION_REVIEW = "publication_review.json"

API_BASE = "https://pub.orcid.org/v3.0"

ROWS_PER_PAGE = 100
MAX_PAGES = 1000
REQUEST_TIMEOUT = 30

# Deduplicación difusa.
FUZZY_TITLE_THRESHOLD = 0.96
MIN_AUTHOR_OVERLAP_FOR_FUZZY = 0.50

# IMPORTANTE:
# False = los duplicados difusos solo se mandan a revisión.
# True  = además se fusionan automáticamente.
AUTO_MERGE_FUZZY = False

# Si quieres que la clasificación de congresos sea más/menos restrictiva.
CONFERENCE_KEYWORDS = [
    "conference",
    "proceedings",
    "symposium",
    "workshop",
    "congress",
    "meeting",
    "international conference",
    "annual meeting",
    "technical meeting",
    "conference proceedings",
    "proceedings of",
    "proc.",
    "conf.",
    "european conference",
    "international symposium",
]

EXCLUDE_KEYWORDS = [
    "journal",
    "review",
    "editorial",
    "book",
    "chapter",
    "thesis",
    "dissertation",
]

# ============================================================================
# ALIAS CONOCIDOS
# ============================================================================

# Estas equivalencias son explícitas.
#
# Es preferible NO meter aquí equivalencias dudosas.
# Las variantes no confirmadas aparecerán en author_review.json.
#
# La clave se normaliza automáticamente, por lo que no importa si lleva
# acentos o diferencias de mayúsculas.

AUTHOR_ALIASES = {
    "miguel-angel fernandez-torres":
        "Fernández-Torres, M.-A.",

    "miguel angel fernandez torres":
        "Fernández-Torres, M.-A.",

    "ivan gonzalez-diaz":
        "González-Díaz, I.",

    "ivan gonzalez diaz":
        "González-Díaz, I.",

    "fernando diaz-de-maria":
        "Díaz-de-María, F.",

    "fernando diaz de maria":
        "Díaz-de-María, F.",
}


# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("orcid_pipeline")


# ============================================================================
# UTILIDADES GENERALES
# ============================================================================

def clean_text(value: Any) -> str:
    """Convierte un valor cualquiera a texto limpio."""
    if value is None:
        return ""

    text = str(value)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def save_json(path: str, data: Any) -> None:
    """Guarda JSON con UTF-8 y formato legible."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
            sort_keys=False,
        )


def load_json(path: str, default: Any) -> Any:
    """Carga JSON o devuelve default si no existe."""
    if not os.path.exists(path):
        return default

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("No se pudo leer %s: %s", path, exc)
        return default


def normalize_unicode(text: str) -> str:
    """
    Normaliza Unicode y elimina diacríticos.

    Ejemplo:
        Fernández -> Fernandez
        María     -> Maria
    """
    text = unicodedata.normalize("NFKD", text)
    return "".join(
        c for c in text
        if not unicodedata.combining(c)
    )


def normalize_dashes(text: str) -> str:
    """Convierte diferentes tipos de guion en '-'."""
    replacements = {
        "‐": "-",
        "-": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        "―": "-",
        "﹘": "-",
        "﹣": "-",
        "－": "-",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    return text


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_key_text(text: str) -> str:
    """
    Normalización agresiva para comparar cadenas.
    """
    text = clean_text(text)
    text = normalize_dashes(text)
    text = normalize_unicode(text)
    text = text.lower()

    text = text.replace("’", "'")
    text = text.replace("`", "'")

    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = normalize_spaces(text)

    return text


def normalize_title(title: str) -> str:
    """
    Normaliza títulos para comparación.

    No se usa para mostrar el título final.
    """
    text = normalize_key_text(title)

    # Eliminamos algunos elementos que suelen cambiar entre fuentes.
    text = re.sub(r"\bdoi\b", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def normalize_orcid(orcid: Any) -> str:
    if not orcid:
        return ""

    text = clean_text(orcid)

    text = re.sub(
        r"^https?://orcid\.org/",
        "",
        text,
        flags=re.I,
    )

    text = text.rstrip("/")
    return text


def normalize_doi(doi: Any) -> str:
    if not doi:
        return ""

    text = clean_text(doi)

    text = re.sub(
        r"^https?://doi\.org/",
        "",
        text,
        flags=re.I,
    )

    text = re.sub(
        r"^doi:\s*",
        "",
        text,
        flags=re.I,
    )

    return text.strip().lower().rstrip(".")


def normalize_identifier(value: Any) -> str:
    return clean_text(value).lower()


def safe_get(obj: Any, *keys: Any, default: Any = None) -> Any:
    """
    Acceso seguro a estructuras JSON anidadas.
    """
    current = obj

    for key in keys:
        if current is None:
            return default

        if isinstance(current, dict):
            current = current.get(key, default)

        elif isinstance(current, list):
            try:
                current = current[int(key)]
            except (ValueError, IndexError, TypeError):
                return default

        else:
            return default

    return current


def first_non_empty(*values: Any) -> str:
    for value in values:
        value = clean_text(value)
        if value:
            return value
    return ""


# ============================================================================
# AUTORES
# ============================================================================

def canonicalize_author_display(name: str) -> str:
    """
    Limpia un nombre conservando una forma razonablemente legible.
    """
    name = clean_text(name)

    if not name:
        return ""

    name = normalize_dashes(name)

    # Quitamos ciertos prefijos accidentales.
    name = re.sub(
        r"^(author|authors)\s*:\s*",
        "",
        name,
        flags=re.I,
    )

    name = normalize_spaces(name)

    return name.strip(" ;,")


def author_alias_key(name: str) -> str:
    """
    Clave para buscar alias explícitos.
    """
    return normalize_key_text(name)


def author_name_parts(name: str) -> Tuple[str, str]:
    """
    Devuelve:

        surname, given

    Soporta:

        Pérez, Juan
        Juan Pérez
        Pérez, J.
        J. Pérez
    """
    name = canonicalize_author_display(name)

    if not name:
        return "", ""

    if "," in name:
        surname, given = name.split(",", 1)
        return (
            clean_text(surname),
            clean_text(given),
        )

    tokens = name.split()

    if len(tokens) == 1:
        return tokens[0], ""

    # Para nombres tipo:
    # Fernando Diaz-de-Maria
    # Miguel-Angel Fernandez-Torres
    #
    # el último token suele ser el apellido.
    surname = tokens[-1]
    given = " ".join(tokens[:-1])

    return surname, given


def initials_from_given(given: str) -> str:
    """
    Convierte nombres a iniciales normalizadas.

    Ejemplos:

        Fernando          -> f
        Miguel-Angel      -> ma
        M.-A.             -> ma
        M A               -> ma
        Ivan               -> i
    """
    given = clean_text(given)

    if not given:
        return ""

    given = normalize_dashes(given)
    given = normalize_unicode(given).lower()

    # Separar por espacios/guiones/puntuación.
    parts = re.findall(
        r"[a-z]+",
        given,
    )

    initials = ""

    for part in parts:
        if part:
            initials += part[0]

    return initials


def author_identity_key(name: str) -> str:
    """
    Genera una identidad aproximada basada en:

        apellido + iniciales

    Ejemplos:

        Díaz-de-María, F.
        Fernando Diaz-de-Maria

    -> diazdemaria|f

    y:

        Fernández-Torres, M.-A.
        Miguel-Angel Fernandez-Torres

    -> fernandeztorres|ma
    """
    surname, given = author_name_parts(name)

    surname_key = normalize_key_text(surname)
    surname_key = surname_key.replace(" ", "")

    initials = initials_from_given(given)

    if not surname_key:
        return ""

    return f"{surname_key}|{initials}"


def author_surname_key(name: str) -> str:
    surname, _ = author_name_parts(name)

    surname = normalize_key_text(surname)
    surname = surname.replace(" ", "")

    return surname


def names_are_likely_same(name1: str, name2: str) -> bool:
    """
    Determina si dos nombres probablemente representan a la misma persona.

    La comparación es conservadora.
    """
    a = canonicalize_author_display(name1)
    b = canonicalize_author_display(name2)

    if not a or not b:
        return False

    if normalize_key_text(a) == normalize_key_text(b):
        return True

    key_a = author_identity_key(a)
    key_b = author_identity_key(b)

    if key_a and key_a == key_b:
        return True

    return False


def normalize_author_name(
    name: str,
    orcid: str = "",
) -> str:
    """
    Aplica alias explícitos y limpieza básica.
    """
    name = canonicalize_author_display(name)

    if not name:
        return ""

    alias = AUTHOR_ALIASES.get(
        author_alias_key(name)
    )

    if alias:
        return alias

    return name


# ============================================================================
# REGISTRO PERSISTENTE DE AUTORES
# ============================================================================

def load_author_registry() -> Dict[str, Dict[str, Any]]:
    registry = load_json(
        OUTPUT_AUTHOR_REGISTRY,
        {},
    )

    if not isinstance(registry, dict):
        return {}

    return registry


def save_author_registry(
    registry: Dict[str, Dict[str, Any]]
) -> None:
    save_json(
        OUTPUT_AUTHOR_REGISTRY,
        registry,
    )


def load_author_overrides() -> Dict[str, Any]:
    overrides = load_json(
        OUTPUT_AUTHOR_OVERRIDES,
        {},
    )

    if not isinstance(overrides, dict):
        return {}

    return overrides


def save_author_overrides(
    overrides: Dict[str, Any]
) -> None:
    save_json(
        OUTPUT_AUTHOR_OVERRIDES,
        overrides,
    )


def next_author_id(
    registry: Dict[str, Dict[str, Any]]
) -> str:
    max_id = 0

    for record in registry.values():
        author_id = clean_text(
            record.get("author_id", "")
        )

        match = re.fullmatch(
            r"A(\d+)",
            author_id,
        )

        if match:
            max_id = max(
                max_id,
                int(match.group(1)),
            )

    return f"A{max_id + 1:05d}"


def override_for_author(
    name: str,
    orcid: str,
    overrides: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Busca una decisión manual.

    Prioridad:

        orcid:<ORCID>
        name:<normalized name>
    """
    orcid = normalize_orcid(orcid)

    if orcid:
        key = f"orcid:{orcid}"

        if key in overrides:
            value = overrides[key]

            if isinstance(value, str):
                return {
                    "canonical_name": value
                }

            if isinstance(value, dict):
                return value

    key = f"name:{author_alias_key(name)}"

    if key in overrides:
        value = overrides[key]

        if isinstance(value, str):
            return {
                "canonical_name": value
            }

        if isinstance(value, dict):
            return value

    return None


def find_registry_author(
    name: str,
    orcid: str,
    registry: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Busca primero por ORCID y luego por identidad de nombre.
    """
    orcid = normalize_orcid(orcid)

    if orcid:
        for record in registry.values():
            if normalize_orcid(
                record.get("orcid", "")
            ) == orcid:
                return record

    identity_key = author_identity_key(name)

    if identity_key:
        for record in registry.values():
            if record.get("identity_key") == identity_key:
                return record

            for variant in record.get(
                "variants",
                []
            ):
                if author_identity_key(variant) == identity_key:
                    return record

    return None


def register_author(
    name: str,
    orcid: str,
    researcher_name: str,
    researcher_orcid: str,
    registry: Dict[str, Dict[str, Any]],
    overrides: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Registra un autor y devuelve su representación canónica.

    Orden de prioridad:

        1. override manual
        2. registro persistente
        3. nombre del investigador ORCID si coincide
        4. nombre entrante
    """
    raw_name = canonicalize_author_display(name)
    orcid = normalize_orcid(orcid)
    researcher_orcid = normalize_orcid(researcher_orcid)

    if not raw_name and researcher_name:
        raw_name = canonicalize_author_display(
            researcher_name
        )

    if not raw_name:
        return {
            "name": "",
            "orcid": orcid,
            "author_id": "",
        }

    normalized_incoming = normalize_author_name(
        raw_name,
        orcid,
    )

    override = override_for_author(
        raw_name,
        orcid,
        overrides,
    )

    existing = find_registry_author(
        normalized_incoming,
        orcid,
        registry,
    )

    # ------------------------------------------------------------
    # Determinar nombre canónico.
    # ------------------------------------------------------------

    canonical_name = ""

    if override:
        canonical_name = first_non_empty(
            override.get("canonical_name"),
            override.get("name"),
            normalized_incoming,
        )

    elif existing:
        canonical_name = first_non_empty(
            existing.get("canonical_name"),
            normalized_incoming,
        )

    elif (
        researcher_orcid
        and orcid
        and researcher_orcid == orcid
        and researcher_name
    ):
        canonical_name = canonicalize_author_display(
            researcher_name
        )

    else:
        canonical_name = normalized_incoming

    canonical_name = canonicalize_author_display(
        canonical_name
    )

    # ------------------------------------------------------------
    # Crear o actualizar registro.
    # ------------------------------------------------------------

    if existing:
        author_id = existing["author_id"]

        existing["canonical_name"] = canonical_name

        if orcid:
            existing["orcid"] = orcid

        identity_key = author_identity_key(
            canonical_name
        )

        if identity_key:
            existing["identity_key"] = identity_key

        variants = existing.setdefault(
            "variants",
            []
        )

        if raw_name and raw_name not in variants:
            variants.append(raw_name)

        if normalized_incoming:
            if normalized_incoming not in variants:
                variants.append(normalized_incoming)

        researchers = existing.setdefault(
            "researchers",
            []
        )

        researcher_info = {
            "name": clean_text(researcher_name),
            "orcid": researcher_orcid,
        }

        if researcher_info not in researchers:
            researchers.append(
                researcher_info
            )

        return {
            "name": canonical_name,
            "orcid": existing.get("orcid", orcid),
            "author_id": author_id,
        }

    author_id = next_author_id(registry)

    identity_key = author_identity_key(
        canonical_name
    )

    record = {
        "author_id": author_id,
        "canonical_name": canonical_name,
        "orcid": orcid,
        "identity_key": identity_key,
        "variants": [],
        "researchers": [],
    }

    if raw_name:
        record["variants"].append(raw_name)

    if (
        normalized_incoming
        and normalized_incoming != raw_name
    ):
        record["variants"].append(
            normalized_incoming
        )

    researcher_info = {
        "name": clean_text(researcher_name),
        "orcid": researcher_orcid,
    }

    if researcher_info["name"] or researcher_info["orcid"]:
        record["researchers"].append(
            researcher_info
        )

    registry[author_id] = record

    return {
        "name": canonical_name,
        "orcid": orcid,
        "author_id": author_id,
    }


def deduplicate_authors(
    author_records: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Elimina autores repetidos dentro de una publicación.

    Primero usa ORCID.
    Después identity_key.
    """
    result = []

    seen_orcids = set()
    seen_identities = set()

    for record in author_records:
        name = clean_text(
            record.get("name", "")
        )
        orcid = normalize_orcid(
            record.get("orcid", "")
        )
        author_id = clean_text(
            record.get("author_id", "")
        )

        if not name:
            continue

        if orcid:
            if orcid in seen_orcids:
                continue

            seen_orcids.add(orcid)

        identity = author_identity_key(name)

        if identity:
            if identity in seen_identities:
                continue

            seen_identities.add(identity)

        result.append({
            "name": name,
            "orcid": orcid,
            "author_id": author_id,
        })

    return result


# ============================================================================
# AUTORES: EXTRACCIÓN DESDE ORCID
# ============================================================================

def extract_orcid_author_name(
    contributor: Dict[str, Any]
) -> str:
    """
    Extrae nombre de contributor de ORCID.
    """
    credit = safe_get(
        contributor,
        "credit-name",
        "value",
        default="",
    )

    if credit:
        return clean_text(credit)

    given = safe_get(
        contributor,
        "contributor-attributes",
        "contributor-role",
        default="",
    )

    _ = given

    given_names = safe_get(
        contributor,
        "contributor-name",
        "given-names",
        "value",
        default="",
    )

    family_name = safe_get(
        contributor,
        "contributor-name",
        "family-name",
        "value",
        default="",
    )

    if family_name and given_names:
        return (
            f"{family_name}, "
            f"{given_names}"
        )

    return first_non_empty(
        family_name,
        given_names,
    )


def extract_orcid_author_orcid(
    contributor: Dict[str, Any]
) -> str:
    path_candidates = [
        (
            "contributor-orcid",
            "path",
        ),
        (
            "contributor-orcid",
            "uri",
        ),
    ]

    for path in path_candidates:
        value = safe_get(
            contributor,
            *path,
            default="",
        )

        if value:
            return normalize_orcid(value)

    return ""


# ============================================================================
# FECHAS
# ============================================================================

def extract_date(
    obj: Dict[str, Any]
) -> str:
    """
    Devuelve YYYY-MM-DD o YYYY.
    """
    year = safe_get(
        obj,
        "publication-date",
        "year",
        "value",
        default="",
    )

    month = safe_get(
        obj,
        "publication-date",
        "month",
        "value",
        default="",
    )

    day = safe_get(
        obj,
        "publication-date",
        "day",
        "value",
        default="",
    )

    if not year:
        year = safe_get(
            obj,
            "year",
            "value",
            default="",
        )

    year = clean_text(year)
    month = clean_text(month)
    day = clean_text(day)

    if not year:
        return ""

    if month:
        try:
            month_int = int(month)
        except ValueError:
            month_int = 0
    else:
        month_int = 0

    if day:
        try:
            day_int = int(day)
        except ValueError:
            day_int = 0
    else:
        day_int = 0

    if month_int and day_int:
        return (
            f"{year}-"
            f"{month_int:02d}-"
            f"{day_int:02d}"
        )

    if month_int:
        return (
            f"{year}-"
            f"{month_int:02d}"
        )

    return year


def extract_year(date_value: str) -> str:
    match = re.search(
        r"\b(19|20)\d{2}\b",
        clean_text(date_value),
    )

    if match:
        return match.group(0)

    return ""


# ============================================================================
# ORCID API
# ============================================================================

def get_access_token() -> str:
    token = os.environ.get(
        "ORCID_ACCESS_TOKEN",
        "",
    ).strip()

    if not token:
        raise RuntimeError(
            "No existe ORCID_ACCESS_TOKEN. "
            "Configura la variable de entorno antes de ejecutar el script."
        )

    return token


def orcid_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }


def api_get(
    url: str,
    token: str,
    params: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    try:
        response = requests.get(
            url,
            headers=orcid_headers(token),
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code == 404:
            logger.warning(
                "ORCID 404: %s",
                url,
            )
            return None

        response.raise_for_status()

        return response.json()

    except requests.RequestException as exc:
        logger.error(
            "Error ORCID: %s | %s",
            url,
            exc,
        )
        return None

    except ValueError as exc:
        logger.error(
            "Respuesta no JSON de ORCID: %s",
            exc,
        )
        return None


def fetch_orcid_works(
    orcid: str,
    token: str,
) -> List[Dict[str, Any]]:
    """
    Obtiene todos los works de un ORCID.
    """
    orcid = normalize_orcid(orcid)

    if not orcid:
        return []

    all_works = []

    for page in range(MAX_PAGES):
        offset = page * ROWS_PER_PAGE

        url = (
            f"{API_BASE}/"
            f"{orcid}/works"
        )

        params = {
            "start": offset,
            "rows": ROWS_PER_PAGE,
        }

        data = api_get(
            url,
            token,
            params,
        )

        if not data:
            break

        groups = safe_get(
            data,
            "group",
            default=[],
        )

        if not groups:
            break

        all_works.extend(groups)

        if len(groups) < ROWS_PER_PAGE:
            break

    return all_works


def fetch_orcid_work_detail(
    orcid: str,
    put_code: str,
    token: str,
) -> Optional[Dict[str, Any]]:
    url = (
        f"{API_BASE}/"
        f"{normalize_orcid(orcid)}/"
        f"work/{put_code}"
    )

    return api_get(
        url,
        token,
    )


# ============================================================================
# PUBLICACIONES
# ============================================================================

def extract_title_from_work(
    work: Dict[str, Any]
) -> str:
    title = safe_get(
        work,
        "title",
        "title",
        "value",
        default="",
    )

    if title:
        return clean_text(title)

    return clean_text(
        safe_get(
            work,
            "title",
            "value",
            default="",
        )
    )


def extract_journal(
    work: Dict[str, Any]
) -> str:
    return first_non_empty(
        safe_get(
            work,
            "journal-title",
            "value",
            default="",
        ),
        safe_get(
            work,
            "journal-title",
            default="",
        ),
    )


def extract_external_ids(
    work: Dict[str, Any]
) -> Dict[str, str]:
    result = {
        "doi": "",
        "pmid": "",
        "pmcid": "",
    }

    external_ids = safe_get(
        work,
        "external-ids",
        "external-id",
        default=[],
    )

    if not isinstance(
        external_ids,
        list,
    ):
        return result

    for external in external_ids:
        id_type = clean_text(
            safe_get(
                external,
                "external-id-type",
                default="",
            )
        ).lower()

        value = first_non_empty(
            safe_get(
                external,
                "external-id-value",
                default="",
            ),
            safe_get(
                external,
                "external-id-url",
                "value",
                default="",
            ),
        )

        value = clean_text(value)

        if id_type == "doi":
            result["doi"] = normalize_doi(value)

        elif id_type == "pmid":
            result["pmid"] = normalize_identifier(
                value
            )

        elif id_type == "pmcid":
            result["pmcid"] = normalize_identifier(
                value
            )

    return result


def extract_urls(
    work: Dict[str, Any]
) -> List[str]:
    urls = []

    url_value = safe_get(
        work,
        "url",
        "value",
        default="",
    )

    if url_value:
        urls.append(
            clean_text(url_value)
        )

    external_ids = safe_get(
        work,
        "external-ids",
        "external-id",
        default=[],
    )

    if isinstance(
        external_ids,
        list,
    ):
        for external in external_ids:
            url = safe_get(
                external,
                "external-id-url",
                "value",
                default="",
            )

            if url:
                urls.append(
                    clean_text(url)
                )

    return list(
        dict.fromkeys(urls)
    )


def extract_authors_from_work(
    work: Dict[str, Any],
    researcher_name: str,
    researcher_orcid: str,
    registry: Dict[str, Dict[str, Any]],
    overrides: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Extrae contributors y los convierte a autores canónicos.
    """
    contributors = safe_get(
        work,
        "contributors",
        "contributor",
        default=[],
    )

    if not isinstance(
        contributors,
        list,
    ):
        contributors = []

    records = []

    for contributor in contributors:
        raw_name = extract_orcid_author_name(
            contributor
        )

        contributor_orcid = extract_orcid_author_orcid(
            contributor
        )

        if not raw_name:
            continue

        # Evitamos que ORCID introduzca literalmente nombres
        # como "IEEE" como autor salvo que exista una identidad
        # persistente/ORCID real para ellos.
        if normalize_key_text(raw_name) in {
            "ieee",
            "inc",
            "publisher",
            "unknown",
            "anonymous",
        }:
            continue

        record = register_author(
            name=raw_name,
            orcid=contributor_orcid,
            researcher_name=researcher_name,
            researcher_orcid=researcher_orcid,
            registry=registry,
            overrides=overrides,
        )

        if record["name"]:
            records.append(record)

    return deduplicate_authors(records)


def extract_publication_from_work(
    work: Dict[str, Any],
    researcher_name: str,
    researcher_orcid: str,
    registry: Dict[str, Dict[str, Any]],
    overrides: Dict[str, Any],
    put_code: str = "",
) -> Dict[str, Any]:
    title = extract_title_from_work(work)

    publication_date = extract_date(work)

    year = extract_year(
        publication_date
    )

    ids = extract_external_ids(work)

    authors = extract_authors_from_work(
        work=work,
        researcher_name=researcher_name,
        researcher_orcid=researcher_orcid,
        registry=registry,
        overrides=overrides,
    )

    author_names = [
        a["name"]
        for a in authors
        if a.get("name")
    ]

    record = {
        "title": title,
        "journal": extract_journal(work),
        "date": publication_date,
        "year": year,
        "doi": ids["doi"],
        "pmid": ids["pmid"],
        "pmcid": ids["pmcid"],
        "url": extract_urls(work),
        "authors": author_names,
        "author_records": authors,

        "type": clean_text(
            safe_get(
                work,
                "type",
                default="",
            )
        ),

        "put_code": clean_text(
            put_code
            or safe_get(
                work,
                "put-code",
                default="",
            )
        ),

        "orcid_sources": [
            {
                "orcid": normalize_orcid(
                    researcher_orcid
                ),
                "researcher_name": clean_text(
                    researcher_name
                ),
            }
        ],
    }

    return record


# ============================================================================
# CONFERENCIAS
# ============================================================================

def text_contains_keyword(
    text: str,
    keywords: List[str]
) -> bool:
    text = normalize_key_text(text)

    for keyword in keywords:
        keyword_normalized = normalize_key_text(
            keyword
        )

        if keyword_normalized in text:
            return True

    return False


def classify_conference_work(
    publication: Dict[str, Any]
) -> Tuple[bool, str]:
    """
    Clasificación heurística.

    No pretende ser perfecta.
    Los excluidos se conservan en JSON para poder revisar.
    """
    work_type = normalize_key_text(
        publication.get("type", "")
    )

    journal = normalize_key_text(
        publication.get("journal", "")
    )

    title = normalize_key_text(
        publication.get("title", "")
    )

    combined = " ".join(
        [
            work_type,
            journal,
            title,
        ]
    )

    if text_contains_keyword(
        combined,
        EXCLUDE_KEYWORDS,
    ):
        # Si además hay una señal clara de proceedings,
        # dejamos que esa señal gane.
        if not text_contains_keyword(
            combined,
            CONFERENCE_KEYWORDS,
        ):
            return False, "excluded_keyword"

    if text_contains_keyword(
        combined,
        CONFERENCE_KEYWORDS,
    ):
        return True, "conference_keyword"

    # Tipos ORCID habituales.
    conference_types = {
        "conference-paper",
        "conference-abstract",
        "conference-poster",
        "conference",
    }

    if work_type in conference_types:
        return True, "orcid_type"

    return False, "not_detected_as_conference"


# ============================================================================
# IDENTIDAD DE PUBLICACIONES
# ============================================================================

def publication_strong_key(
    publication: Dict[str, Any]
) -> str:
    """
    Prioridad:

        DOI
        PMID
        PMCID
    """
    doi = normalize_doi(
        publication.get("doi", "")
    )

    if doi:
        return f"doi:{doi}"

    pmid = normalize_identifier(
        publication.get("pmid", "")
    )

    if pmid:
        return f"pmid:{pmid}"

    pmcid = normalize_identifier(
        publication.get("pmcid", "")
    )

    if pmcid:
        return f"pmcid:{pmcid}"

    return ""


def publication_author_keys(
    publication: Dict[str, Any]
) -> set:
    keys = set()

    for author in publication.get(
        "author_records",
        [],
    ):
        author_id = clean_text(
            author.get("author_id", "")
        )

        if author_id:
            keys.add(
                f"id:{author_id}"
            )
            continue

        name = clean_text(
            author.get("name", "")
        )

        identity = author_identity_key(
            name
        )

        if identity:
            keys.add(
                f"name:{identity}"
            )

    if not keys:
        for name in publication.get(
            "authors",
            [],
        ):
            identity = author_identity_key(
                name
            )

            if identity:
                keys.add(
                    f"name:{identity}"
                )

    return keys


def publication_fallback_key(
    publication: Dict[str, Any]
) -> str:
    title = normalize_title(
        publication.get("title", "")
    )

    year = extract_year(
        publication.get("year", "")
        or publication.get("date", "")
    )

    authors = sorted(
        publication_author_keys(
            publication
        )
    )

    return (
        f"title:{title}"
        f"|year:{year}"
        f"|authors:{'|'.join(authors)}"
    )


def title_similarity(
    title1: str,
    title2: str
) -> float:
    a = normalize_title(title1)
    b = normalize_title(title2)

    if not a or not b:
        return 0.0

    return difflib.SequenceMatcher(
        None,
        a,
        b,
    ).ratio()


def author_overlap(
    publication1: Dict[str, Any],
    publication2: Dict[str, Any],
) -> float:
    a = publication_author_keys(
        publication1
    )

    b = publication_author_keys(
        publication2
    )

    if not a or not b:
        return 0.0

    intersection = len(a & b)

    denominator = min(
        len(a),
        len(b),
    )

    if denominator == 0:
        return 0.0

    return intersection / denominator


# ============================================================================
# FUSIÓN DE PUBLICACIONES
# ============================================================================

def merge_lists(
    first: List[Any],
    second: List[Any],
) -> List[Any]:
    result = []

    for value in first + second:
        if value not in result:
            result.append(value)

    return result


def merge_publications(
    first: Dict[str, Any],
    second: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Fusiona dos registros considerados como la misma publicación.
    """
    result = dict(first)

    # Campos simples.
    for field in [
        "title",
        "journal",
        "date",
        "year",
        "doi",
        "pmid",
        "pmcid",
        "type",
    ]:
        current = clean_text(
            result.get(field, "")
        )

        incoming = clean_text(
            second.get(field, "")
        )

        if not current and incoming:
            result[field] = incoming

    # URLs.
    result["url"] = merge_lists(
        result.get("url", []),
        second.get("url", []),
    )

    # Autores.
    author_records = (
        result.get("author_records", [])
        + second.get("author_records", [])
    )

    result["author_records"] = deduplicate_authors(
        author_records
    )

    result["authors"] = [
        author["name"]
        for author in result["author_records"]
        if author.get("name")
    ]

    # Fuentes ORCID.
    result["orcid_sources"] = merge_lists(
        result.get("orcid_sources", []),
        second.get("orcid_sources", []),
    )

    # Put codes.
    put_codes = []

    for record in [
        first,
        second,
    ]:
        value = clean_text(
            record.get("put_code", "")
        )

        if value and value not in put_codes:
            put_codes.append(value)

    result["put_codes"] = put_codes

    if put_codes:
        result["put_code"] = put_codes[0]

    return result


# ============================================================================
# DEDUPLICACIÓN DE PUBLICACIONES
# ============================================================================

def deduplicate_publications(
    publications: List[Dict[str, Any]]
) -> Tuple[
    List[Dict[str, Any]],
    List[Dict[str, Any]]
]:
    """
    Devuelve:

        deduplicadas
        publication_review

    Duplicados fuertes se fusionan automáticamente.

    Duplicados difusos:
        AUTO_MERGE_FUZZY=False -> revisión
        AUTO_MERGE_FUZZY=True  -> fusión
    """
    by_strong_key = {}
    by_fallback_key = {}

    deduplicated = []
    review = []

    # ------------------------------------------------------------
    # Primera pasada: DOI / PMID / PMCID.
    # ------------------------------------------------------------

    for publication in publications:
        strong_key = publication_strong_key(
            publication
        )

        if strong_key:
            if strong_key in by_strong_key:
                index = by_strong_key[
                    strong_key
                ]

                deduplicated[index] = merge_publications(
                    deduplicated[index],
                    publication,
                )

                continue

            by_strong_key[strong_key] = len(
                deduplicated
            )

        deduplicated.append(
            publication
        )

    # ------------------------------------------------------------
    # Segunda pasada: título + año + autores.
    # ------------------------------------------------------------

    final_publications = []

    for publication in deduplicated:
        fallback_key = publication_fallback_key(
            publication
        )

        if (
            fallback_key
            and fallback_key in by_fallback_key
        ):
            index = by_fallback_key[
                fallback_key
            ]

            final_publications[index] = merge_publications(
                final_publications[index],
                publication,
            )

        else:
            index = len(final_publications)

            if fallback_key:
                by_fallback_key[
                    fallback_key
                ] = index

            final_publications.append(
                publication
            )

    # ------------------------------------------------------------
    # Tercera pasada: fuzzy.
    # ------------------------------------------------------------

    if len(final_publications) > 1:
        merged_indices = set()

        for i in range(
            len(final_publications)
        ):
            if i in merged_indices:
                continue

            p1 = final_publications[i]

            title1 = p1.get(
                "title",
                "",
            )

            year1 = extract_year(
                p1.get("year", "")
                or p1.get("date", "")
            )

            for j in range(
                i + 1,
                len(final_publications)
            ):
                if j in merged_indices:
                    continue

                p2 = final_publications[j]

                title2 = p2.get(
                    "title",
                    "",
                )

                year2 = extract_year(
                    p2.get("year", "")
                    or p2.get("date", "")
                )

                # Si hay año en ambos y no coincide,
                # no consideramos fuzzy.
                if (
                    year1
                    and year2
                    and year1 != year2
                ):
                    continue

                similarity = title_similarity(
                    title1,
                    title2,
                )

                if (
                    similarity
                    < FUZZY_TITLE_THRESHOLD
                ):
                    continue

                overlap = author_overlap(
                    p1,
                    p2,
                )

                if (
                    overlap
                    < MIN_AUTHOR_OVERLAP_FOR_FUZZY
                ):
                    continue

                review_item = {
                    "reason": "fuzzy_duplicate_candidate",
                    "similarity": round(
                        similarity,
                        4,
                    ),
                    "author_overlap": round(
                        overlap,
                        4,
                    ),
                    "publication_a": {
                        "title": p1.get(
                            "title",
                            "",
                        ),
                        "year": year1,
                        "doi": p1.get(
                            "doi",
                            "",
                        ),
                        "authors": p1.get(
                            "authors",
                            [],
                        ),
                    },
                    "publication_b": {
                        "title": p2.get(
                            "title",
                            "",
                        ),
                        "year": year2,
                        "doi": p2.get(
                            "doi",
                            "",
                        ),
                        "authors": p2.get(
                            "authors",
                            [],
                        ),
                    },
                    "auto_merged": AUTO_MERGE_FUZZY,
                }

                review.append(
                    review_item
                )

                if AUTO_MERGE_FUZZY:
                    final_publications[i] = merge_publications(
                        final_publications[i],
                        final_publications[j],
                    )

                    merged_indices.add(j)

        if merged_indices:
            final_publications = [
                p
                for index, p in enumerate(
                    final_publications
                )
                if index not in merged_indices
            ]

    return final_publications, review


# ============================================================================
# AUTOR REVIEW
# ============================================================================

def build_author_reports(
    registry: Dict[str, Dict[str, Any]]
) -> Tuple[
    Dict[str, Any],
    List[Dict[str, Any]]
]:
    variants = {}
    review = []

    for author_id, record in registry.items():
        canonical = record.get(
            "canonical_name",
            "",
        )

        author_variants = record.get(
            "variants",
            [],
        )

        variants[author_id] = {
            "author_id": author_id,
            "canonical_name": canonical,
            "orcid": record.get(
                "orcid",
                "",
            ),
            "variants": author_variants,
        }

        identity_keys = defaultdict(
            list
        )

        for variant in author_variants:
            identity_keys[
                author_identity_key(variant)
            ].append(
                variant
            )

        for identity_key, names in identity_keys.items():
            if len(names) <= 1:
                continue

            if not identity_key:
                continue

            review.append({
                "author_id": author_id,
                "canonical_name": canonical,
                "identity_key": identity_key,
                "variants": names,
            })

    return variants, review


# ============================================================================
# BIBTEX
# ============================================================================

def bibtex_escape(value: str) -> str:
    if not value:
        return ""

    value = str(value)

    replacements = {
        "\\": "\\textbackslash{}",
        "{": "\\{",
        "}": "\\}",
        "&": "\\&",
        "%": "\\%",
        "#": "\\#",
        "_": "\\_",
    }

    # Evitar escapar dos veces las llaves generadas.
    value = value.replace(
        "\\",
        "\\textbackslash{}"
    )

    for old, new in [
        ("&", "\\&"),
        ("%", "\\%"),
        ("#", "\\#"),
        ("_", "\\_"),
    ]:
        value = value.replace(
            old,
            new,
        )

    return value


def bibtex_author_name(
    name: str
) -> str:
    """
    Para BibTeX preferimos conservar:

        Apellido, Iniciales

    cuando ya viene en ese formato.
    """
    name = canonicalize_author_display(
        name
    )

    if "," in name:
        return name

    surname, given = author_name_parts(
        name
    )

    if surname and given:
        return f"{surname}, {given}"

    return name


def make_bibtex_key(
    publication: Dict[str, Any],
    used_keys: set,
) -> str:
    authors = publication.get(
        "author_records",
        [],
    )

    first_author = ""

    if authors:
        first_author = authors[0].get(
            "name",
            "",
        )

    surname, _ = author_name_parts(
        first_author
    )

    surname = normalize_unicode(
        surname
    )

    surname = re.sub(
        r"[^A-Za-z0-9]",
        "",
        surname,
    )

    surname = surname or "Unknown"

    year = extract_year(
        publication.get("year", "")
        or publication.get("date", "")
    )

    year = year or "n.d."

    title = normalize_key_text(
        publication.get(
            "title",
            "",
        )
    )

    words = title.split()

    title_fragment = "".join(
        words[:3]
    )

    title_fragment = re.sub(
        r"[^a-zA-Z0-9]",
        "",
        title_fragment,
    )

    base = (
        f"{surname}"
        f"{year}"
        f"{title_fragment}"
    )

    base = base[:70] or "publication"

    key = base
    counter = 2

    while key in used_keys:
        key = f"{base}_{counter}"
        counter += 1

    used_keys.add(key)

    return key


def publication_to_bibtex(
    publication: Dict[str, Any],
    used_keys: set,
) -> str:
    key = make_bibtex_key(
        publication,
        used_keys,
    )

    authors = publication.get(
        "author_records",
        [],
    )

    author_string = " and ".join(
        bibtex_author_name(
            author["name"]
        )
        for author in authors
        if author.get("name")
    )

    title = publication.get(
        "title",
        "",
    )

    year = extract_year(
        publication.get("year", "")
        or publication.get("date", "")
    )

    journal = publication.get(
        "journal",
        "",
    )

    doi = normalize_doi(
        publication.get(
            "doi",
            "",
        )
    )

    url_values = publication.get(
        "url",
        [],
    )

    url = ""

    if isinstance(
        url_values,
        list
    ) and url_values:
        url = url_values[0]

    fields = []

    if author_string:
        fields.append(
            f"  author = {{{bibtex_escape(author_string)}}}"
        )

    if title:
        fields.append(
            f"  title = {{{bibtex_escape(title)}}}"
        )

    if journal:
        fields.append(
            f"  journal = {{{bibtex_escape(journal)}}}"
        )

    if year:
        fields.append(
            f"  year = {{{bibtex_escape(year)}}}"
        )

    if doi:
        fields.append(
            f"  doi = {{{bibtex_escape(doi)}}}"
        )

    if url:
        fields.append(
            f"  url = {{{bibtex_escape(url)}}}"
        )

    entry = [
        f"@inproceedings{{{key},",
        *fields,
        "}",
    ]

    return "\n".join(entry)


def write_bibtex(
    publications: List[Dict[str, Any]]
) -> None:
    used_keys = set()

    entries = []

    for publication in publications:
        entries.append(
            publication_to_bibtex(
                publication,
                used_keys,
            )
        )

    content = (
        "\n\n".join(entries)
        + "\n"
    )

    with open(
        OUTPUT_BIB,
        "w",
        encoding="utf-8",
    ) as f:
        f.write(content)


# ============================================================================
# HTML
# ============================================================================

def html_escape(value: Any) -> str:
    return html.escape(
        clean_text(value)
    )


def generate_html(
    publications: List[Dict[str, Any]],
    excluded: List[Dict[str, Any]],
) -> None:
    rows = []

    sorted_publications = sorted(
        publications,
        key=lambda p: (
            extract_year(
                p.get(
                    "year",
                    "",
                )
                or p.get(
                    "date",
                    "",
                )
            ),
            normalize_title(
                p.get(
                    "title",
                    "",
                )
            ),
        ),
        reverse=True,
    )

    for publication in sorted_publications:
        authors = publication.get(
            "authors",
            [],
        )

        author_text = "; ".join(
            authors
        )

        doi = normalize_doi(
            publication.get(
                "doi",
                "",
            )
        )

        doi_html = ""

        if doi:
            doi_html = (
                f'<a href="https://doi.org/'
                f'{html_escape(doi)}">'
                f'{html_escape(doi)}'
                f'</a>'
            )

        sources = publication.get(
            "orcid_sources",
            [],
        )

        source_text = "; ".join(
            clean_text(
                source.get(
                    "researcher_name",
                    "",
                )
            )
            for source in sources
            if source.get(
                "researcher_name"
            )
        )

        rows.append(
            "<tr>"
            f"<td>{html_escape(publication.get('year', ''))}</td>"
            f"<td>{html_escape(publication.get('title', ''))}</td>"
            f"<td>{html_escape(author_text)}</td>"
            f"<td>{html_escape(publication.get('journal', ''))}</td>"
            f"<td>{doi_html}</td>"
            f"<td>{html_escape(source_text)}</td>"
            "</tr>"
        )

    excluded_rows = []

    for publication in excluded:
        excluded_rows.append(
            "<tr>"
            f"<td>{html_escape(publication.get('year', ''))}</td>"
            f"<td>{html_escape(publication.get('title', ''))}</td>"
            f"<td>{html_escape(publication.get('reason', ''))}</td>"
            "</tr>"
        )

    document = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Publicaciones de congresos</title>
<style>
body {{
    font-family: Arial, sans-serif;
    margin: 30px;
    color: #222;
}}

h1, h2 {{
    margin-top: 30px;
}}

table {{
    border-collapse: collapse;
    width: 100%;
    margin-bottom: 40px;
}}

th, td {{
    border: 1px solid #ccc;
    padding: 8px;
    vertical-align: top;
}}

th {{
    background: #eee;
}}

tr:nth-child(even) {{
    background: #f8f8f8;
}}

.small {{
    color: #666;
    font-size: 0.9em;
}}
</style>
</head>

<body>

<h1>Publicaciones de congresos</h1>

<p class="small">
Generado automáticamente:
{html_escape(datetime.now().isoformat())}
</p>

<p>
Total publicaciones:
<strong>{len(publications)}</strong>
</p>

<table>
<thead>
<tr>
<th>Año</th>
<th>Título</th>
<th>Autores</th>
<th>Revista / Proceedings</th>
<th>DOI</th>
<th>Investigador ORCID</th>
</tr>
</thead>

<tbody>
{''.join(rows)}
</tbody>
</table>

<h2>Publicaciones excluidas</h2>

<table>
<thead>
<tr>
<th>Año</th>
<th>Título</th>
<th>Motivo</th>
</tr>
</thead>

<tbody>
{''.join(excluded_rows)}
</tbody>
</table>

</body>
</html>
"""

    with open(
        OUTPUT_HTML,
        "w",
        encoding="utf-8",
    ) as f:
        f.write(document)


# ============================================================================
# CARGA DE INVESTIGADORES
# ============================================================================

def load_researchers(
    path: str
) -> List[Dict[str, Any]]:
    data = load_json(
        path,
        [],
    )

    if isinstance(data, dict):
        # Soportar formatos:
        #
        # {"researchers": [...]}
        #
        if isinstance(
            data.get("researchers"),
            list,
        ):
            data = data["researchers"]
        else:
            data = [data]

    if not isinstance(
        data,
        list,
    ):
        raise ValueError(
            f"{path} no contiene una lista de investigadores."
        )

    return data


def researcher_name(
    researcher: Dict[str, Any]
) -> str:
    return first_non_empty(
        researcher.get("name"),
        researcher.get("full_name"),
        researcher.get("display_name"),
    )


def researcher_orcid(
    researcher: Dict[str, Any]
) -> str:
    return normalize_orcid(
        first_non_empty(
            researcher.get("orcid"),
            researcher.get("ORCID"),
            researcher.get("id"),
        )
    )


# ============================================================================
# PROCESAMIENTO
# ============================================================================

def process_researcher(
    researcher: Dict[str, Any],
    token: str,
    registry: Dict[str, Dict[str, Any]],
    overrides: Dict[str, Any],
) -> Tuple[
    List[Dict[str, Any]],
    List[Dict[str, Any]]
]:
    name = researcher_name(
        researcher
    )

    orcid = researcher_orcid(
        researcher
    )

    if not orcid:
        logger.warning(
            "Investigador sin ORCID: %s",
            name,
        )

        return [], []

    logger.info(
        "Procesando %s (%s)",
        name,
        orcid,
    )

    works = fetch_orcid_works(
        orcid,
        token,
    )

    logger.info(
        "  Works encontrados: %d",
        len(works),
    )

    publications = []
    excluded = []

    for group in works:
        summaries = safe_get(
            group,
            "work-summary",
            default=[],
        )

        if not isinstance(
            summaries,
            list,
        ):
            continue

        for summary in summaries:
            put_code = clean_text(
                safe_get(
                    summary,
                    "put-code",
                    default="",
                )
            )

            # Intentamos obtener el detalle completo.
            detail = None

            if put_code:
                detail = fetch_orcid_work_detail(
                    orcid,
                    put_code,
                    token,
                )

            work = detail or summary

            publication = extract_publication_from_work(
                work=work,
                researcher_name=name,
                researcher_orcid=orcid,
                registry=registry,
                overrides=overrides,
                put_code=put_code,
            )

            is_conference, reason = (
                classify_conference_work(
                    publication
                )
            )

            publication["conference_classification"] = (
                reason
            )

            if is_conference:
                publications.append(
                    publication
                )
            else:
                excluded_record = dict(
                    publication
                )

                excluded_record[
                    "reason"
                ] = reason

                excluded.append(
                    excluded_record
                )

    return publications, excluded


# ============================================================================
# NORMALIZACIÓN FINAL
# ============================================================================

def normalize_publication_records(
    publications: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    result = []

    for publication in publications:
        record = dict(publication)

        record["title"] = clean_text(
            record.get(
                "title",
                "",
            )
        )

        record["journal"] = clean_text(
            record.get(
                "journal",
                "",
            )
        )

        record["date"] = clean_text(
            record.get(
                "date",
                "",
            )
        )

        record["year"] = extract_year(
            record.get(
                "year",
                "",
            )
            or record.get(
                "date",
                "",
            )
        )

        record["doi"] = normalize_doi(
            record.get(
                "doi",
                "",
            )
        )

        record["pmid"] = normalize_identifier(
            record.get(
                "pmid",
                "",
            )
        )

        record["pmcid"] = normalize_identifier(
            record.get(
                "pmcid",
                "",
            )
        )

        # Autores.
        records = []

        for author in record.get(
            "author_records",
            [],
        ):
            if isinstance(
                author,
                str,
            ):
                author = {
                    "name": author
                }

            name = clean_text(
                author.get(
                    "name",
                    "",
                )
            )

            if not name:
                continue

            records.append({
                "name": name,
                "orcid": normalize_orcid(
                    author.get(
                        "orcid",
                        "",
                    )
                ),
                "author_id": clean_text(
                    author.get(
                        "author_id",
                        "",
                    )
                ),
            })

        records = deduplicate_authors(
            records
        )

        record["author_records"] = records

        record["authors"] = [
            author["name"]
            for author in records
            if author.get("name")
        ]

        # URLs.
        urls = record.get(
            "url",
            [],
        )

        if isinstance(
            urls,
            str,
        ):
            urls = [urls]

        record["url"] = list(
            dict.fromkeys(
                clean_text(url)
                for url in urls
                if clean_text(url)
            )
        )

        result.append(record)

    return result


# ============================================================================
# ORDENACIÓN
# ============================================================================

def sort_publications(
    publications: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    return sorted(
        publications,
        key=lambda p: (
            -(int(
                extract_year(
                    p.get(
                        "year",
                        "",
                    )
                    or p.get(
                        "date",
                        "",
                    )
                )
                or 0
            )),
            normalize_title(
                p.get(
                    "title",
                    "",
                )
            ),
        )
    )


# ============================================================================
# JSON FINAL
# ============================================================================

def make_final_json_records(
    publications: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Prepara la salida pública.

    Conserva:
        authors
        author_records

    para que el .json siga siendo cómodo de usar,
    pero sin perder los IDs persistentes.
    """
    result = []

    for publication in publications:
        record = dict(publication)

        # Normalización de campos internos.
        record["authors"] = [
            author["name"]
            for author in record.get(
                "author_records",
                []
            )
            if author.get("name")
        ]

        result.append(record)

    return result


# ============================================================================
# ESTADÍSTICAS
# ============================================================================

def print_statistics(
    publications: List[Dict[str, Any]],
    excluded: List[Dict[str, Any]],
    registry: Dict[str, Dict[str, Any]],
    review: List[Dict[str, Any]],
) -> None:
    doi_count = sum(
        bool(
            normalize_doi(
                p.get("doi", "")
            )
        )
        for p in publications
    )

    print()
    print("=" * 70)
    print("RESUMEN")
    print("=" * 70)
    print(
        f"Publicaciones de congresos : {len(publications)}"
    )
    print(
        f"Publicaciones excluidas    : {len(excluded)}"
    )
    print(
        f"Autores persistentes       : {len(registry)}"
    )
    print(
        f"Candidatos fuzzy a revisar : {len(review)}"
    )
    print(
        f"Publicaciones con DOI      : {doi_count}"
    )
    print("=" * 70)
    print()


# ============================================================================
# MAIN
# ============================================================================

def main() -> None:
    logger.info(
        "Iniciando pipeline ORCID..."
    )

    # ------------------------------------------------------------
    # Token.
    # ------------------------------------------------------------

    token = get_access_token()

    # ------------------------------------------------------------
    # Investigadores.
    # ------------------------------------------------------------

    researchers = load_researchers(
        INPUT_FILE
    )

    logger.info(
        "Investigadores cargados: %d",
        len(researchers),
    )

    # ------------------------------------------------------------
    # Memoria persistente.
    # ------------------------------------------------------------

    registry = load_author_registry()

    overrides = load_author_overrides()

    # Creamos el fichero de overrides aunque todavía esté vacío.
    save_author_overrides(
        overrides
    )

    # ------------------------------------------------------------
    # Procesar investigadores.
    # ------------------------------------------------------------

    all_publications = []
    all_excluded = []

    for researcher in researchers:
        publications, excluded = (
            process_researcher(
                researcher=researcher,
                token=token,
                registry=registry,
                overrides=overrides,
            )
        )

        all_publications.extend(
            publications
        )

        all_excluded.extend(
            excluded
        )

    # ------------------------------------------------------------
    # Guardar memoria de autores.
    # ------------------------------------------------------------

    save_author_registry(
        registry
    )

    # ------------------------------------------------------------
    # Normalizar.
    # ------------------------------------------------------------

    all_publications = (
        normalize_publication_records(
            all_publications
        )
    )

    all_excluded = (
        normalize_publication_records(
            all_excluded
        )
    )

    # ------------------------------------------------------------
    # Guardar TODAS las publicaciones de ORCID antes de
    # deduplicar, útil para auditoría.
    # ------------------------------------------------------------

    save_json(
        OUTPUT_ALL,
        all_publications,
    )

    # ------------------------------------------------------------
    # Deduplicar publicaciones.
    # ------------------------------------------------------------

    logger.info(
        "Deduplicando publicaciones..."
    )

    publications, publication_review = (
        deduplicate_publications(
            all_publications
        )
    )

    publications = sort_publications(
        publications
    )

    # ------------------------------------------------------------
    # Guardar revisión de publicaciones.
    # ------------------------------------------------------------

    save_json(
        OUTPUT_PUBLICATION_REVIEW,
        publication_review,
    )

    # ------------------------------------------------------------
    # JSON principal.
    # ------------------------------------------------------------

    final_records = (
        make_final_json_records(
            publications
        )
    )

    save_json(
        OUTPUT_JSON,
        final_records,
    )

    # ------------------------------------------------------------
    # JSON de excluidas.
    # ------------------------------------------------------------

    save_json(
        OUTPUT_EXCLUDED,
        all_excluded,
    )

    # ------------------------------------------------------------
    # Variantes y revisión de autores.
    # ------------------------------------------------------------

    author_variants, author_review = (
        build_author_reports(
            registry
        )
    )

    save_json(
        OUTPUT_AUTHOR_VARIANTS,
        author_variants,
    )

    save_json(
        OUTPUT_AUTHOR_REVIEW,
        author_review,
    )

    # ------------------------------------------------------------
    # BibTeX.
    # ------------------------------------------------------------

    logger.info(
        "Generando BibTeX..."
    )

    write_bibtex(
        publications
    )

    # ------------------------------------------------------------
    # HTML.
    # ------------------------------------------------------------

    logger.info(
        "Generando HTML..."
    )

    generate_html(
        publications,
        all_excluded,
    )

    # ------------------------------------------------------------
    # Estadísticas.
    # ------------------------------------------------------------

    print_statistics(
        publications=publications,
        excluded=all_excluded,
        registry=registry,
        review=publication_review,
    )

    logger.info(
        "Pipeline terminado correctamente."
    )

    print(
        "Archivos generados:"
    )

    for path in [
        OUTPUT_JSON,
        OUTPUT_ALL,
        OUTPUT_EXCLUDED,
        OUTPUT_HTML,
        OUTPUT_BIB,
        OUTPUT_AUTHOR_VARIANTS,
        OUTPUT_AUTHOR_REVIEW,
        OUTPUT_AUTHOR_REGISTRY,
        OUTPUT_AUTHOR_OVERRIDES,
        OUTPUT_PUBLICATION_REVIEW,
    ]:
        print(
            f"  - {path}"
        )


if __name__ == "__main__":
    main()
