
import os
import json
import re
import html
import unicodedata

import requests


# ============================================================
# CONFIGURACIÓN
# ============================================================

INPUT_FILE = "researchers.json"

OUTPUT_JSON = "publications.json"
OUTPUT_HTML = "publications.html"
OUTPUT_BIB = "publications.bib"

ORCID_API = "https://pub.orcid.org/v3.0"

ACCESS_TOKEN = os.getenv("ORCID_ACCESS_TOKEN")

if not ACCESS_TOKEN:
    raise RuntimeError(
        "No se ha encontrado la variable de entorno "
        "ORCID_ACCESS_TOKEN."
    )

HEADERS = {
    "Accept": "application/vnd.orcid+json",
    "Authorization": f"Bearer {ACCESS_TOKEN}",
}


# ============================================================
# PETICIONES A ORCID
# ============================================================

def orcid_get(url):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=60
    )
    response.raise_for_status()
    return response.json()


def get_orcid_works(orcid):
    """Obtiene las obras públicas de un investigador."""

    url = f"{ORCID_API}/{orcid}/works"
    data = orcid_get(url)

    return data.get("group", [])


def get_orcid_work(orcid, put_code):
    """Obtiene los datos completos de una obra."""

    url = f"{ORCID_API}/{orcid}/work/{put_code}"

    try:
        return orcid_get(url)
    except requests.HTTPError as error:
        print(f"No se pudo recuperar la obra {put_code}: {error}")
        return None


# ============================================================
# FUNCIONES AUXILIARES
# ============================================================

def normalize_text(value):
    if not value:
        return ""

    value = unicodedata.normalize("NFKC", str(value))
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def normalize_title(title):
    title = normalize_text(title).lower()
    title = unicodedata.normalize("NFKD", title)

    title = "".join(
        character
        for character in title
        if not unicodedata.combining(character)
    )

    title = re.sub(r"[^a-z0-9\s]", "", title)
    title = re.sub(r"\s+", " ", title)

    return title.strip()


def clean_doi(doi):
    if not doi:
        return ""

    doi = str(doi).strip()

    doi = re.sub(
        r"^https?://doi\.org/",
        "",
        doi,
        flags=re.IGNORECASE
    )

    doi = re.sub(
        r"^doi:\s*",
        "",
        doi,
        flags=re.IGNORECASE
    )

    return doi.strip().rstrip(" .")


def get_external_id(work, id_type):
    external_ids = (
        work.get("external-ids", {})
        .get("external-id", [])
    )

    for external_id in external_ids:
        current_type = external_id.get(
            "external-id-type", ""
        ).lower()

        if current_type == id_type:
            return normalize_text(
                external_id.get("external-id-value", "")
            )

    return ""


def get_title(work):
    title_data = work.get("title", {})
    title = title_data.get("title", {})

    return normalize_text(title.get("content", ""))


def get_publication_date(work):
    date_data = work.get("publication-date") or {}

    year = (date_data.get("year") or {}).get("value")
    month = (date_data.get("month") or {}).get("value")
    day = (date_data.get("day") or {}).get("value")

    if not year:
        return ""

    if month:
        if day:
            return f"{year}-{int(month):02d}-{int(day):02d}"

        return f"{year}-{int(month):02d}"

    return str(year)


def get_journal(work):
    journal_title = (
        work.get("journal-title") or {}
    ).get("content", "")

    return normalize_text(journal_title)


def get_url(work):
    url_data = work.get("url") or {}
    return normalize_text(url_data.get("value", ""))


def get_authors(work):
    contributors = (
        work.get("contributors") or {}
    ).get("contributor", [])

    authors = []

    for contributor in contributors:
        credit_name = (
            contributor.get("credit-name") or {}
        ).get("value", "")

        if credit_name:
            authors.append(normalize_text(credit_name))

    return authors


def get_year(work):
    date_string = get_publication_date(work)

    if date_string:
        return date_string[:4]

    return ""


def make_safe_key(text):
    text = unicodedata.normalize("NFKD", text)

    text = "".join(
        character
        for character in text
        if not unicodedata.combining(character)
    )

    text = re.sub(r"[^A-Za-z0-9]+", "", text)

    return text or "publication"


def make_bibtex_key(publication, used_keys):
    authors = publication.get("authors", [])
    year = publication.get("year", "")
    title = publication.get("title", "")

    if authors:
        first_author = authors[0].split()[-1]
    else:
        first_author = "Unknown"

    key_base = (
        make_safe_key(first_author)
        + (year or "nd")
        + make_safe_key(title)[:40]
    )

    key = key_base
    counter = 2

    while key in used_keys:
        key = f"{key_base}{counter}"
        counter += 1

    used_keys.add(key)

    return key


# ============================================================
# CONVERSIÓN DE OBRAS
# ============================================================

def work_to_publication(work, researcher):
    title = get_title(work)

    if not title:
        return None

    publication = {
        "researcher": researcher.get("name", ""),
        "orcid": researcher.get("orcid", ""),
        "title": title,
        "doi": clean_doi(get_external_id(work, "doi")),
        "url": get_url(work),
        "authors": get_authors(work),
        "year": get_year(work),
        "date": get_publication_date(work),
        "journal": get_journal(work),
        "type": work.get("type", ""),
        "put_code": work.get("put-code", ""),
    }

    return publication


