import json
import os
import re
import time
import html
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ============================================================
# CONFIGURACIÓN
# ============================================================

INPUT_FILE = "researchers1.json"

OUTPUT_JSON = "conference_publications.json"
OUTPUT_ALL = "conference_publications_all_orcid.json"
OUTPUT_EXCLUDED = "conference_publications_excluded.json"
OUTPUT_HTML = "conference_publications.html"
OUTPUT_BIB = "conference_publications.bib"
OUTPUT_AUTHOR_VARIANTS = "author_variants.json"

API_BASE = "https://pub.orcid.org/v3.0"

ROWS_PER_PAGE = 100
MAX_PAGES = 1000
REQUEST_TIMEOUT = 30


# ============================================================
# TOKEN ORCID
# ============================================================

TOKEN = os.getenv("ORCID_ACCESS_TOKEN")

if not TOKEN:
    raise RuntimeError(
        "No se ha encontrado ORCID_ACCESS_TOKEN.\n"
        "El workflow debe generar el token antes de ejecutar el script."
    )

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.orcid+json",
}


# ============================================================
# SESIÓN HTTP
# ============================================================

session = requests.Session()

retry = Retry(
    total=5,
    connect=5,
    read=5,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"],
    respect_retry_after_header=True,
)

adapter = HTTPAdapter(
    max_retries=retry,
    pool_connections=20,
    pool_maxsize=20,
)

session.mount("https://", adapter)
session.mount("http://", adapter)


# ============================================================
# REGISTRO GLOBAL DE AUTORES
# ============================================================

# ORCID del autor -> nombre canónico
AUTHOR_REGISTRY = {}

# Forma normalizada -> variantes originales observadas
AUTHOR_VARIANTS = {}


# ============================================================
# ALIAS DE AUTORES
# ============================================================

# Estos alias se utilizan únicamente cuando tenemos suficiente
# evidencia de que son la misma forma de nombre.
#
# IMPORTANTE:
# No estamos intentando adivinar nombres completos.
# Se conservan las iniciales cuando son las que proporciona ORCID.

