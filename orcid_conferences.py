import json
import re
import unicodedata
import requests

# ==========================================
# CONFIGURACIÓN
# ==========================================
ORCID_ID = "0000-0001-9238-6923"  # Cambia por tu ORCID si es diferente
OUTPUT_BIB = "conferencias_orcid.bib"

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "orcid-script/2.0 (mailto:tu-email@uc3m.es)"
}

# Aliases de normalización manual si fuera necesario forzar un formato
AUTHOR_ALIASES = {
    "gallardo antolin a": "Gallardo Antolín, A.",
    "gallardo antolin ascension": "Gallardo Antolín, A.",
    "gallardoantolin a": "Gallardo Antolín, A.",
    "diaz de maria f": "Díaz de María, F.",
    "pelaez moreno c": "Peláez Moreno, C.",
}

# ==========================================
# FUNCIONES AUXILIARES DE TEXTO
# ==========================================
def strip_diacritics(text):
    """ Elimina acentos y tildes para normalizar claves de búsqueda. """
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )

def format_name_segment(segment):
    """
    Capitaliza correctamente apellidos o partes del nombre
    respetando partículas como 'de', 'del', 'la', 'van', etc.
    """
    if not segment:
        return ""
    words = segment.strip().split()
    lowercase_particles = {"de", "del", "la", "las", "los", "y", "von", "van", "di", "da"}
    
    formatted_words = []
    for i, w in enumerate(words):
        w_lower = w.lower()
        if i > 0 and w_lower in lowercase_particles:
            formatted_words.append(w_lower)
        else:
            formatted_words.append(w.capitalize())
            
    return " ".join(formatted_words)

def format_first_name_to_initials(first_name_raw):
    """
    Convierte cualquier nombre de pila ('Jorge', 'Juan Manuel', 'J.m.m.', 'J. A.')
    en sus iniciales limpias en mayúscula separadas por espacio ('J.', 'J. M.', 'J. M. M.').
    """
    if not first_name_raw:
        return ""
    
    # Expandir iniciales pegadas tipo "J.m.m." o "J.M." a "J. m. m."
    cleaned = re.sub(r"([A-Za-z])\.", r"\1 ", str(first_name_raw))
    # Separar letras mayúsculas pegadas tipo "JM" -> "J M"
    cleaned = re.sub(r"([A-Z])(?=[A-Z])", r"\1 ", cleaned)
    
    tokens = re.findall(r"\w+", cleaned)
    initials = []
    
    for token in tokens:
        if token:
            initials.append(f"{token[0].upper()}.")
            
    return " ".join(initials)

def normalize_author_name(name_raw):
    """
    Normaliza un nombre de autor a 'Apellido, I.' o 'Apellido, I. J.':
    - Convierte siempre el nombre de pila a iniciales en mayúscula.
    - Maneja 'APELLIDOS, NOMBRE' y 'NOMBRE APELLIDOS'.
    - Corrige iniciales juntas o minúsculas.
    """
    if not name_raw:
        return ""

    name = str(name_raw).replace("-", " ")
    name = re.sub(r"\s+", " ", name).strip()
    
    key = strip_diacritics(name).lower()
    key = re.sub(r"[^\w\s]", "", key).strip()

    if key in AUTHOR_ALIASES:
        return AUTHOR_ALIASES[key]

    # CASO A: Viene con coma ("APELLIDOS, NOMBRE")
    if "," in name:
        parts = name.split(",", 1)
        surname = format_name_segment(parts[0])
        initials = format_first_name_to_initials(parts[1])
        return f"{surname}, {initials}".strip(", ")

    # CASO B: Viene sin coma ("NOMBRE APELLIDOS")
    words = name.split()
    if len(words) == 1:
        return format_name_segment(words[0])
    
    # Identificar si las dos últimas palabras forman un apellido compuesto con partícula
    if len(words) > 2 and words[-2].lower() in ("de", "del", "la", "las", "los"):
        surname = format_name_segment(" ".join(words[-2:]))
        first_names = " ".join(words[:-2])
    else:
        surname = format_name_segment(words[-1])
        first_names = " ".join(words[:-1])

    initials = format_first_name_to_initials(first_names)
    return f"{surname}, {initials}".strip(", ")

# ==========================================
# EXTRACCIÓN Y CROSSREF
# ==========================================
def fetch_crossref_metadata(doi):
    """ Recupera metadatos detallados de la API de CrossRef a través del DOI. """
    url = f"https://api.crossref.org/works/{doi}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            return res.json().get("message", {})
    except Exception as e:
        print(f"  [!] Error al consultar CrossRef para DOI {doi}: {e}")
    return {}

