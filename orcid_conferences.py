import json
import os
import re
import time
import unicodedata
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
OUTPUT_AUTHOR_REVIEW = "author_review.json"

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
# SESIÓN HTTP CON REINTENTOS
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
# REGISTROS GLOBALES DE AUTORES
# ============================================================

AUTHOR_REGISTRY = {}
AUTHOR_VARIANTS = {}
AUTHOR_REVIEW = {}


# ============================================================
# ALIAS Y NORMALIZACIÓN DE AUTORES
# ============================================================

AUTHOR_ALIASES = {
    "diaz-de-maria, f.": "Díaz-de-María, F.",
    "díaz-de-maría, f.": "Díaz-de-María, F.",
    "diaz-de-maria, f": "Díaz-de-María, F.",
    "díaz-de-maría, f": "Díaz-de-María, F.",
    "diaz-de-maria,f.": "Díaz-de-María, F.",
    "díaz-de-maría,f.": "Díaz-de-María, F.",
    "pelaez-moreno, c.": "Peláez-Moreno, C.",
    "peláez-moreno, c.": "Peláez-Moreno, C.",
    "pelaez-moreno, c": "Peláez-Moreno, C.",
    "peláez-moreno, c": "Peláez-Moreno, C.",
    "pelaez-moreno,c.": "Peláez-Moreno, C.",
    "peláez-moreno,c.": "Peláez-Moreno, C.",
    "gallardo-antolin, a.": "Gallardo-Antolín, A.",
    "gallardo-antolín, a.": "Gallardo-Antolín, A.",
    "gallardo-antolin, a": "Gallardo-Antolín, A.",
    "gallardo-antolín, a": "Gallardo-Antolín, A.",
    "ascension gallardo-antolin": "Gallardo-Antolín, A.",
    "ascensión gallardo-antolín": "Gallardo-Antolín, A.",
    "gonzalez-diaz, i.": "González-Díaz, I.",
    "gonzález-diaz, i.": "González-Díaz, I.",
    "gonzalez-díaz, i.": "González-Díaz, I.",
    "gonzález-díaz, i.": "González-Díaz, I.",
    "gonzalez-diaz, i": "González-Díaz, I.",
    "gonzález-diaz, i": "González-Díaz, I.",
    "gonzalez díaz, i.": "González-Díaz, I.",
    "gonzález díaz, i.": "González-Díaz, I.",
    "gonzalez diaz, i.": "González-Díaz, I.",
    "martinez-enriquez, e.": "Martínez-Enríquez, E.",
    "martínez-enriquez, e.": "Martínez-Enríquez, E.",
    "martinez-enríquez, e.": "Martínez-Enríquez, E.",
    "martínez-enríquez, e.": "Martínez-Enríquez, E.",
    "martinez-enriquez, e": "Martínez-Enríquez, E.",
    "martínez-enríquez, e": "Martínez-Enríquez, E.",
    "de-frutos-lopez, m.": "De-Frutos-López, M.",
    "de-frutos-lópez, m.": "De-Frutos-López, M.",
    "de-frutos-lopez, m": "De-Frutos-López, M.",
    "de-frutos-lópez, m": "De-Frutos-López, M.",
    "del-ama-esteban, o.": "Del-Ama-Esteban, O.",
    "del-ama-esteban, o": "Del-Ama-Esteban, O.",
    "sanz-rodriguez, s.": "Sanz-Rodríguez, S.",
    "sanz-rodríguez, s.": "Sanz-Rodríguez, S.",
    "sanz-rodriguez, s": "Sanz-Rodríguez, S.",
    "sanz-rodríguez, s": "Sanz-Rodríguez, S.",
    "garcia-garcia, d.": "García-García, D.",
    "garcía-garcia, d.": "García-García, D.",
    "garcia-garcía, d.": "García-García, D.",
    "garcía-garcía, d.": "García-García, D.",
    "garcia-garcia, d": "García-García, D.",
    "garcía-garcía, d": "García-García, D.",
    "figueiras-vidal, a.r.": "Figueiras-Vidal, A.R.",
    "figueiras-vidal, a. r.": "Figueiras-Vidal, A.R.",
    "figueiras-vidal, ar": "Figueiras-Vidal, A.R.",
    "fernandez-torres, m.a.": "Fernández-Torres, M.-A.",
    "fernández-torres, m.a.": "Fernández-Torres, M.-A.",
    "fernandez-torres, m.-a.": "Fernández-Torres, M.-A.",
    "fernández-torres, m.-a.": "Fernández-Torres, M.-A.",
    "martinez-cortes, t.": "Martínez-Cortés, T.",
    "martínez-cortes, t.": "Martínez-Cortés, T.",
    "martinez-cortés, t.": "Martínez-Cortés, T.",
    "martínez-cortés, t": "Martínez-Cortés, T.",
    "garcia-cabellos, j.m.": "García-Cabellos, J.M.",
    "garcía-cabellos, j.m.": "García-Cabellos, J.M.",
    "garcia-cabellos, jm": "García-Cabellos, J.M.",
    "perez-cruz, f.": "Pérez-Cruz, F.",
    "pérez-cruz, f.": "Pérez-Cruz, F.",
    "perez-cruz, f": "Pérez-Cruz, F.",
    "jimenez-moreno, a.": "Jiménez-Moreno, A.",
    "jiménez-moreno, a.": "Jiménez-Moreno, A.",
    "jimenez-moreno, a": "Jiménez-Moreno, A.",
    "mejia-ocana, a.b.": "Mejía-Ocaña, A.B.",
    "mejía-ocaña, a.b.": "Mejía-Ocaña, A.B.",
    "mejia-navarrete, d.": "Mejía-Navarrete, D.",
    "mejía-navarrete, d.": "Mejía-Navarrete, D.",
    "vicente-pena, j.": "Vicente-Peña, J.",
    "vicente-peña, j.": "Vicente-Peña, J.",
    "vicente-pena, j": "Vicente-Peña, J.",
    "rodriguez-hidalgo, a.": "Rodríguez-Hidalgo, A.",
    "rodríguez-hidalgo, a.": "Rodríguez-Hidalgo, A.",
    "ludena-choez, m.": "Ludeña-Choez, M.",
    "ludeña-choez, m.": "Ludeña-Choez, M.",
    "macias-guarasa, m.": "Macías-Guarasa, M.",
    "macías-guarasa, m.": "Macías-Guarasa, M.",
    "santamaria-caballero, a.": "Santamaría-Caballero, A.",
    "santamaría-caballero, a.": "Santamaría-Caballero, A.",
    "artes-rodriguez, j.": "Artés-Rodríguez, J.",
    "artés-rodríguez, j.": "Artés-Rodríguez, J.",
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
    if not orcid:
        return ""
    value = clean_text(orcid)
    value = re.sub(r"^https?://orcid\.org/", "", value, flags=re.IGNORECASE)
    return value.strip().lower()

def safe_get(url, params=None):
    try:
        response = session.get(url, headers=HEADERS, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as error:
        print(f"      ERROR: {error}")
        return None

def _strip_diacritics(value):
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char))