AUTHOR_ALIASES = {
    # --------------------------------------------------------
    # Díaz-de-María
    # --------------------------------------------------------
    "diaz-de-maria, f.": "Díaz-de-María, F.",
    "díaz-de-maría, f.": "Díaz-de-María, F.",
    "diaz-de-maria, f": "Díaz-de-María, F.",
    "díaz-de-maría, f": "Díaz-de-María, F.",
    "diaz-de-maria,f.": "Díaz-de-María, F.",
    "díaz-de-maría,f.": "Díaz-de-María, F.",

    # --------------------------------------------------------
    # Peláez-Moreno
    # --------------------------------------------------------
    "pelaez-moreno, c.": "Peláez-Moreno, C.",
    "peláez-moreno, c.": "Peláez-Moreno, C.",
    "pelaez-moreno, c": "Peláez-Moreno, C.",
    "peláez-moreno, c": "Peláez-Moreno, C.",
    "pelaez-moreno,c.": "Peláez-Moreno, C.",
    "peláez-moreno,c.": "Peláez-Moreno, C.",

    # --------------------------------------------------------
    # Gallardo-Antolín
    # --------------------------------------------------------
    "gallardo-antolin, a.": "Gallardo-Antolín, A.",
    "gallardo-antolín, a.": "Gallardo-Antolín, A.",
    "gallardo-antolin, a": "Gallardo-Antolín, A.",
    "gallardo-antolín, a": "Gallardo-Antolín, A.",
    "ascension gallardo-antolin": "Gallardo-Antolín, A.",
    "ascensión gallardo-antolín": "Gallardo-Antolín, A.",

    # --------------------------------------------------------
    # González-Díaz
    # --------------------------------------------------------
    "gonzalez-diaz, i.": "González-Díaz, I.",
    "gonzález-diaz, i.": "González-Díaz, I.",
    "gonzalez-díaz, i.": "González-Díaz, I.",
    "gonzález-díaz, i.": "González-Díaz, I.",
    "gonzalez-diaz, i": "González-Díaz, I.",
    "gonzález-diaz, i": "González-Díaz, I.",
    "gonzalez díaz, i.": "González-Díaz, I.",
    "gonzález díaz, i.": "González-Díaz, I.",
    "gonzalez diaz, i.": "González-Díaz, I.",

    # --------------------------------------------------------
    # Martínez-Enríquez
    # --------------------------------------------------------
    "martinez-enriquez, e.": "Martínez-Enríquez, E.",
    "martínez-enriquez, e.": "Martínez-Enríquez, E.",
    "martinez-enríquez, e.": "Martínez-Enríquez, E.",
    "martínez-enríquez, e.": "Martínez-Enríquez, E.",
    "martinez-enriquez, e": "Martínez-Enríquez, E.",
    "martínez-enríquez, e": "Martínez-Enríquez, E.",

    # --------------------------------------------------------
    # De-Frutos-López
    # --------------------------------------------------------
    "de-frutos-lopez, m.": "De-Frutos-López, M.",
    "de-frutos-lópez, m.": "De-Frutos-López, M.",
    "de-frutos-lopez, m": "De-Frutos-López, M.",
    "de-frutos-lópez, m": "De-Frutos-López, M.",

    # --------------------------------------------------------
    # Del-Ama-Esteban
    # --------------------------------------------------------
    "del-ama-esteban, o.": "Del-Ama-Esteban, O.",
    "del-ama-esteban, o": "Del-Ama-Esteban, O.",

    # --------------------------------------------------------
    # Sanz-Rodríguez
    # --------------------------------------------------------
    "sanz-rodriguez, s.": "Sanz-Rodríguez, S.",
    "sanz-rodríguez, s.": "Sanz-Rodríguez, S.",
    "sanz-rodriguez, s": "Sanz-Rodríguez, S.",
    "sanz-rodríguez, s": "Sanz-Rodríguez, S.",

    # --------------------------------------------------------
    # García-García
    # --------------------------------------------------------
    "garcia-garcia, d.": "García-García, D.",
    "garcía-garcia, d.": "García-García, D.",
    "garcia-garcía, d.": "García-García, D.",
    "garcía-garcía, d.": "García-García, D.",
    "garcia-garcia, d": "García-García, D.",
    "garcía-garcía, d": "García-García, D.",

    # --------------------------------------------------------
    # Figueiras-Vidal
    # --------------------------------------------------------
    "figueiras-vidal, a.r.": "Figueiras-Vidal, A.R.",
    "figueiras-vidal, a. r.": "Figueiras-Vidal, A.R.",
    "figueiras-vidal, ar": "Figueiras-Vidal, A.R.",

    # --------------------------------------------------------
    # Fernández-Torres
    # Unificamos M.A. y M.-A. en M.-A.
    # --------------------------------------------------------
    "fernandez-torres, m.a.": "Fernández-Torres, M.-A.",
    "fernández-torres, m.a.": "Fernández-Torres, M.-A.",
    "fernandez-torres, m.-a.": "Fernández-Torres, M.-A.",
    "fernández-torres, m.-a.": "Fernández-Torres, M.-A.",

    # --------------------------------------------------------
    # Martínez-Cortés
    # --------------------------------------------------------
    "martinez-cortes, t.": "Martínez-Cortés, T.",
    "martínez-cortes, t.": "Martínez-Cortés, T.",
    "martinez-cortés, t.": "Martínez-Cortés, T.",
    "martínez-cortés, t": "Martínez-Cortés, T.",

    # --------------------------------------------------------
    # García-Cabellos
    # --------------------------------------------------------
    "garcia-cabellos, j.m.": "García-Cabellos, J.M.",
    "garcía-cabellos, j.m.": "García-Cabellos, J.M.",
    "garcia-cabellos, jm": "García-Cabellos, J.M.",

    # --------------------------------------------------------
    # Pérez-Cruz
    # --------------------------------------------------------
    "perez-cruz, f.": "Pérez-Cruz, F.",
    "pérez-cruz, f.": "Pérez-Cruz, F.",
    "perez-cruz, f": "Pérez-Cruz, F.",

    # --------------------------------------------------------
    # Jiménez-Moreno
    # --------------------------------------------------------
    "jimenez-moreno, a.": "Jiménez-Moreno, A.",
    "jiménez-moreno, a.": "Jiménez-Moreno, A.",
    "jimenez-moreno, a": "Jiménez-Moreno, A.",

    # --------------------------------------------------------
    # Mejía-Ocaña / Mejía-Navarrete
    # --------------------------------------------------------
    "mejia-ocana, a.b.": "Mejía-Ocaña, A.B.",
    "mejía-ocaña, a.b.": "Mejía-Ocaña, A.B.",
    "mejia-navarrete, d.": "Mejía-Navarrete, D.",
    "mejía-navarrete, d.": "Mejía-Navarrete, D.",

    # --------------------------------------------------------
    # Vicente-Peña
    # --------------------------------------------------------
    "vicente-pena, j.": "Vicente-Peña, J.",
    "vicente-peña, j.": "Vicente-Peña, J.",
    "vicente-pena, j": "Vicente-Peña, J.",

    # --------------------------------------------------------
    # Rodríguez-Hidalgo
    # --------------------------------------------------------
    "rodriguez-hidalgo, a.": "Rodríguez-Hidalgo, A.",
    "rodríguez-hidalgo, a.": "Rodríguez-Hidalgo, A.",

    # --------------------------------------------------------
    # Ludeña-Choez
    # --------------------------------------------------------
    "ludena-choez, m.": "Ludeña-Choez, M.",
    "ludeña-choez, m.": "Ludeña-Choez, M.",

    # --------------------------------------------------------
    # Macías-Guarasa
    # --------------------------------------------------------
    "macias-guarasa, m.": "Macías-Guarasa, M.",
    "macías-guarasa, m.": "Macías-Guarasa, M.",

    # --------------------------------------------------------
    # Santamaría-Caballero
    # --------------------------------------------------------
    "santamaria-caballero, a.": "Santamaría-Caballero, A.",
    "santamaría-caballero, a.": "Santamaría-Caballero, A.",

    # --------------------------------------------------------
    # Artés-Rodríguez
    # --------------------------------------------------------
    "artes-rodriguez, j.": "Artés-Rodríguez, J.",
    "artés-rodríguez, j.": "Artés-Rodríguez, J.",

    # --------------------------------------------------------
    # Autores de registros recientes
    # --------------------------------------------------------
    "perez-suay, a.": "Pérez-Suay, A.",
    "pérez-suay, a.": "Pérez-Suay, A.",
    "munoz-mari, j.": "Muñoz-Mari, J.",
    "muñoz-mari, j.": "Muñoz-Mari, J.",
    "amoros, j.": "Amorós, J.",
    "amorós, j.": "Amorós, J.",
    "fernandez-moran, r.": "Fernández-Morán, R.",
    "fernández-moran, r.": "Fernández-Morán, R.",
    "martinez-garcia, m.": "Martínez-García, M.",
    "martínez-garcia, m.": "Martínez-García, M.",
}



# ============================================================
# UTILIDADES
# ============================================================

def clean_text(value):
    if value is None:
        return ""

    return str(value).strip()


def normalize_title(title):
    if not title:
        return ""

    title = str(title).lower()
    title = re.sub(r"\s+", " ", title)
    title = re.sub(r"[^\w\s]", "", title)

    return title.strip()


def normalize_orcid(orcid):
    """
    Normaliza un ORCID para utilizarlo como identificador.
    """

    if not orcid:
        return ""

    value = clean_text(orcid)

    value = re.sub(
        r"^https?://orcid\.org/",
        "",
        value,
        flags=re.IGNORECASE,
    )

    return value.strip().lower()


