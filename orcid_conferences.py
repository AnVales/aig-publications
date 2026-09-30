import json
import os
import re
import html
import unicodedata

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

API_BASE = "https://pub.orcid.org/v3.0"
REQUEST_TIMEOUT = 30
BULK_SIZE = 50  # Límite de put-codes por petición en ORCID


# ============================================================
# TOKEN Y SESIÓN ORCID
# ============================================================

TOKEN = os.getenv("ORCID_ACCESS_TOKEN")

if not TOKEN:
    raise RuntimeError("No se ha encontrado ORCID_ACCESS_TOKEN en las variables de entorno.")

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.orcid+json",
}

session = requests.Session()
retry = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"],
)
adapter = HTTPAdapter(max_retries=retry)
session.mount("https://", adapter)
session.mount("http://", adapter)


# ============================================================
# ALIAS Y NORMALIZACIÓN CORREGIDA DE AUTORES
# ============================================================

AUTHOR_ALIASES = {
    # Fernando Díaz-de-María
    "diaz de maria f": "Díaz de María, F.",
    "diaz de maria fernando": "Díaz de María, F.",
    "diaz de maria, f.": "Díaz de María, F.",
    "diaz de maria, fernando": "Díaz de María, F.",
    "díaz de maría, f.": "Díaz de María, F.",
    "díaz de maría, fernando": "Díaz de María, F.",
    "díaz de maría f": "Díaz de María, F.",
    "fernando diaz de maria": "Díaz de María, F.",
    "fernando díaz de maría": "Díaz de María, F.",
    
    # Carmen Peláez-Moreno
    "pelaez moreno c": "Peláez Moreno, C.",
    "pelaez moreno carmen": "Peláez Moreno, C.",
    "pelaez moreno, c.": "Peláez Moreno, C.",
    "peláez moreno, c.": "Peláez Moreno, C.",
    "carmen pelaez moreno": "Peláez Moreno, C.",
    "carmen peláez moreno": "Peláez Moreno, C.",
    
    # Ascensión Gallardo-Antolín
    "gallardo antolin a": "Gallardo Antolín, A.",
    "gallardo antolín a": "Gallardo Antolín, A.",
    "gallardo antolin, a.": "Gallardo Antolín, A.",
    "gallardo antolín, a.": "Gallardo Antolín, A.",
    "ascension gallardo antolin": "Gallardo Antolín, A.",
    "ascensión gallardo antolín": "Gallardo Antolín, A.",

    # Iván González Díaz
    "gonzalez diaz i": "González Díaz, I.",
    "gonzalez diaz, i.": "González Díaz, I.",
    "gonzález díaz, i.": "González Díaz, I.",
    "ivan gonzalez": "González Díaz, I.",
    "iván gonzález": "González Díaz, I.",
    
    # Miguel Ángel Fernández Torres
    "fernandez torres m a": "Fernández Torres, M. A.",
    "fernandez torres, m. a.": "Fernández Torres, M. A.",
    "fernández torres, m. a.": "Fernández Torres, M. A.",
    "miguel angel fernandez torres": "Fernández Torres, M. A.",
    "miguel ángel fernández torres": "Fernández Torres, M. A.",
}


def strip_diacritics(text):
    """Elimina tildes y marcas diacríticas para comparación uniforme."""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c))