def fetch_orcid_conferences(orcid_id):
    """ Obtiene todas las obras de tipo 'conference' o 'inproceedings' desde ORCID. """
    url = f"https://pub.orcid.org/v3.0/{orcid_id}/works"
    print(f"Consultando ORCID API para {orcid_id}...")
    
    res = requests.get(url, headers=HEADERS, timeout=15)
    if res.status_code != 200:
        print(f"Error al conectar con ORCID: Status {res.status_code}")
        return []

    data = res.json()
    group = data.get("group", [])
    publications = []

    for item in group:
        work_summaries = item.get("work-summary", [])
        if not work_summaries:
            continue
        
        summary = work_summaries[0]
        work_type = (summary.get("type") or "").lower()

        # Filtrar únicamente conferencias / actas
        if "conference" not in work_type and "proceeding" not in work_type:
            continue

        title = summary.get("title", {}).get("title", {}).get("value", "")
        year = summary.get("publication-date", {}).get("year", {}).get("value", "")
        
        # Extraer DOI y URL
        doi = None
        url_val = summary.get("url", {}).get("value", "")
        ext_ids = summary.get("external-ids", {}).get("external-id", [])
        for eid in ext_ids:
            if eid.get("external-id-type") == "doi":
                doi = eid.get("external-id-value")
                break

        authors = []
        journal = ""

        # Enriquecer datos con CrossRef si tenemos DOI
        if doi:
            cr_meta = fetch_crossref_metadata(doi)
            if cr_meta:
                if not title and "title" in cr_meta:
                    title = cr_meta["title"][0]
                
                # Nombre del congreso / actas
                if "container-title" in cr_meta and cr_meta["container-title"]:
                    journal = cr_meta["container-title"][0]
                
                # Autores desde CrossRef
                cr_authors = cr_meta.get("author", [])
                for ca in cr_authors:
                    given = ca.get("given", "")
                    family = ca.get("family", "")
                    if family and given:
                        authors.append(normalize_author_name(f"{family}, {given}"))
                    elif family:
                        authors.append(normalize_author_name(family))
                    elif given:
                        authors.append(normalize_author_name(given))

        # Normalizar la lista de autores
        authors = [a for a in authors if a]

        publications.append({
            "title": title,
            "year": year,
            "journal": journal,
            "doi": doi,
            "url": url_val,
            "authors": authors
        })

    return publications

# ==========================================
# GENERACIÓN Y GUARDADO DE BIBTEX
# ==========================================
def save_bibtex(publications, filename=OUTPUT_BIB):
    """ Genera y guarda el archivo .bib con sintaxis válida y limpia. """
    entries = []
    
    for i, pub in enumerate(publications, 1):
        first_word = re.findall(r"\w+", str(pub.get("title") or "").lower())
        kw = first_word[0] if first_word else "work"
        year = str(pub.get("year") or "nodate")
        key = f"pub_{year}_{kw}_{i}"

        # Escapar caracteres conflictivos en el título
        title = str(pub.get("title") or "").replace("{", "\\{").replace("}", "\\}")
        
        # FIX PARA BOOKTITLE: Garantizar un booktitle por defecto en @inproceedings
        booktitle = str(pub.get("journal") or "").strip()
        if not booktitle:
            booktitle = "Proceedings"

        doi = str(pub.get("doi") or "")
        url = str(pub.get("url") or "")
        authors_list = pub.get("authors") or []

        entry = f"@inproceedings{{{key},\n"
        if authors_list:
            authors_str = " and ".join(authors_list)
            entry += f"  author = {{{authors_str}}},\n"
        entry += f"  title = {{{title}}},\n"
        entry += f"  booktitle = {{{booktitle}}},\n"
        if year != "nodate":
            entry += f"  year = {{{year}}},\n"
        if doi:
            entry += f"  doi = {{{doi}}},\n"
        if url:
            entry += f"  url = {{{url}}}\n"
            
        # Limpiar la última coma sobrante si existiera antes del cierre
        entry = entry.rstrip(",\n") + "\n}\n"
        entries.append(entry)

    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(entries))

    print(f"\n¡Éxito! Se han guardado {len(publications)} entradas en '{filename}'.")

# ==========================================
# EJECUCIÓN
# ==========================================
if __name__ == "__main__":
    pubs = fetch_orcid_conferences(ORCID_ID)
    if pubs:
        save_bibtex(pubs, OUTPUT_BIB)
    else:
        print("No se encontraron publicaciones de congresos.")