def safe_get(url, params=None):
    try:
        response = session.get(
            url,
            headers=HEADERS,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()
        return response.json()

    except requests.RequestException as error:
        print(f"      ERROR HTTP: {error}")
        return None

    except ValueError as error:
        print(f"      ERROR JSON: {error}")
        return None


# ============================================================
# NOMBRES DE AUTORES
# ============================================================

def author_alias_key(name):
    """
    Crea una clave muy flexible para buscar alias.

    No se utiliza para mostrar el nombre.
    """

    if not name:
        return ""

    value = clean_text(name).lower()

    value = re.sub(r"\s+", " ", value)
    value = value.replace(" ", "")

    return value


def normalize_author_name(name):
    """
    Normaliza un nombre de autor.

    Objetivo:

        Diaz-De-Maria, F.
        Díaz-De-María, F.
        Díaz-de-María, F

    ->

        Díaz-de-María, F.

    No intenta reconstruir nombres completos que no estén
    presentes en ORCID.
    """

    if not name:
        return ""

    original = clean_text(name)

    if not original:
        return ""

    # Espacios repetidos
    value = re.sub(r"\s+", " ", original)

    # Espacios alrededor de la coma
    value = re.sub(r"\s*,\s*", ", ", value)

    # --------------------------------------------------------
    # Si está en formato "Apellido, Iniciales"
    # --------------------------------------------------------

    if "," in value:
        surname, initials = value.split(",", 1)

        surname = surname.strip()
        initials = initials.strip()

        # Normalizar espacios entre iniciales.
        # F. J. -> F.J.
        initials = re.sub(
            r"\s*\.\s*",
            ".",
            initials,
        )

        # Si termina en una letra de inicial y no tiene punto,
        # añadimos punto solo si es claramente una inicial.
        if re.fullmatch(
            r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]",
            initials,
        ):
            initials += "."

        value = f"{surname}, {initials}"

    # --------------------------------------------------------
    # Normalización de partículas/apellidos concretos
    # --------------------------------------------------------

    replacements = [
        (
            r"(?i)\bDíaz[- ]De[- ]María\b",
            "Díaz-de-María",
        ),
        (
            r"(?i)\bDiaz[- ]De[- ]Maria\b",
            "Díaz-de-María",
        ),
        (
            r"(?i)\bDíaz[- ]De[- ]maria\b",
            "Díaz-de-María",
        ),
        (
            r"(?i)\bDiaz[- ]De[- ]maria\b",
            "Díaz-de-María",
        ),
        (
            r"(?i)\bPelaez[- ]Moreno\b",
            "Peláez-Moreno",
        ),
        (
            r"(?i)\bPeláez[- ]Moreno\b",
            "Peláez-Moreno",
        ),
        (
            r"(?i)\bGallardo[- ]Antolin\b",
            "Gallardo-Antolín",
        ),
        (
            r"(?i)\bGallardo[- ]Antolín\b",
            "Gallardo-Antolín",
        ),
        (
            r"(?i)\bGonzalez[- ]Diaz\b",
            "González-Díaz",
        ),
        (
            r"(?i)\bGonzález[- ]Diaz\b",
            "González-Díaz",
        ),
        (
            r"(?i)\bGonzalez[- ]Díaz\b",
            "González-Díaz",
        ),
        (
            r"(?i)\bGonzález[- ]Díaz\b",
            "González-Díaz",
        ),
        (
            r"(?i)\bGonzález Díaz\b",
            "González-Díaz",
        ),
        (
            r"(?i)\bGonzalez Diaz\b",
            "González-Díaz",
        ),
        (
            r"(?i)\bMartinez[- ]Enriquez\b",
            "Martínez-Enríquez",
        ),
        (
            r"(?i)\bMartínez[- ]Enriquez\b",
            "Martínez-Enríquez",
        ),
        (
            r"(?i)\bMartinez[- ]Enríquez\b",
            "Martínez-Enríquez",
        ),
        (
            r"(?i)\bDe[- ]Frutos[- ]Lopez\b",
            "De-Frutos-López",
        ),
        (
            r"(?i)\bDe[- ]Frutos[- ]López\b",
            "De-Frutos-López",
        ),
        (
            r"(?i)\bDel[- ]Ama[- ]Esteban\b",
            "Del-Ama-Esteban",
        ),
        (
            r"(?i)\bSanz[- ]Rodriguez\b",
            "Sanz-Rodríguez",
        ),
        (
            r"(?i)\bSanz[- ]Rodríguez\b",
            "Sanz-Rodríguez",
        ),
        (
            r"(?i)\bGarcia[- ]Garcia\b",
            "García-García",
        ),
        (
            r"(?i)\bGarcia[- ]García\b",
            "García-García",
        ),
        (
            r"(?i)\bGarcía[- ]Garcia\b",
            "García-García",
        ),
        (
            r"(?i)\bFernandez[- ]Torres\b",
            "Fernández-Torres",
        ),
        (
            r"(?i)\bFernández[- ]Torres\b",
            "Fernández-Torres",
        ),
    ]

    for pattern, replacement in replacements:
        value = re.sub(
            pattern,
            replacement,
            value,
        )

    # --------------------------------------------------------
    # Alias explícitos
    # --------------------------------------------------------

    alias = AUTHOR_ALIASES.get(
        author_alias_key(value)
    )

    if alias:
        value = alias

    # --------------------------------------------------------
    # Casos sin formato "Apellido, inicial"
    # --------------------------------------------------------

    no_comma_alias = AUTHOR_ALIASES.get(
        author_alias_key(original)
    )

    if no_comma_alias:
        value = no_comma_alias

    return value.strip()


def normalize_author_for_match(name):
    """
    Normalización agresiva SOLO para comparar nombres.

    No utilizar esta función para escribir el BibTeX.
    """

    if not name:
        return ""

    value = normalize_author_name(name).lower()

    # Eliminar puntuación/espacios para comparación
    value = re.sub(
        r"[^a-záéíóúüñ0-9]",
        "",
        value,
    )

    return value


def register_author_variant(original_name, canonical_name):
    """
    Guarda las variantes observadas para poder generar
    author_variants.json.
    """

    if not original_name:
        return

    key = normalize_author_for_match(original_name)

    if not key:
        return

    AUTHOR_VARIANTS.setdefault(
        key,
        set(),
    ).add(original_name)

    if canonical_name:
        AUTHOR_VARIANTS[key].add(canonical_name)


# ============================================================
# ORCID: AUTORES
# ============================================================

def get_contributor_orcid(contributor):
    """
    Obtiene el ORCID de un contribuyente cuando ORCID lo proporciona.
    """

    if not isinstance(contributor, dict):
        return ""

    orcid_obj = contributor.get("contributor-orcid")

    if isinstance(orcid_obj, dict):
        for key in ("uri", "path"):
            value = orcid_obj.get(key)

            if value:
                return normalize_orcid(value)

    elif isinstance(orcid_obj, str):
        return normalize_orcid(orcid_obj)

    return ""