def normalize_author_name(name_raw):
    """
    Normaliza el nombre de un autor sin fragmentar palabras en iniciales:
    1. Si coincide con un alias, devuelve la forma canónica.
    2. Si no, aplica Title Case limpio respetando iniciales verdaderas y apellidos.
    """
    if not name_raw:
        return ""

    # Limpieza básica
    name = str(name_raw).replace("-", " ")
    name = re.sub(r"\s+", " ", name).strip()
    
    # Búsqueda en alias (sin tildes, minúsculas, sin puntuación)
    key = strip_diacritics(name).lower()
    key = re.sub(r"[^\w\s]", "", key).strip()

    if key in AUTHOR_ALIASES:
        return AUTHOR_ALIASES[key]

    # Si viene con coma "APELLIDOS, NOMBRE"
    if "," in name:
        parts = name.split(",", 1)
        surname = parts[0].strip()
        first_name = parts[1].strip()
        
        # Formatear apellido
        surname_words = [w.capitalize() if w.lower() not in ("de", "del", "la", "las", "los", "y") else w.lower() for w in surname.split()]
        surname_formatted = " ".join(surname_words)
        
        # Formatear nombre/iniciales
        first_words = []
        for w in first_name.split():
            if len(w) == 1 or (len(w) == 2 and w.endswith(".")):
                first_words.append(w[0].upper() + ".")
            else:
                first_words.append(w.capitalize())
        first_formatted = " ".join(first_words)
        
        return f"{surname_formatted}, {first_formatted}"

    # Si viene sin coma "NOMBRE APELLIDOS"
    words = name.split()
    formatted_words = []
    for word in words:
        if len(word) == 1 or (len(word) == 2 and word.endswith(".")):
            formatted_words.append(word[0].upper() + ".")
        elif word.lower() in ("de", "del", "la", "las", "los", "y"):
            formatted_words.append(word.lower())
        else:
            formatted_words.append(word.capitalize())

    return " ".join(formatted_words)


def clean_text(value):
    if value is None:
        return ""
    return str(value).strip()


def normalize_orcid(orcid_raw):
    if not orcid_raw:
        return ""
    val = clean_text(orcid_raw)
    val = re.sub(r"^https?://[^/]+/", "", val, flags=re.IGNORECASE)
    val = re.sub(r"[^\dXX-]", "", val, flags=re.IGNORECASE)
    return val.strip()


def safe_get(url):
    try:
        response = session.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            res_json = response.json()
            return res_json if isinstance(res_json, dict) else None
        print(f"      [WARN] HTTP {response.status_code} al consultar: {url}")
        return None
    except Exception as e:
        print(f"      [ERROR] Excepción de red: {e}")
        return None


def extract_orcid_from_item(item):
    for key in ("orcid", "ORCID", "orcid_id", "orcidId", "id"):
        if key in item and item[key]:
            return normalize_orcid(item[key])
    return ""


# ============================================================
# EXTRACCIÓN DE OBRAS CON BATCHING BULK (AUTORES)
# ============================================================

def get_works_bulk_details(orcid, put_codes):
    if not put_codes:
        return {}

    details_map = {}
    
    for i in range(0, len(put_codes), BULK_SIZE):
        chunk = put_codes[i:i + BULK_SIZE]
        codes_str = ",".join(str(code) for code in chunk)
        url = f"{API_BASE}/{orcid}/works/{codes_str}"
        
        data = safe_get(url)
        if not data or not isinstance(data, dict):
            continue

        bulk_works = data.get("bulk", []) or []
        for item in bulk_works:
            work = item.get("work")
            if not work or not isinstance(work, dict):
                continue
            
            put_code = work.get("put-code")
            authors = []
            contributors = work.get("contributors", {})
            if isinstance(contributors, dict):
                contrib_list = contributors.get("contributor", []) or []
                for c in contrib_list:
                    if isinstance(c, dict):
                        credit_name = c.get("credit-name")
                        if isinstance(credit_name, dict):
                            name_val = credit_name.get("value")
                            if name_val:
                                authors.append(normalize_author_name(name_val))

            if put_code:
                details_map[put_code] = authors

    return details_map