def author_alias_key(name):
    if not name:
        return ""
    value = clean_text(name).lower()
    value = _strip_diacritics(value)
    value = re.sub(r"[‐‑‒–—]", "-", value)
    value = re.sub(r"[^a-z0-9]+", "", value)
    return value

def _build_author_alias_index():
    index = {}
    for alias, canonical in AUTHOR_ALIASES.items():
        key = author_alias_key(alias)
        if not key:
            continue
        index[key] = canonical
    return index

AUTHOR_ALIAS_INDEX = _build_author_alias_index()

def _normalize_initials(value):
    value = clean_text(value)
    if not value:
        return ""
    if re.fullmatch(r"(?:[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]\.?\s*)+", value):
        letters = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", value)
        if letters and len(letters) <= 4:
            return "".join(letter.upper() + "." for letter in letters)
    if re.fullmatch(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", value):
        return value.upper() + "."
    return value

def normalize_author_name(name):
    if not name:
        return ""
    original = clean_text(name)
    if not original:
        return ""
    value = re.sub(r"\s+", " ", original)
    value = re.sub(r"[‐‑‒–—]", "-", value)
    value = re.sub(r"\s*,\s*", ", ", value)
    if "," in value:
        surname, initials = value.split(",", 1)
        surname = surname.strip()
        initials = _normalize_initials(initials)
        value = f"{surname}, {initials}" if initials else surname

    alias = AUTHOR_ALIAS_INDEX.get(author_alias_key(value)) or AUTHOR_ALIAS_INDEX.get(author_alias_key(original))
    if alias:
        return alias
    return value.strip()

def normalize_author_for_match(name):
    if not name:
        return ""
    value = normalize_author_name(name).lower()
    return re.sub(r"[^a-záéíóúüñ0-9]", "", value)

def register_author_variant(original_name, canonical_name):
    if not original_name:
        return
    key = normalize_author_for_match(original_name)
    if not key:
        return
    AUTHOR_VARIANTS.setdefault(key, set()).add(original_name)
    if canonical_name:
        AUTHOR_VARIANTS[key].add(canonical_name)
    if ("," not in original_name and len(original_name.split()) > 2) or ";" in original_name:
        AUTHOR_REVIEW.setdefault(key, {
            "name": original_name,
            "canonical": canonical_name,
            "reason": "formato de nombre poco habitual",
        })

def get_contributor_orcid(contributor):
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
        credit_name = contributor.get("credit-name") or {}
        original_name = clean_text(credit_name.get("value") if isinstance(credit_name, dict) else credit_name)
        contributor_orcid = get_contributor_orcid(contributor)

        if not original_name and not contributor_orcid:
            continue

        canonical_name = normalize_author_name(original_name)
        register_author_variant(original_name, canonical_name)
        authors.append({"name": canonical_name, "orcid": contributor_orcid})

    return authors

def register_author(author, researcher_name="", researcher_orcid=""):
    if not isinstance(author, dict):
        return ""
    original_name = clean_text(author.get("name"))
    name = normalize_author_name(original_name)
    author_orcid = normalize_orcid(author.get("orcid"))
    researcher_orcid = normalize_orcid(researcher_orcid)

    if author_orcid and researcher_orcid and author_orcid == researcher_orcid:
        researcher_canonical = normalize_author_name(researcher_name)
        if researcher_canonical:
            AUTHOR_REGISTRY[author_orcid] = researcher_canonical
            register_author_variant(original_name, researcher_canonical)
            return researcher_canonical

    if author_orcid:
        if author_orcid in AUTHOR_REGISTRY:
            canonical = AUTHOR_REGISTRY[author_orcid]
            register_author_variant(original_name, canonical)
            return canonical
        if name:
            AUTHOR_REGISTRY[author_orcid] = name
            register_author_variant(original_name, name)
            return name

    return name

def get_date(date_obj):
    if not isinstance(date_obj, dict):
        return ""
    year_obj = date_obj.get("year") or {}
    month_obj = date_obj.get("month") or {}
    day_obj = date_obj.get("day") or {}

    year = year_obj.get("value") if isinstance(year_obj, dict) else None
    month = month_obj.get("value") if isinstance(month_obj, dict) else None
    day = day_obj.get("value") if isinstance(day_obj, dict) else None

    if not year:
        return ""
    return f"{year}-{str(month).zfill(2) if month else '01'}-{str(day).zfill(2) if day else '01'}"

def get_year(date_obj):
    if not isinstance(date_obj, dict):
        return ""
    year_obj = date_obj.get("year") or {}
    return clean_text(year_obj.get("value")) if isinstance(year_obj, dict) else ""


# ============================================================
# EXTRACCIÓN DE DATOS DESDE ORCID
# ============================================================

def get_orcid_work_groups(orcid):
    all_groups = []
    start = 0
    seen_group_keys = set()

    for _ in range(MAX_PAGES):
        params = {"start": start, "rows": ROWS_PER_PAGE}
        print(f"      Página ORCID {start}-{start + ROWS_PER_PAGE}")
        data = safe_get(f"{API_BASE}/{orcid}/works", params=params)
        if not data:
            break

        groups = data.get("group") or []
        if not groups:
            break

        new_groups = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            summaries = group.get("work-summary") or []
            if not isinstance(summaries, list):
                summaries = [summaries]
            put_codes = [str(s.get("put-code")) for s in summaries if isinstance(s, dict) and s.get("put-code") is not None]
            group_key = tuple(sorted(put_codes))

            if group_key and group_key not in seen_group_keys:
                seen_group_keys.add(group_key)
                new_groups.append(group)

        if not new_groups:
            break
        all_groups.extend(new_groups)
        if len(groups) < ROWS_PER_PAGE:
            break
        start += len(groups)

    return all_groups

def extract_all_summaries(groups):
    summaries = []
    seen_put_codes = set()
    for group in groups:
        if not isinstance(group, dict):
            continue
        group_summaries = group.get("work-summary") or []
        if not isinstance(group_summaries, list):
            group_summaries = [group_summaries]
        for summary in group_summaries:
            if not isinstance(summary, dict):
                continue
            put_code = summary.get("put-code")
            if put_code is None:
                continue
            put_code = str(put_code)
            if put_code not in seen_put_codes:
                seen_put_codes.add(put_code)
                summaries.append(summary)
    return summaries

def get_orcid_work(orcid, put_code):
    return safe_get(f"{API_BASE}/{orcid}/work/{put_code}")

def extract_external_ids(work):
    result = {"doi": "", "pmid": "", "pmcid": "", "other_ids": []}
    if not isinstance(work, dict):
        return result

    external_ids = work.get("external-ids") or {}
    external_id_list = external_ids.get("external-id") or []
    if not isinstance(external_id_list, list):
        external_id_list = [external_id_list]

    for item in external_id_list:
        if not isinstance(item, dict):
            continue
        id_type = clean_text(item.get("external-id-type")).lower()
        value = clean_text(item.get("external-id-value"))
        if not value:
            continue

        if id_type == "doi":
            doi = value.lower()
            doi = re.sub(r"^https?://doi\.org/", "", doi)
            result["doi"] = doi.replace("doi:", "").strip()
        elif id_type in ("pmid", "pubmed"):
            result["pmid"] = value
        elif id_type == "pmcid":
            result["pmcid"] = value
        else:
            result["other_ids"].append({"type": id_type, "value": value})

    return result

def extract_title(work):
    if not isinstance(work, dict):
        return ""
    title_obj = work.get("title") or {}
    if not isinstance(title_obj, dict):
        return clean_text(title_obj)
    title = title_obj.get("title") or {}
    return clean_text(title.get("value") if isinstance(title, dict) else title)

def extract_journal(work):
    if not isinstance(work, dict):
        return ""
    journal = work.get("journal-title") or {}
    return clean_text(journal.get("value") if isinstance(journal, dict) else journal)

def extract_url(work):
    if not isinstance(work, dict):
        return ""
    url_obj = work.get("url")
    return clean_text(url_obj.get("value") if isinstance(url_obj, dict) else url_obj)

def work_to_publication(work, summary=None, researcher_name="", researcher_orcid=""):
    if not isinstance(work, dict):
        work = {}
    if not isinstance(summary, dict):
        summary = {}

    title = extract_title(work) or extract_title(summary)
    journal = extract_journal(work) or extract_journal(summary)
    work_type = clean_text(work.get("type")) or clean_text(summary.get("type"))
    publication_date = get_date(work.get("publication-date")) or get_date(summary.get("publication-date"))
    year = get_year(work.get("publication-date")) or get_year(summary.get("publication-date"))
    url = extract_url(work) or extract_url(summary)

    external_ids = extract_external_ids(work)
    if not external_ids["doi"]:
        summary_ids = extract_external_ids(summary)
        if summary_ids["doi"]:
            external_ids["doi"] = summary_ids["doi"]

    raw_authors = extract_authors(work)
    processed_authors = []

    for author in raw_authors:
        canonical_name = register_author(
            author,
            researcher_name=researcher_name,
            researcher_orcid=researcher_orcid,
        )
        if canonical_name and canonical_name not in processed_authors:
            processed_authors.append(canonical_name)

    return {
        "title": title,
        "journal": journal,
        "type": work_type,
        "publication_date": publication_date,
        "year": year,
        "url": url,
        "doi": external_ids["doi"],
        "pmid": external_ids["pmid"],
        "pmcid": external_ids["pmcid"],
        "authors": processed_authors,
        "orcid_source": researcher_orcid,
    }


# ============================================================
# DEDUPLICACIÓN Y CLASIFICACIÓN
# ============================================================

def deduplicate_publications(publications):
    seen_dois = {}
    seen_titles = {}
    unique_pubs = []

    for pub in publications:
        doi = pub.get("doi", "").strip().lower()
        title_norm = normalize_title(pub.get("title", ""))
        year = str(pub.get("year", "")).strip()
        title_key = f"{title_norm}_{year}" if title_norm else None

        existing_pub = None

        if doi and doi in seen_dois:
            existing_pub = seen_dois[doi]
        elif title_key and title_key in seen_titles:
            existing_pub = seen_titles[title_key]

        if existing_pub:
            existing_authors = existing_pub.get("authors", [])
            for author in pub.get("authors", []):
                if author not in existing_authors:
                    existing_authors.append(author)

            for field in ("journal", "url", "publication_date", "pmid", "pmcid"):
                if not existing_pub.get(field) and pub.get(field):
                    existing_pub[field] = pub[field]
        else:
            unique_pubs.append(pub)
            if doi:
                seen_dois[doi] = pub
            if title_key:
                seen_titles[title_key] = pub

    return unique_pubs

def looks_like_conference(pub):
    # Normalizamos eliminando guiones y espacios para hacer match robusto con ORCID
    pub_type = str(pub.get("type", "")).lower().replace("-", "_").replace(" ", "_")
    journal = str(pub.get("journal", "")).lower()
    title = str(pub.get("title", "")).lower()

    # 1. Comprobación directa por tipo de documento en ORCID
    conference_types = {
        "conference_paper",
        "conference_abstract",
        "conference_poster",
        "proceeding",
        "proceedings",
    }
    if any(ctype in pub_type for ctype in conference_types):
        return True

    # 2. Búsqueda por palabras clave en la fuente/revista/libro o título
    keywords = [
        "proceedings",
        "conference",
        "symposium",
        "workshop",
        "congress",
        "congreso",
        "jornadas",
        "encuentro",
        "iain",
        "ieee",
        "acm",
        "lncs",
        "lecture notes in computer science",
        "int. conf.",
        "international conference",
    ]

    target_text = f"{journal} {title}"
    return any(kw in target_text for kw in keywords)


# ============================================================
# FUNCIONES DE GUARDADO
# ============================================================

def save_json(data, filename):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def generate_bibtex_key(pub, index):
    authors = pub.get("authors", [])
    first_author = "unknown"
    if authors:
        first_author = authors[0].split(",")[0].replace(" ", "").lower()
    year = pub.get("year") or "nodate"
    title_words = re.findall(r"\w+", pub.get("title", "").lower())
    keyword = title_words[0] if title_words else "work"
    return f"{first_author}{year}{keyword}_{index}"

def save_bibtex(publications, filename=OUTPUT_BIB):
    bib_entries = []
    for i, pub in enumerate(publications, 1):
        key = generate_bibtex_key(pub, i)
        authors = " and ".join(pub.get("authors", []))
        title = pub.get("title", "").replace("{", "\\{").replace("}", "\\}")
        booktitle_or_journal = pub.get("journal", "")
        year = pub.get("year", "")
        doi = pub.get("doi", "")
        url = pub.get("url", "")

        pub_type_raw = str(pub.get("type", "")).lower()
        entry_type = "inproceedings" if "conference" in pub_type_raw or "proceeding" in pub_type_raw else "article"

        entry = f"@{entry_type}{{{key},\n"
        entry += f"  title = {{{title}}},\n"
        if authors:
            entry += f"  author = {{{authors}}},\n"
        if entry_type == "inproceedings" and booktitle_or_journal:
            entry += f"  booktitle = {{{booktitle_or_journal}}},\n"
        elif booktitle_or_journal:
            entry += f"  journal = {{{booktitle_or_journal}}},\n"
        if year:
            entry += f"  year = {{{year}}},\n"
        if doi:
            entry += f"  doi = {{{doi}}},\n"
        if url:
            entry += f"  url = {{{url}}}\n"
        entry += "}\n"

        bib_entries.append(entry)

    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(bib_entries))