def extract_authors(work):
    """
    Extrae autores del trabajo.

    Devuelve:

        [
            {
                "name": "...",
                "orcid": "..."
            }
        ]
    """

    authors = []

    if not isinstance(work, dict):
        return authors

    contributors = work.get("contributors") or {}

    contributor_list = contributors.get("contributor") or []

    if not isinstance(contributor_list, list):
        contributor_list = [contributor_list]

    for contributor in contributor_list:

        if not isinstance(contributor, dict):
            continue

        credit_name = contributor.get(
            "credit-name"
        ) or {}

        if isinstance(credit_name, dict):
            original_name = clean_text(
                credit_name.get("value")
            )
        else:
            original_name = clean_text(
                credit_name
            )

        contributor_orcid = get_contributor_orcid(
            contributor
        )

        if not original_name and not contributor_orcid:
            continue

        canonical_name = normalize_author_name(
            original_name
        )

        register_author_variant(
            original_name,
            canonical_name,
        )

        authors.append({
            "name": canonical_name,
            "orcid": contributor_orcid,
        })

    return authors


def register_author(
    author,
    researcher_name="",
    researcher_orcid="",
):
    """
    Decide el nombre canónico de un autor.

    Si existe ORCID, se utiliza como identificador.
    """

    if not isinstance(author, dict):
        return ""

    original_name = clean_text(
        author.get("name")
    )

    name = normalize_author_name(
        original_name
    )

    author_orcid = normalize_orcid(
        author.get("orcid")
    )

    researcher_orcid = normalize_orcid(
        researcher_orcid
    )

    # --------------------------------------------------------
    # Si el autor es el propio investigador que estamos
    # procesando, utilizamos el nombre definido en
    # researchers1.json.
    # --------------------------------------------------------

    if (
        author_orcid
        and researcher_orcid
        and author_orcid == researcher_orcid
    ):
        researcher_canonical = normalize_author_name(
            researcher_name
        )

        if researcher_canonical:
            AUTHOR_REGISTRY[
                author_orcid
            ] = researcher_canonical

            register_author_variant(
                original_name,
                researcher_canonical,
            )

            return researcher_canonical

    # --------------------------------------------------------
    # Si tenemos ORCID del autor
    # --------------------------------------------------------

    if author_orcid:

        if author_orcid in AUTHOR_REGISTRY:
            canonical = AUTHOR_REGISTRY[
                author_orcid
            ]

            register_author_variant(
                original_name,
                canonical,
            )

            return canonical

        if name:
            AUTHOR_REGISTRY[
                author_orcid
            ] = name

            register_author_variant(
                original_name,
                name,
            )

            return name

    # --------------------------------------------------------
    # Sin ORCID
    # --------------------------------------------------------

    return name


# ============================================================
# FECHAS
# ============================================================

def get_date(date_obj):
    if not isinstance(date_obj, dict):
        return ""

    year_obj = date_obj.get("year") or {}
    month_obj = date_obj.get("month") or {}
    day_obj = date_obj.get("day") or {}

    year = (
        year_obj.get("value")
        if isinstance(year_obj, dict)
        else None
    )

    month = (
        month_obj.get("value")
        if isinstance(month_obj, dict)
        else None
    )

    day = (
        day_obj.get("value")
        if isinstance(day_obj, dict)
        else None
    )

    if not year:
        return ""

    year = str(year)

    month = (
        str(month).zfill(2)
        if month
        else "01"
    )

    day = (
        str(day).zfill(2)
        if day
        else "01"
    )

    return f"{year}-{month}-{day}"


def get_year(date_obj):
    if not isinstance(date_obj, dict):
        return ""

    year_obj = date_obj.get("year") or {}

    if not isinstance(year_obj, dict):
        return ""

    return clean_text(
        year_obj.get("value")
    )


# ============================================================
# ORCID: OBTENER GRUPOS DE TRABAJOS
# ============================================================

def get_orcid_work_groups(orcid):
    all_groups = []

    start = 0

    seen_group_keys = set()

    for page_number in range(MAX_PAGES):

        params = {
            "start": start,
            "rows": ROWS_PER_PAGE,
        }

        print(
            f"      Página ORCID "
            f"{start}-{start + ROWS_PER_PAGE}"
        )

        data = safe_get(
            f"{API_BASE}/{orcid}/works",
            params=params,
        )

        if not data:
            break

        groups = data.get("group") or []

        if not groups:
            print(
                "      No hay más grupos."
            )
            break

        print(
            f"      Grupos recibidos: "
            f"{len(groups)}"
        )

        new_groups = []

        for group in groups:

            if not isinstance(group, dict):
                continue

            summaries = group.get(
                "work-summary"
            ) or []

            if not isinstance(
                summaries,
                list,
            ):
                summaries = [
                    summaries
                ]

            put_codes = []

            for summary in summaries:

                if not isinstance(
                    summary,
                    dict,
                ):
                    continue

                put_code = summary.get(
                    "put-code"
                )

                if put_code is not None:
                    put_codes.append(
                        str(put_code)
                    )

            group_key = tuple(
                sorted(put_codes)
            )

            if (
                group_key
                and group_key in seen_group_keys
            ):
                continue

            if group_key:
                seen_group_keys.add(
                    group_key
                )

            new_groups.append(group)

        if not new_groups:
            print(
                "      AVISO: no hay grupos nuevos."
            )
            break

        all_groups.extend(
            new_groups
        )

        if len(groups) < ROWS_PER_PAGE:
            break

        start += len(groups)

    print(
        f"      Grupos obtenidos: "
        f"{len(all_groups)}"
    )

    return all_groups


def extract_all_summaries(groups):
    summaries = []

    seen_put_codes = set()

    for group in groups:

        if not isinstance(
            group,
            dict,
        ):
            continue

        group_summaries = group.get(
            "work-summary"
        ) or []

        if not isinstance(
            group_summaries,
            list,
        ):
            group_summaries = [
                group_summaries
            ]

        for summary in group_summaries:

            if not isinstance(
                summary,
                dict,
            ):
                continue

            put_code = summary.get(
                "put-code"
            )

            if put_code is None:
                continue

            put_code = str(
                put_code
            )

            if put_code in seen_put_codes:
                continue

            seen_put_codes.add(
                put_code
            )

            summaries.append(
                summary
            )

    return summaries