def get_works_from_orcid(orcid):
    url = f"{API_BASE}/{orcid}/works"
    data = safe_get(url)
    if not data or not isinstance(data, dict):
        return []

    groups = data.get("group") or []
    summaries_data = []
    put_codes = []

    for group in groups:
        if not isinstance(group, dict):
            continue
        summaries = group.get("work-summary") or []
        if not summaries:
            continue
        
        summary = summaries[0]
        if isinstance(summary, dict):
            put_code = summary.get("put-code")
            if put_code:
                put_codes.append(put_code)
                summaries_data.append(summary)

    authors_map = get_works_bulk_details(orcid, put_codes)

    publications = []
    for summary in summaries_data:
        put_code = summary.get("put-code")
        
        title_obj = summary.get("title") or {}
        title = ""
        if isinstance(title_obj, dict):
            t_val = title_obj.get("title") or {}
            title = t_val.get("value") if isinstance(t_val, dict) else str(t_val)
        
        journal_obj = summary.get("journal-title") or {}
        journal = journal_obj.get("value") if isinstance(journal_obj, dict) else str(journal_obj)

        work_type = clean_text(summary.get("type"))
        
        pub_date = summary.get("publication-date") or {}
        year = ""
        if isinstance(pub_date, dict):
            year_obj = pub_date.get("year") or {}
            year = year_obj.get("value") if isinstance(year_obj, dict) else ""

        doi = ""
        ext_ids = summary.get("external-ids") or {}
        if isinstance(ext_ids, dict):
            ext_list = ext_ids.get("external-id") or []
            for ext in ext_list:
                if isinstance(ext, dict) and str(ext.get("external-id-type")).lower() == "doi":
                    doi = clean_text(ext.get("external-id-value"))
                    doi = re.sub(r"^https?://doi\.org/", "", doi, flags=re.IGNORECASE)
                    break

        url_obj = summary.get("url") or {}
        url_val = url_obj.get("value") if isinstance(url_obj, dict) else str(url_obj)

        authors = authors_map.get(put_code, [])

        if title:
            publications.append({
                "title": title,
                "journal": journal,
                "type": work_type,
                "year": year,
                "doi": doi,
                "url": url_val,
                "authors": authors,
                "orcid_source": orcid
            })

    return publications


# ============================================================
# FILTRADO EXCLUSIVO DE CONGRESOS (DESCARTA REVISTAS Y ARTICLES)
# ============================================================

def looks_like_conference(pub):
    raw_type = str(pub.get("type", "") or "").lower().replace("_", "-")
    journal = str(pub.get("journal", "") or "").lower()
    title = str(pub.get("title", "") or "").lower()

    if any(ji in raw_type for ji in ["journal-article", "journal_article"]):
        return False
    
    if any(ji in journal for ji in ["journal", "transactions", "letters", "magazine", "access", "review"]):
        if not any(cw in f"{journal} {title}" for cw in ["proceedings", "conference", "symposium", "workshop", "actas"]):
            return False

    conf_types = ["conference", "proceeding", "poster", "abstract", "symposium", "workshop"]
    if any(ct in raw_type for ct in conf_types):
        return True

    keywords = [
        "proceedings", "conference", "symposium", "workshop", "congress", 
        "congreso", "jornadas", "encuentro", "lncs", "lecture notes", 
        "int. conf.", "international conference", "actas", "icip", "icassp", "iberspeech", "interspeech"
    ]
    
    target_text = f"{journal} {title}"
    if any(kw in target_text for kw in keywords):
        return True

    return False


# ============================================================
# EXPORTACIÓN (EXCLUSIVAMENTE @inproceedings PARA BIBTEX)
# ============================================================

def save_json(data, filename):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_bibtex(publications, filename=OUTPUT_BIB):
    entries = []
    for i, pub in enumerate(publications, 1):
        first_word = re.findall(r"\w+", str(pub.get("title") or "").lower())
        kw = first_word[0] if first_word else "work"
        year = str(pub.get("year") or "nodate")
        key = f"pub_{year}_{kw}_{i}"

        title = str(pub.get("title") or "").replace("{", "\\{").replace("}", "\\}")
        booktitle = str(pub.get("journal") or "")
        doi = str(pub.get("doi") or "")
        url = str(pub.get("url") or "")
        authors_list = pub.get("authors") or []

        entry = f"@inproceedings{{{key},\n"
        if authors_list:
            authors_str = " and ".join(authors_list)
            entry += f"  author = {{{authors_str}}},\n"
        entry += f"  title = {{{title}}},\n"
        if booktitle:
            entry += f"  booktitle = {{{booktitle}}},\n"
        if year:
            entry += f"  year = {{{year}}},\n"
        if doi:
            entry += f"  doi = {{{doi}}},\n"
        if url:
            entry += f"  url = {{{url}}}\n"
        entry += "}\n"
        entries.append(entry)

    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(entries))