def save_html(publications, filename=OUTPUT_HTML):
    html_content = [
        "<!DOCTYPE html>",
        "<html lang='es'>",
        "<head><meta charset='utf-8'><title>Publicaciones de Congreso</title>",
        "<style>body{font-family:sans-serif;margin:20px;} .pub{margin-bottom:15px;padding:10px;border-left:3px solid #0056b3;background:#f9f9f9;} .title{font-weight:bold;} .authors{color:#555;} .meta{font-size:0.9em;color:#777;}</style>",
        "</head><body>",
        f"<h1>Publicaciones de Congreso ({len(publications)})</h1>",
    ]

    for pub in publications:
        authors = html.escape(", ".join(pub.get("authors", [])))
        title = html.escape(pub.get("title", "Sin título"))
        journal = html.escape(pub.get("journal", ""))
        year = html.escape(str(pub.get("year", "")))
        doi = pub.get("doi", "")

        doi_link = f' | <a href="https://doi.org/{html.escape(doi)}" target="_blank">DOI</a>' if doi else ""

        html_content.append(
            f'<div class="pub">'
            f'<div class="title">{title}</div>'
            f'<div class="authors">{authors}</div>'
            f'<div class="meta">{journal} ({year}){doi_link}</div>'
            f'</div>'
        )

    html_content.append("</body></html>")

    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(html_content))