def get_orcid_work(
    orcid,
    put_code,
):
    url = (
        f"{API_BASE}/"
        f"{orcid}/work/"
        f"{put_code}"
    )

    return safe_get(url)


# ============================================================
# EXTRACCIÓN DE DATOS
# ============================================================

def extract_external_ids(work):
    result = {
        "doi": "",
        "pmid": "",
        "pmcid": "",
        "other_ids": [],
    }

    if not isinstance(
        work,
        dict,
    ):
        return result

    external_ids = (
        work.get(
            "external-ids"
        )
        or {}
    )

    external_id_list = (
        external_ids.get(
            "external-id"
        )
        or []
    )

    if not isinstance(
        external_id_list,
        list,
    ):
        external_id_list = [
            external_id_list
        ]

    for item in external_id_list:

        if not isinstance(
            item,
            dict,
        ):
            continue

        id_type = clean_text(
            item.get(
                "external-id-type"
            )
        ).lower()

        value = clean_text(
            item.get(
                "external-id-value"
            )
        )

        if not value:
            continue

        if id_type == "doi":

            doi = value.lower()

            doi = re.sub(
                r"^https?://doi\.org/",
                "",
                doi,
            )

            doi = doi.replace(
                "doi:",
                "",
            ).strip()

            result["doi"] = doi

        elif id_type in (
            "pmid",
            "pubmed",
        ):

            result["pmid"] = value

        elif id_type == "pmcid":

            result["pmcid"] = value

        else:

            result[
                "other_ids"
            ].append({
                "type": id_type,
                "value": value,
            })

    return result


def extract_title(work):
    if not isinstance(
        work,
        dict,
    ):
        return ""

    title_obj = (
        work.get("title")
        or {}
    )

    if not isinstance(
        title_obj,
        dict,
    ):
        return clean_text(
            title_obj
        )

    title = (
        title_obj.get(
            "title"
        )
        or {}
    )

    if isinstance(
        title,
        dict,
    ):
        return clean_text(
            title.get("value")
        )

    return clean_text(title)


def extract_journal(work):
    if not isinstance(
        work,
        dict,
    ):
        return ""

    journal = (
        work.get(
            "journal-title"
        )
        or {}
    )

    if isinstance(
        journal,
        dict,
    ):
        return clean_text(
            journal.get("value")
        )

    return clean_text(journal)


def extract_url(work):
    if not isinstance(
        work,
        dict,
    ):
        return ""

    url_obj = work.get("url")

    if isinstance(
        url_obj,
        dict,
    ):
        return clean_text(
            url_obj.get("value")
        )

    return clean_text(url_obj)


def work_to_publication(
    work,
    summary=None,
    researcher_name="",
    researcher_orcid="",
):

    if not isinstance(
        work,
        dict,
    ):
        work = {}

    if not isinstance(
        summary,
        dict,
    ):
        summary = {}

    title = (
        extract_title(work)
        or extract_title(summary)
    )

    journal = (
        extract_journal(work)
        or extract_journal(summary)
    )

    work_type = (
        clean_text(
            work.get("type")
        )
        or clean_text(
            summary.get("type")
        )
    )

    publication_date = (
        work.get(
            "publication-date"
        )
        or summary.get(
            "publication-date"
        )
        or {}
    )

    date = get_date(
        publication_date
    )

    year = get_year(
        publication_date
    )

    if not year and date:
        year = date[:4]

    identifiers = extract_external_ids(
        work
    )

    if not identifiers["doi"]:

        summary_ids = (
            extract_external_ids(
                summary
            )
        )

        for key in (
            "doi",
            "pmid",
            "pmcid",
        ):

            if (
                not identifiers[key]
                and summary_ids[key]
            ):
                identifiers[key] = (
                    summary_ids[key]
                )

    url = (
        extract_url(work)
        or extract_url(summary)
    )

    authors = extract_authors(
        work
    )

    if not authors:
        authors = extract_authors(
            summary
        )

    canonical_authors = []

    for author in authors:

        canonical_name = register_author(
            author,
            researcher_name=researcher_name,
            researcher_orcid=researcher_orcid,
        )

        if canonical_name:
            canonical_authors.append(
                canonical_name
            )

    # Eliminar autores repetidos dentro de
    # una misma publicación.
    unique_authors = []

    seen_authors = set()

    for author in canonical_authors:

        author_key = normalize_author_for_match(
            author
        )

        if author_key in seen_authors:
            continue

        seen_authors.add(
            author_key
        )

        unique_authors.append(
            author
        )

    put_code = (
        work.get("put-code")
        or summary.get("put-code")
    )

    source = (
        work.get("source")
        or summary.get("source")
        or {}
    )

    source_name = ""

    if isinstance(
        source,
        dict,
    ):
        source_name = clean_text(
            source.get(
                "source-name"
            )
        )

    return {
        "put_code": (
            str(put_code)
            if put_code is not None
            else ""
        ),
        "title": title,
        "type": work_type,
        "journal": journal,
        "date": date,
        "year": year,
        "doi": identifiers["doi"],
        "pmid": identifiers["pmid"],
        "pmcid": identifiers["pmcid"],
        "url": url,
        "authors": unique_authors,
        "source": source_name,
        "raw_type": work_type,
    }


# ============================================================
# CLASIFICACIÓN DE COMUNICACIONES DE CONGRESOS
# ============================================================

