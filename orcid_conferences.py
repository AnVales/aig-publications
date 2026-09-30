import json
import os
import re
import time
import unicodedata
import html

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
# AUXILIARES DE LIMPIEZA
# ============================================================

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
            return response.json()
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
# EXTRACCIÓN DE TRABAJOS DE ORCID
# ============================================================

def get_works_from_orcid(orcid):
    url = f"{API_BASE}/{orcid}/works"
    data = safe_get(url)
    if not data:
        return []

    groups = data.get("group") or []
    publications = []

    for group in groups:
        summaries = group.get("work-summary") or []
        if not summaries:
            continue
        
        summary = summaries[0]
        
        title_obj = summary.get("title") or {}
        title = ""
        if isinstance(title_obj, dict):
            t_val = title_obj.get("title") or {}
            title = t_val.get("value") if isinstance(t_val, dict) else str(t_val)
        
        journal_obj = summary.get("journal-title") or {}
        journal = journal_obj.get("value") if isinstance(journal_obj, dict) else str(journal_obj)

        work_type = clean_text(summary.get("type"))
        
        pub_date = summary.get("publication-date") or {}
        year_obj = pub_date.get("year") or {}
        year = year_obj.get("value") if isinstance(year_obj, dict) else ""

        doi = ""
        ext_ids = summary.get("external-ids") or {}
        ext_list = ext_ids.get("external-id") or []
        for ext in ext_list:
            if isinstance(ext, dict) and str(ext.get("external-id-type")).lower() == "doi":
                doi = clean_text(ext.get("external-id-value"))
                doi = re.sub(r"^https?://doi\.org/", "", doi, flags=re.IGNORECASE)
                break

        url_obj = summary.get("url") or {}
        url_val = url_obj.get("value") if isinstance(url_obj, dict) else str(url_obj)

        if title:
            publications.append({
                "title": title,
                "journal": journal,
                "type": work_type,
                "year": year,
                "doi": doi,
                "url": url_val,
                "authors": [],
                "orcid_source": orcid
            })

    return publications


# ============================================================
# CLASIFICACIÓN DE CONGRESOS
# ============================================================

def looks_like_conference(pub):
    raw_type = str(pub.get("type", "") or "").lower()
    journal = str(pub.get("journal", "") or "").lower()
    title = str(pub.get("title", "") or "").lower()

    conf_types = ["conference", "proceeding", "poster", "abstract", "symposium", "workshop"]
    if any(ct in raw_type for ct in conf_types):
        return True

    keywords = [
        "proceedings", "conference", "symposium", "workshop", "congress", 
        "congreso", "jornadas", "encuentro", "ieee", "acm", "lncs", 
        "lecture notes", "int. conf.", "international conference", "actas"
    ]
    
    target_text = f"{journal} {title}"
    if any(kw in target_text for kw in keywords):
        return True

    if raw_type and "journal-article" not in raw_type and "journalarticle" not in raw_type:
        return True

    return False


# ============================================================
# GUARDADO DE ARCHIVOS
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
        journal = str(pub.get("journal") or "")
        doi = str(pub.get("doi") or "")
        url = str(pub.get("url") or "")

        entry = f"@inproceedings{{{key},\n"
        entry += f"  title = {{{title}}},\n"
        if journal:
            entry += f"  booktitle = {{{journal}}},\n"
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
        "<head><meta charset='utf-8'><title>Publicaciones de Congreso</title>",
        "<style>body{font-family:sans-serif;margin:20px;} .pub{margin-bottom:15px;padding:10px;border-left:3px solid #0056b3;background:#f9f9f9;} .title{font-weight:bold;} .meta{font-size:0.9em;color:#777;}</style>",
        "</head><body>",
        f"<h1>Publicaciones de Congreso ({len(publications)})</h1>",
    ]

    for pub in publications:
        title = html.escape(str(pub.get("title") or "Sin título"))
        journal = html.escape(str(pub.get("journal") or ""))
        year = html.escape(str(pub.get("year") or ""))
        doi = str(pub.get("doi") or "")
        doi_link = f' | <a href="https://doi.org/{html.escape(doi)}" target="_blank">DOI</a>' if doi else ""

        html_content.append(
            f'<div class="pub">'
            f'<div class="title">{title}</div>'
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

    conferences = []
    excluded = []

    for pub in all_publications:
        if looks_like_conference(pub):
            conferences.append(pub)
        else:
            excluded.append(pub)

    target_list = conferences
    if len(conferences) == 0 and len(all_publications) > 0:
        print("[AVISO] El filtro específico de congresos arrojó 0 resultados. Exportando TODAS las publicaciones.")
        target_list = all_publications

    print(f"Publicaciones seleccionadas para guardar: {len(target_list)}")

    save_json(target_list, OUTPUT_JSON)
    save_json(excluded, OUTPUT_EXCLUDED)
    save_bibtex(target_list, OUTPUT_BIB)
    save_html(target_list, OUTPUT_HTML)

    print("\n¡Proceso finalizado con éxito! Archivos actualizados.")

if __name__ == "__main__":
    main()