def save_html(publications, filename=OUTPUT_HTML):
    html_content = [
        "<!DOCTYPE html>",
        "<html lang='es'>",
        "<head><meta charset='utf-8'><title>Comunicaciones a Congresos</title>",
        "<style>body{font-family:sans-serif;margin:20px;} .pub{margin-bottom:15px;padding:10px;border-left:3px solid #0056b3;background:#f9f9f9;} .title{font-weight:bold;} .authors{color:#333;font-style:italic;margin-top:2px;} .meta{font-size:0.9em;color:#777;margin-top:2px;}</style>",
        "</head><body>",
        f"<h1>Comunicaciones a Congresos ({len(publications)})</h1>",
    ]

    for pub in publications:
        title = html.escape(str(pub.get("title") or "Sin título"))
        journal = html.escape(str(pub.get("journal") or ""))
        year = html.escape(str(pub.get("year") or ""))
        doi = str(pub.get("doi") or "")
        doi_link = f' | <a href="https://doi.org/{html.escape(doi)}" target="_blank">DOI</a>' if doi else ""
        
        authors_list = pub.get("authors") or []
        authors_str = html.escape(", ".join(authors_list)) if authors_list else ""
        authors_div = f'<div class="authors">{authors_str}</div>' if authors_str else ""

        html_content.append(
            f'<div class="pub">'
            f'<div class="title">{title}</div>'
            f'{authors_div}'
            f'<div class="meta">{journal} ({year}){doi_link}</div>'
            f'</div>'
        )

    html_content.append("</body></html>")

    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(html_content))


# ============================================================
# FLUJO PRINCIPAL
# ============================================================

def main():
    if not os.path.exists(INPUT_FILE):
        print(f"[ERROR CRÍTICO] No se encuentra el archivo {INPUT_FILE}")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        researchers = json.load(f)

    print(f"Investigadores cargados desde {INPUT_FILE}: {len(researchers)}")

    all_publications = []

    for item in researchers:
        name = item.get("name", "Investigador sin nombre")
        orcid = extract_orcid_from_item(item)

        if not orcid:
            print(f"  [OMITIDO] {name}: No se detectó un ORCID válido.")
            continue

        print(f"\nConsultando: {name} (ORCID: {orcid}) ...")
        pubs = get_works_from_orcid(orcid)
        print(f"  -> {len(pubs)} publicaciones encontradas para {name}.")
        all_publications.extend(pubs)

    print(f"\n==================================================")
    print(f"Total publicaciones obtenidas en total: {len(all_publications)}")
    print(f"==================================================")

    save_json(all_publications, OUTPUT_ALL)

    conferences = [pub for pub in all_publications if looks_like_conference(pub)]
    excluded = [pub for pub in all_publications if not looks_like_conference(pub)]

    print(f"Comunicaciones a congresos filtradas: {len(conferences)}")
    print(f"Artículos de revista u otros excluidos: {len(excluded)}")

    save_json(conferences, OUTPUT_JSON)
    save_json(excluded, OUTPUT_EXCLUDED)
    save_bibtex(conferences, OUTPUT_BIB)
    save_html(conferences, OUTPUT_HTML)

    print(f"\n¡Proceso finalizado con éxito! El archivo {OUTPUT_BIB} contiene nombres legibles y sin fragmentar.")


if __name__ == "__main__":
    main()