def looks_like_conference(pub):
    """
    Identifica posibles comunicaciones de congresos.

    Se incluyen:
    - conference-paper
    - conference-abstract
    - conference proceeding
    - conference presentation
    - tipos cuyo texto mencione conference/congreso
    - registros con palabras clave de congreso
      en título o revista

    Se excluyen los artículos de revista claramente
    identificados.
    """

    if not isinstance(
        pub,
        dict,
    ):
        return False

    title = clean_text(
        pub.get("title")
    )

    journal = clean_text(
        pub.get("journal")
    )

    work_type = clean_text(
        pub.get("type")
    ).lower()

    if not title:
        return False

    article_types = {
        "journal-article",
        "article",
        "journal article",
    }

    if work_type in article_types:
        return False

    conference_types = {
        "conference-paper",
        "conference-abstract",
        "conference-poster",
        "conference-presentation",
        "conference-proceedings",
        "conference proceeding",
        "conference paper",
        "conference abstract",
        "conference poster",
        "conference presentation",
        "proceedings",
    }

    if work_type in conference_types:
        return True

    combined_type = (
        work_type
        .replace("_", "-")
        .replace(" ", "-")
    )

    if "conference" in combined_type:
        return True

    if (
        "congreso" in combined_type
        or "congress" in combined_type
    ):
        return True

    keywords = (
        "conference",
        "congress",
        "congreso",
        "symposium",
        "symposio",
        "workshop",
        "meeting",
        "proceedings",
        "abstract book",
        "libro de resúmenes",
        "libro de resumenes",
        "comunicación oral",
        "comunicacion oral",
        "póster",
        "poster",
    )

    text_to_check = (
        f"{title} {journal}"
        .lower()
    )

    if any(
        keyword in text_to_check
        for keyword in keywords
    ):
        return True

    return False


# ============================================================
# DEDUPLICACIÓN
# ============================================================

def normalize_doi(doi):
    if not doi:
        return ""

    value = clean_text(
        doi
    ).lower()

    value = re.sub(
        r"^https?://doi\.org/",
        "",
        value,
    )

    value = value.replace(
        "doi:",
        "",
    )

    return value.strip()


def publication_key(pub):
    """
    Genera una clave para detectar la misma publicación.

    Prioridad:

    1. DOI
    2. PMID
    3. PMCID
    4. título + año + autores

    IMPORTANTE:

    El ORCID del investigador NO se utiliza aquí.

    Esto evita que una publicación aparezca varias veces
    simplemente porque está presente en el ORCID de varios
    investigadores.
    """

    doi = normalize_doi(
        pub.get("doi")
    )

    if doi:
        return (
            "doi",
            doi,
        )

    pmid = clean_text(
        pub.get("pmid")
    ).lower()

    if pmid:
        return (
            "pmid",
            pmid,
        )

    pmcid = clean_text(
        pub.get("pmcid")
    ).lower()

    if pmcid:
        return (
            "pmcid",
            pmcid,
        )

    title = normalize_title(
        pub.get("title")
    )

    year = clean_text(
        pub.get("year")
    )

    authors = pub.get(
        "authors"
    ) or []

    normalized_authors = []

    for author in authors:
        normalized_authors.append(
            normalize_author_for_match(
                author
            )
        )

    authors_key = tuple(
        normalized_authors
    )

    return (
        "fallback",
        title,
        year,
        authors_key,
    )


def merge_publications(
    first,
    second,
):
    """
    Combina dos registros que hemos identificado
    como la misma publicación.

    Conserva la información disponible de ambos.
    """

    merged = dict(first)

    fields = (
        "title",
        "type",
        "journal",
        "date",
        "year",
        "doi",
        "pmid",
        "pmcid",
        "url",
        "source",
    )

    for field in fields:

        if (
            not merged.get(field)
            and second.get(field)
        ):
            merged[field] = (
                second[field]
            )

    # --------------------------------------------------------
    # Autores
    # --------------------------------------------------------

    authors = []

    for author in (
        first.get("authors") or []
    ) + (
        second.get("authors") or []
    ):

        if not author:
            continue

        canonical = normalize_author_name(
            author
        )

        if not canonical:
            continue

        author_key = (
            normalize_author_for_match(
                canonical
            )
        )

        already_present = any(
            normalize_author_for_match(
                existing
            ) == author_key
            for existing in authors
        )

        if not already_present:
            authors.append(
                canonical
            )

    merged["authors"] = authors

    return merged


def deduplicate_publications(
    publications
):
    """
    Deduplica publicaciones y combina la información
    disponible en los registros duplicados.
    """

    seen = {}
    result = []

    duplicate_count = 0

    for pub in publications:

        key = publication_key(
            pub
        )

        if key in seen:

            duplicate_count += 1

            existing_index = seen[
                key
            ]

            existing = result[
                existing_index
            ]

            result[
                existing_index
            ] = merge_publications(
                existing,
                pub,
            )

            continue

        seen[key] = len(result)

        result.append(
            pub
        )

    print(
        f"      Duplicados eliminados: "
        f"{duplicate_count}"
    )

    return result


# ============================================================
# BIBTEX
# ============================================================

def bibtex_escape(text):
    """
    Escapa caracteres problemáticos para BibTeX.

    IMPORTANTE:
    No escapamos las letras acentuadas porque el archivo
    se guarda como UTF-8.
    """

    if text is None:
        return ""

    text = str(text)

    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "&": r"\&",
        "%": r"\%",
        "#": r"\#",
        "_": r"\_",
    }

    for old, new in replacements.items():
        text = text.replace(
            old,
            new,
        )

    return text


def bibtex_key_base(pub):
    """
    Genera la parte principal de una clave BibTeX.
    """

    authors = pub.get(
        "authors"
    ) or []

    if authors:

        first_author = authors[0]

        if "," in first_author:
            first_author = (
                first_author.split(
                    ",",
                    1,
                )[0]
            )

        first_author = re.sub(
            r"[^A-Za-z0-9]",
            "",
            first_author,
        )

    else:
        first_author = "Author"

    year = (
        pub.get("year")
        or "nd"
    )

    doi = normalize_doi(
        pub.get("doi")
    )

    if doi:

        suffix = re.sub(
            r"[^A-Za-z0-9]",
            "",
            doi,
        )

        suffix = suffix[-12:]

        return (
            f"{first_author}"
            f"{year}"
            f"{suffix}"
        )

    title = normalize_title(
        pub.get("title")
    )

    title_words = re.findall(
        r"[a-z0-9]+",
        title,
    )

    title_suffix = "".join(
        word[:4]
        for word in title_words[:3]
    )

    return (
        f"{first_author}"
        f"{year}"
        f"{title_suffix}"
    )