# ============================================================
# ELIMINAR DUPLICADOS
# ============================================================

def deduplicate_publications(publications):
    unique = set()
    result = []

    for publication in publications:
        doi = publication.get("doi", "").lower()
        title = normalize_title(publication.get("title", ""))

        if doi:
            key = f"doi:{doi}"
        else:
            key = f"title:{title}"

        if key in unique:
            continue

        unique.add(key)
        result.append(publication)

    return result


# ============================================================
# BIBTEX
# ============================================================

def bibtex_escape(value):
    if not value:
        return ""

    replacements = {
        "&": r"\&",
        "%": r"\%",
        "#": r"\#",
        "_": r"\_",
    }

    for old, new in replacements.items():
        value = str(value).replace(old, new)

    return value


def publication_to_bibtex(publication):
    key = publication["bibtex_key"]
    authors = publication.get("authors", [])

    author_text = " and ".join(authors)

    if not author_text:
        author_text = publication.get("researcher", "")

    lines = [
        f"@article{{{key},",
        f"  title = {{{bibtex_escape(publication['title'])}}},",
    ]

    if author_text:
        lines.append(
            f"  author = {{{bibtex_escape(author_text)}}},"
        )

    if publication.get("year"):
        lines.append(
            f"  year = {{{publication['year']}}},"
        )

    if publication.get("journal"):
        lines.append(
            f"  journal = {{{bibtex_escape(publication['journal'])}}},"
        )

    if publication.get("doi"):
        lines.append(
            f"  doi = {{{publication['doi']}}},"
        )

    if publication.get("url"):
        lines.append(
            f"  url = {{{publication['url']}}},"
        )

    lines.append("}")

    return "\n".join(lines)


# ============================================================
# HTML
# ============================================================

def publication_to_html(publication):
    title = html.escape(publication.get("title", ""))
    researcher = html.escape(
        publication.get("researcher", "")
    )
    year = html.escape(publication.get("year", ""))
    journal = html.escape(publication.get("journal", ""))

    doi = publication.get("doi", "")
    url = publication.get("url", "")

    links = []

    if doi:
        doi_url = f"https://doi.org/{doi}"
        links.append(
            f'<a href="{html.escape(doi_url)}">DOI</a>'
        )

    if url:
        links.append(
            f'<a href="{html.escape(url)}">Enlace</a>'
        )

    return f"""
<article class="publication">
  <h2>{title}</h2>
  <p>
    <strong>Investigador:</strong> {researcher}<br>
    <strong>Año:</strong> {year}<br>
    <strong>Revista:</strong> {journal}
  </p>
  <p>{" | ".join(links)}</p>
</article>
"""


def create_html(publications):
    items = "\n".join(
        publication_to_html(publication)
        for publication in publications
    )

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>Publicaciones</title>
  <style>
    body {{
      font-family: Arial, sans-serif;
      max-width: 1100px;
      margin: 40px auto;
      padding: 0 20px;
    }}

    .publication {{
      border-bottom: 1px solid #ccc;
      padding: 20px 0;
    }}

    h2 {{
      font-size: 1.2em;
    }}
  </style>
</head>
<body>
  <h1>Publicaciones</h1>
  {items}
</body>
</html>
"""


# ============================================================
# PROGRAMA PRINCIPAL
# ============================================================

def main():
    with open(INPUT_FILE, "r", encoding="utf-8") as file:
        researchers = json.load(file)

    publications = []

    for researcher in researchers:
        name = researcher.get("name", "")
        orcid = researcher.get("orcid", "").strip()

        if not orcid:
            print(f"Se omite {name}: no tiene ORCID.")
            continue

        print(f"Consultando ORCID de {name}: {orcid}")

        try:
            work_groups = get_orcid_works(orcid)
        except requests.HTTPError as error:
            print(f"Error consultando {name}: {error}")
            continue

        for group in work_groups:
            summaries = group.get("work-summary", [])

            if not summaries:
                continue

            summary = summaries[0]
            put_code = summary.get("put-code")

            if not put_code:
                continue

            complete_work = get_orcid_work(orcid, put_code)

            if complete_work is None:
                complete_work = summary

            publication = work_to_publication(
                complete_work,
                researcher
            )

            if publication:
                publications.append(publication)

    publications = deduplicate_publications(publications)

    used_keys = set()

    for publication in publications:
        publication["bibtex_key"] = make_bibtex_key(
            publication,
            used_keys
        )

    publications.sort(
        key=lambda item: (
            item.get("year", ""),
            item.get("title", "").lower()
        ),
        reverse=True
    )

    with open(OUTPUT_JSON, "w", encoding="utf-8") as file:
        json.dump(
            publications,
            file,
            ensure_ascii=False,
            indent=2
        )

    with open(OUTPUT_HTML, "w", encoding="utf-8") as file:
        file.write(create_html(publications))

    bibtex_entries = "\n\n".join(
        publication_to_bibtex(publication)
        for publication in publications
    )

    with open(OUTPUT_BIB, "w", encoding="utf-8") as file:
        file.write(bibtex_entries)

    print(f"Publicaciones encontradas: {len(publications)}")
    print(f"Generado: {OUTPUT_JSON}")
    print(f"Generado: {OUTPUT_HTML}")
    print(f"Generado: {OUTPUT_BIB}")


if __name__ == "__main__":
    main()