# ============================================================
# FLUJO PRINCIPAL DE EJECUCIÓN
# ============================================================

def main():
    start_time = time.time()

    if not os.path.exists(INPUT_FILE):
        print(f"Error: No se encuentra el archivo de entrada {INPUT_FILE}")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        researchers = json.load(f)

    all_publications = []

    for researcher in researchers:
        name = researcher.get("name", "")
        orcid = normalize_orcid(researcher.get("orcid", ""))

        if not orcid:
            continue

        print(f"Procesando: {name} ({orcid})")
        groups = get_orcid_work_groups(orcid)
        summaries = extract_all_summaries(groups)

        for summary in summaries:
            put_code = summary.get("put-code")
            if not put_code:
                continue

            work_detail = get_orcid_work(orcid, put_code)
            if not work_detail:
                continue

            bulk_data = work_detail.get("bulk", [])
            work = bulk_data[0].get("work") if bulk_data else work_detail.get("work")

            if work:
                pub = work_to_publication(
                    work,
                    summary=summary,
                    researcher_name=name,
                    researcher_orcid=orcid,
                )
                all_publications.append(pub)

            time.sleep(0.1)

    # Guardar todas las publicaciones antes de filtrar
    save_json(all_publications, OUTPUT_ALL)

    # Deduplicación
    unique_publications = deduplicate_publications(all_publications)

    # Clasificación
    conferences = []
    excluded = []

    for pub in unique_publications:
        if looks_like_conference(pub):
            conferences.append(pub)
        else:
            excluded.append(pub)

    # Guardar resultados finales
    save_json(excluded, OUTPUT_EXCLUDED)
    save_json(conferences, OUTPUT_JSON)
    save_bibtex(conferences, OUTPUT_BIB)
    save_html(conferences, OUTPUT_HTML)

    author_variants_clean = {k: sorted(list(v)) for k, v in AUTHOR_VARIANTS.items()}
    save_json(author_variants_clean, OUTPUT_AUTHOR_VARIANTS)
    save_json(AUTHOR_REVIEW, OUTPUT_AUTHOR_REVIEW)

    # Resumen por consola
    elapsed = time.time() - start_time

    print()
    print("=" * 70)
    print("RESULTADOS")
    print("=" * 70)
    print(f"Trabajos ORCID:        {len(all_publications)}")
    print(f"Tras deduplicación:    {len(unique_publications)}")
    print(f"Congresos incluidos:   {len(conferences)}")
    print(f"Trabajos excluidos:    {len(excluded)}")
    print(f"Variantes de autores:  {len(author_variants_clean)}")
    print(f"Revisiones de autores: {len(AUTHOR_REVIEW)}")
    print(f"Tiempo total:          {elapsed:.1f} segundos")
    print()
    print("Archivos generados:")
    print(f"  - {OUTPUT_ALL}")
    print(f"  - {OUTPUT_EXCLUDED}")
    print(f"  - {OUTPUT_JSON}")
    print(f"  - {OUTPUT_BIB}")
    print(f"  - {OUTPUT_HTML}")
    print(f"  - {OUTPUT_AUTHOR_VARIANTS}")
    print(f"  - {OUTPUT_AUTHOR_REVIEW}")


if __name__ == "__main__":
    main()