def make_bibtex_key(
    pub,
    index,
    used_keys=None,
):
    """
    Genera una clave BibTeX estable.

    Si ya existe, añade un sufijo numérico para garantizar
    que nunca haya dos claves iguales dentro del archivo.
    """

    if used_keys is None:
        used_keys = set()

    base = bibtex_key_base(
        pub
    )

    key = base

    counter = 2

    while key in used_keys:

        key = (
            f"{base}"
            f"_{counter}"
        )

        counter += 1

    used_keys.add(
        key
    )

    return key


def publication_to_bibtex(
    pub,
    index,
    used_keys,
):
    key = make_bibtex_key(
        pub,
        index,
        used_keys,
    )

    authors = pub.get(
        "authors"
    ) or []

    author_text = " and ".join(
        bibtex_escape(author)
        for author in authors
    )

    lines = [
        f"@inproceedings{{{key},",
    ]

    if pub.get("title"):
        lines.append(
            "  title = "
            f"{{{bibtex_escape(pub['title'])}}},"
        )

    if author_text:
        lines.append(
            "  author = "
            f"{{{author_text}}},"
        )

    if pub.get("journal"):
        lines.append(
            "  booktitle = "
            f"{{{bibtex_escape(pub['journal'])}}},"
        )

    if pub.get("year"):
        lines.append(
            "  year = "
            f"{{{bibtex_escape(pub['year'])}}},"
        )

    if pub.get("doi"):
        lines.append(
            "  doi = "
            f"{{{bibtex_escape(pub['doi'])}}},"
        )

    if pub.get("url"):
        lines.append(
            "  url = "
            f"{{{bibtex_escape(pub['url'])}}},"
        )

    lines.append("}")

    return "\n".join(lines)


def save_bibtex(
    publications,
    filename,
):
    entries = []

    used_keys = set()

    for index, pub in enumerate(
        publications,
        start=1,
    ):

        entries.append(
            publication_to_bibtex(
                pub,
                index,
                used_keys,
            )
        )

    with open(
        filename,
        "w",
        encoding="utf-8",
    ) as file:

        file.write(
            "\n\n".join(entries)
        )


# ============================================================
# INFORME DE VARIANTES DE AUTORES
# ============================================================

def save_author_variants(
    filename
):
    """
    Guarda únicamente las identidades que han presentado
    más de una forma textual.
    """

    result = []

    for normalized, names in AUTHOR_VARIANTS.items():

        unique_names = sorted(
            set(names)
        )

        if len(unique_names) <= 1:
            continue

        result.append({
            "normalized": normalized,
            "variants": unique_names,
        })

    result.sort(
        key=lambda item:
        item["normalized"]
    )

    save_json(
        result,
        filename,
    )

    return result


# ============================================================
# HTML
# ============================================================

def save_html(
    publications,
    filename,
):
    rows = []

    for pub in publications:

        title = html.escape(
            pub.get("title")
            or ""
        )

        journal = html.escape(
            pub.get("journal")
            or ""
        )

        year = html.escape(
            pub.get("year")
            or ""
        )

        work_type = html.escape(
            pub.get("type")
            or ""
        )

        researcher = html.escape(
            pub.get("researcher")
            or ""
        )

        doi = pub.get(
            "doi"
        ) or ""

        url = pub.get(
            "url"
        ) or ""

        if doi:

            doi_url = (
                "https://doi.org/"
                + quote(doi)
            )

            doi_html = (
                f'<a href="'
                f'{html.escape(doi_url)}" '
                f'target="_blank" '
                f'rel="noopener">'
                f'{html.escape(doi)}'
                f'</a>'
            )

        else:
            doi_html = ""

        if url:

            url_html = (
                f'<a href="'
                f'{html.escape(url)}" '
                f'target="_blank" '
                f'rel="noopener">'
                "Enlace"
                "</a>"
            )

        else:
            url_html = ""

        rows.append(
            "<tr>"
            f"<td>{researcher}</td>"
            f"<td>{title}</td>"
            f"<td>{journal}</td>"
            f"<td>{year}</td>"
            f"<td>{work_type}</td>"
            f"<td>{doi_html}</td>"
            f"<td>{url_html}</td>"
            "</tr>"
        )

    document = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport"
      content="width=device-width, initial-scale=1">
<title>Comunicaciones de congresos</title>

<style>
body {{
    font-family: Arial, sans-serif;
    margin: 30px;
}}

table {{
    border-collapse: collapse;
    width: 100%;
}}

th, td {{
    border: 1px solid #ccc;
    padding: 8px;
    vertical-align: top;
    text-align: left;
}}

th {{
    background: #eee;
}}

a {{
    overflow-wrap: anywhere;
}}
</style>
</head>

<body>

<h1>Comunicaciones de congresos</h1>

<table>

<thead>
<tr>
<th>Investigador</th>
<th>Título</th>
<th>Congreso o publicación</th>
<th>Año</th>
<th>Tipo ORCID</th>
<th>DOI</th>
<th>URL</th>
</tr>
</thead>

<tbody>
{"".join(rows)}
</tbody>

</table>

</body>
</html>
"""

    with open(
        filename,
        "w",
        encoding="utf-8",
    ) as file:

        file.write(
            document
        )


# ============================================================
# INVESTIGADORES
# ============================================================

def load_researchers(
    filename
):
    with open(
        filename,
        "r",
        encoding="utf-8",
    ) as file:

        data = json.load(
            file
        )

    if isinstance(
        data,
        dict,
    ):

        for key in (
            "researchers",
            "investigadores",
            "people",
        ):

            if key in data:

                data = data[
                    key
                ]

                break

    if not isinstance(
        data,
        list,
    ):

        raise ValueError(
            "researchers1.json debe contener "
            "una lista de investigadores."
        )

    return data


def get_researcher_name(
    researcher
):
    if not isinstance(
        researcher,
        dict,
    ):
        return "Investigador"

    for key in (
        "name",
        "nombre",
        "full_name",
        "fullname",
    ):

        if researcher.get(
            key
        ):

            return clean_text(
                researcher[key]
            )

    return "Investigador"


def get_researcher_orcid(
    researcher
):
    if not isinstance(
        researcher,
        dict,
    ):
        return ""

    for key in (
        "orcid",
        "ORCID",
        "orcid_id",
        "orcidId",
    ):

        value = researcher.get(
            key
        )

        if value:

            value = clean_text(
                value
            )

            value = re.sub(
                r"^https?://orcid\.org/",
                "",
                value,
                flags=re.IGNORECASE,
            )

            return value.strip()

    return ""


# ============================================================
# PROCESAR INVESTIGADOR
# ============================================================

def process_researcher(
    researcher,
    position,
    total,
):

    name = get_researcher_name(
        researcher
    )

    orcid = get_researcher_orcid(
        researcher
    )

    print()
    print(
        f"[{position}/{total}] "
        f"{name}"
    )

    print(
        f"      ORCID: {orcid}"
    )

    if not orcid:

        print(
            "      ERROR: investigador "
            "sin ORCID."
        )

        return []

    groups = get_orcid_work_groups(
        orcid
    )

    summaries = extract_all_summaries(
        groups
    )

    print(
        f"      Work summaries: "
        f"{len(summaries)}"
    )

    publications = []

    total_summaries = len(
        summaries
    )

    for index, summary in enumerate(
        summaries,
        start=1,
    ):

        put_code = summary.get(
            "put-code"
        )

        if put_code is None:
            continue

        if (
            index == 1
            or index % 25 == 0
            or index == total_summaries
        ):

            print(
                f"      Obras: "
                f"{index}/"
                f"{total_summaries}"
            )

        work = get_orcid_work(
            orcid,
            put_code,
        )

        if work is None:
            work = summary

        try:

            pub = work_to_publication(
                work,
                summary,
                researcher_name=name,
                researcher_orcid=orcid,
            )

            pub["researcher"] = name
            pub["orcid"] = orcid

            publications.append(
                pub
            )

        except Exception as error:

            print(
                f"      AVISO: error "
                f"procesando put-code "
                f"{put_code}: {error}"
            )

    print(
        f"      Obras recuperadas: "
        f"{len(publications)}"
    )

    return publications


# ============================================================
# GUARDAR JSON
# ============================================================

def save_json(
    data,
    filename,
):
    with open(
        filename,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )


# ============================================================
# MAIN
# ============================================================

def main():

    start_time = time.time()

    researchers = load_researchers(
        INPUT_FILE
    )

    print(
        f"Investigadores encontrados: "
        f"{len(researchers)}"
    )

    all_publications = []

    # --------------------------------------------------------
    # Recuperar publicaciones
    # --------------------------------------------------------

    for position, researcher in enumerate(
        researchers,
        start=1,
    ):

        publications = process_researcher(
            researcher,
            position,
            len(researchers),
        )

        all_publications.extend(
            publications
        )

    print()
    print(
        "=" * 70
    )
    print(
        "PROCESAMIENTO TERMINADO"
    )
    print(
        "=" * 70
    )

    print(
        f"Trabajos recuperados de ORCID: "
        f"{len(all_publications)}"
    )

    # --------------------------------------------------------
    # Guardar absolutamente todo lo recuperado
    # --------------------------------------------------------

    save_json(
        all_publications,
        OUTPUT_ALL,
    )

    # --------------------------------------------------------
    # Informe de variantes de autores
    # --------------------------------------------------------

    author_variants = save_author_variants(
        OUTPUT_AUTHOR_VARIANTS
    )

    print(
        f"Variantes de autores detectadas: "
        f"{len(author_variants)}"
    )

    # --------------------------------------------------------
    # Deduplicación
    # --------------------------------------------------------

    unique_publications = (
        deduplicate_publications(
            all_publications
        )
    )

    print(
        f"Trabajos después de deduplicar: "
        f"{len(unique_publications)}"
    )

    # --------------------------------------------------------
    # Clasificación
    # --------------------------------------------------------

    conferences = []
    excluded = []

    for pub in unique_publications:

        if looks_like_conference(
            pub
        ):

            conferences.append(
                pub
            )

        else:

            excluded.append(
                pub
            )

    # --------------------------------------------------------
    # Guardar resultados
    # --------------------------------------------------------

    save_json(
        excluded,
        OUTPUT_EXCLUDED,
    )

    save_json(
        conferences,
        OUTPUT_JSON,
    )

    save_bibtex(
        conferences,
        OUTPUT_BIB,
    )

    save_html(
        conferences,
        OUTPUT_HTML,
    )

    # --------------------------------------------------------
    # Tiempo
    # --------------------------------------------------------

    elapsed = (
        time.time()
        - start_time
    )

    print()
    print(
        "=" * 70
    )
    print(
        "RESULTADOS"
    )
    print(
        "=" * 70
    )

    print(
        f"Trabajos ORCID:        "
        f"{len(all_publications)}"
    )

    print(
        f"Tras deduplicación:    "
        f"{len(unique_publications)}"
    )

    print(
        f"Congresos incluidos:   "
        f"{len(conferences)}"
    )

    print(
        f"Trabajos excluidos:    "
        f"{len(excluded)}"
    )

    print(
        f"Variantes de autores:  "
        f"{len(author_variants)}"
    )

    print(
        f"Tiempo total:          "
        f"{elapsed:.1f} segundos"
    )

    print()
    print(
        "Archivos generados:"
    )

    print(
        f"  - {OUTPUT_ALL}"
    )

    print(
        f"  - {OUTPUT_EXCLUDED}"
    )

    print(
        f"  - {OUTPUT_JSON}"
    )

    print(
        f"  - {OUTPUT_BIB}"
    )

    print(
        f"  - {OUTPUT_HTML}"
    )

    print(
        f"  - {OUTPUT_AUTHOR_VARIANTS}"
    )

    print()
    print(
        "IMPORTANTE:"
    )

    print(
        f"Si una publicación aparece en "
        f"{OUTPUT_ALL} pero no en "
        f"{OUTPUT_BIB}, ha sido excluida "
        "por la clasificación."
    )

    print(
        f"Si no aparece en "
        f"{OUTPUT_ALL}, el problema "
        "está en la recuperación desde ORCID."
    )

    print(
        "El archivo "
        f"{OUTPUT_AUTHOR_VARIANTS} "
        "contiene las variantes de nombres "
        "detectadas durante la ejecución."
    )


# ============================================================
# EJECUCIÓN
# ============================================================

if __name__ == "__main__":
    main()
