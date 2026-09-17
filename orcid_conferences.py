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

API_BASE = "https://pub.orcid.org/v3.0"

ROWS_PER_PAGE = 100
MAX_PAGES = 1000
REQUEST_TIMEOUT = 30
BULK_SIZE = 100


# ============================================================
# AUTENTICACIÓN
# ============================================================

TOKEN = os.getenv("ORCID_ACCESS_TOKEN")

if not TOKEN:
    raise RuntimeError(
        "No se ha encontrado la variable de entorno "
        "'ORCID_ACCESS_TOKEN'."
    )

HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Bearer {TOKEN}",
}


# ============================================================
# SESIÓN HTTP CON REINTENTOS
# ============================================================

session = requests.Session()

retry_strategy = Retry(
    total=5,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"],
)

adapter = HTTPAdapter(max_retries=retry_strategy)

session.mount("https://", adapter)
session.mount("http://", adapter)


# ============================================================
# FUNCIONES AUXILIARES
# ============================================================

def safe_get(url, params=None):
    """
    Realiza una petición GET controlada.
    Devuelve un diccionario/lista JSON o None si falla.
    """

    try:
        response = session.get(
            url,
            headers=HEADERS,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code == 404:
            return None

        response.raise_for_status()

        return response.json()

    except requests.RequestException as error:
        print(f"Error consultando {url}: {error}")
        return None

    except ValueError as error:
        print(f"Respuesta JSON no válida de {url}: {error}")
        return None


def clean_text(value):
    """
    Limpia espacios y convierte valores a texto.
    """

    if value is None:
        return ""

    if isinstance(value, dict):
        value = value.get("value", "")

    return str(value).strip()


def normalize_title(title):
    """
    Normaliza un título para facilitar comparaciones.
    """

    title = clean_text(title).lower()

    title = re.sub(r"\s+", " ", title)

    title = re.sub(r"[^\w\s]", "", title, flags=re.UNICODE)

    return title.strip()


def get_date(date_object):
    """
    Extrae una fecha ORCID en formato YYYY-MM-DD.
    """

    if not date_object:
        return ""

    year = date_object.get("year", {}).get("value")
    month = date_object.get("month", {}).get("value")
    day = date_object.get("day", {}).get("value")

    if not year:
        return ""

    year = str(year)
    month = str(month).zfill(2) if month else "01"
    day = str(day).zfill(2) if day else "01"

    return f"{year}-{month}-{day}"


def get_year(date_object):
    """
    Extrae el año de una fecha ORCID.
    """

    if not date_object:
        return ""

    year = date_object.get("year", {}).get("value")

    return clean_text(year)


# ============================================================
# CONSULTAS A ORCID
# ============================================================

def get_orcid_work_groups(orcid_id):
    """
    Obtiene todas las obras registradas en ORCID,
    recorriendo todas las páginas disponibles.
    """

    all_groups = []

    for page in range(MAX_PAGES):
        offset = page * ROWS_PER_PAGE

        url = f"{API_BASE}/{orcid_id}/works"

        params = {
            "start": offset,
            "rows": ROWS_PER_PAGE,
        }

        data = safe_get(url, params=params)

        if not data:
            break

        groups = data.get("group", [])

        if not groups:
            break

        all_groups.extend(groups)

        if len(groups) < ROWS_PER_PAGE:
            break

        time.sleep(0.1)

    return all_groups


def extract_all_summaries(work_group):
    """
    Extrae los resúmenes de una obra agrupada.
    """

    summaries = work_group.get("work-summary", [])

    if not isinstance(summaries, list):
        summaries = [summaries]

    return summaries


def get_orcid_work(orcid_id, put_code):
    """
    Obtiene el detalle completo de una obra concreta.
    """

    url = f"{API_BASE}/{orcid_id}/work/{put_code}"

    return safe_get(url)


# ============================================================
# EXTRACCIÓN DE INFORMACIÓN
# ============================================================

def extract_external_ids(work):
    """
    Extrae DOI, ISBN, URL y otros identificadores externos.
    """

    external_ids = work.get("external-ids", {})

    if isinstance(external_ids, dict):
        external_ids = external_ids.get("external-id", [])

    if not isinstance(external_ids, list):
        external_ids = []

    result = {}

    for external_id in external_ids:
        id_type = clean_text(
            external_id.get("external-id-type")
        ).lower()

        id_value = clean_text(
            external_id.get("external-id-value")
        )

        id_url = external_id.get("external-id-url")

        if isinstance(id_url, dict):
            id_url = id_url.get("value", "")

        id_url = clean_text(id_url)

        if id_type and id_value:
            result[id_type] = id_value

        if id_type == "doi" and id_value:
            result["doi"] = id_value

        if id_url and "url" not in result:
            result["url"] = id_url

    return result


def extract_title(work):
    """
    Extrae el título de la publicación.
    """

    title_data = work.get("title", {})

    if isinstance(title_data, dict):
        title = title_data.get("title", "")

        if isinstance(title, dict):
            title = title.get("value", "")

        return clean_text(title)

    return clean_text(title_data)


def extract_journal(work):
    """
    Extrae el nombre de la revista o publicación.
    """

    journal_title = work.get("journal-title", "")

    if isinstance(journal_title, dict):
        journal_title = journal_title.get("value", "")

    return clean_text(journal_title)


def extract_booktitle(work):
    """
    Intenta extraer el nombre del congreso o evento.
    """

    possible_fields = [
        "conference-title",
        "booktitle",
        "conference",
        "event-title",
    ]

    for field in possible_fields:
        value = work.get(field, "")

        if isinstance(value, dict):
            value = value.get("value", "")

        value = clean_text(value)

        if value:
            return value

    return ""


def extract_url(work, external_ids):
    """
    Obtiene una URL asociada a la obra.
    """

    if external_ids.get("url"):
        return external_ids["url"]

    url_data = work.get("url", "")

    if isinstance(url_data, dict):
        url_data = url_data.get("value", "")

    return clean_text(url_data)


def extract_authors(work):
    """
    Extrae los nombres de los colaboradores de la obra.
    """

    contributors = work.get("contributors", {})

    if not isinstance(contributors, dict):
        return []

    contributor_list = contributors.get("contributor", [])

    if not isinstance(contributor_list, list):
        contributor_list = [contributor_list]

    authors = []

    for contributor in contributor_list:
        if not isinstance(contributor, dict):
            continue

        contributor_attributes = contributor.get(
            "contributor-attributes",
            {},
        )

        if isinstance(contributor_attributes, dict):
            contributor_role = clean_text(
                contributor_attributes.get(
                    "contributor-role"
                )
            ).lower()

            if contributor_role and contributor_role not in {
                "author",
                "co-author",
                "editor",
                "",
            }:
                continue

        contributor_name = contributor.get(
            "credit-name",
            "",
        )

        if isinstance(contributor_name, dict):
            contributor_name = contributor_name.get(
                "value",
                "",
            )

        contributor_name = clean_text(contributor_name)

        if contributor_name and contributor_name not in authors:
            authors.append(contributor_name)

    return authors


def work_to_publication(work, researcher_name, researcher_orcid):
    """
    Convierte una obra ORCID en un registro simplificado.
    """

    if not work:
        return None

    title = extract_title(work)

    if not title:
        return None

    external_ids = extract_external_ids(work)

    publication_type = clean_text(
        work.get("type", "")
    ).lower()

    subtype = clean_text(
        work.get("sub-type", "")
    ).lower()

    publication_date = work.get("publication-date", {})

    year = get_year(publication_date)

    date = get_date(publication_date)

    journal = extract_journal(work)

    booktitle = extract_booktitle(work)

    url = extract_url(work, external_ids)

    authors = extract_authors(work)

    if researcher_name and researcher_name not in authors:
        authors.insert(0, researcher_name)

    publication = {
        "title": title,
        "authors": authors,
        "author": researcher_name,
        "researcher_orcid": researcher_orcid,
        "type": publication_type,
        "subtype": subtype,
        "raw_type": publication_type,
        "year": year,
        "date": date,
        "journal": journal,
        "booktitle": booktitle,
        "doi": external_ids.get("doi", ""),
        "url": url,
        "put_code": work.get("put-code", ""),
        "source": "ORCID",
    }

    return publication


# ============================================================
# FILTRO DE COMUNICACIONES DE CONGRESOS
# ============================================================

def looks_like_conference(publication):
    """
    Determina si una publicación parece ser una comunicación
    de congreso según su tipo, subtipo o información textual.
    """

    publication_type = clean_text(
        publication.get("type", "")
    ).lower()

    publication_subtype = clean_text(
        publication.get("subtype", "")
    ).lower()

    title = clean_text(
        publication.get("title", "")
    ).lower()

    booktitle = clean_text(
        publication.get("booktitle", "")
    ).lower()

    journal = clean_text(
        publication.get("journal", "")
    ).lower()

    conference_types = {
        "conference-paper",
        "conference-abstract",
        "conference-poster",
        "conference-presentation",
        "conference-proceedings",
        "conference",
        "proceedings",
        "conference contribution",
        "conference contribution - paper",
        "conference contribution - poster",
    }

    if publication_type in conference_types:
        return True

    if publication_subtype in conference_types:
        return True

    combined_text = " ".join(
        [
            publication_type,
            publication_subtype,
            title,
            booktitle,
            journal,
        ]
    )

    conference_keywords = [
        "conference",
        "congress",
        "congreso",
        "congresso",
        "symposium",
        "symposia",
        "workshop",
        "meeting",
        "proceedings",
        "comunicación de congreso",
        "comunicacion de congreso",
        "comunicación",
        "comunicacion",
        "poster presentation",
        "oral presentation",
    ]

    return any(
        keyword in combined_text
        for keyword in conference_keywords
    )


# ============================================================
# DEDUPLICACIÓN
# ============================================================

def publication_key(publication):
    """
    Crea una clave para identificar publicaciones duplicadas.
    """

    doi = clean_text(
        publication.get("doi", "")
    ).lower()

    if doi:
        return f"doi:{doi}"

    title = normalize_title(
        publication.get("title", "")
    )

    year = clean_text(
        publication.get("year", "")
    )

    if title:
        return f"title:{title}|year:{year}"

    put_code = clean_text(
        publication.get("put_code", "")
    )

    return f"put-code:{put_code}"


def deduplicate_publications(publications):
    """
    Elimina publicaciones duplicadas.
    """

    unique_publications = {}

    for publication in publications:
        key = publication_key(publication)

        if key not in unique_publications:
            unique_publications[key] = publication

    return list(unique_publications.values())


# ============================================================
# BIBTEX
# ============================================================

def bibtex_escape(value):
    """
    Escapa caracteres habituales para BibTeX.
    """

    value = clean_text(value)

    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "#": r"\#",
        "_": r"\_",
    }

    for old, new in replacements.items():
        value = value.replace(old, new)

    return value


def make_bibtex_key(publication, index):
    """
    Genera una clave BibTeX.
    """

    authors = publication.get("authors", [])

    if authors:
        first_author = authors[0]
    else:
        first_author = publication.get(
            "author",
            "Unknown",
        )

    first_author = re.sub(
        r"[^A-Za-z0-9]",
        "",
        first_author,
    )

    if not first_author:
        first_author = "Unknown"

    year = publication.get("year", "")

    if not year:
        year = "nd"

    return f"{first_author}{year}_{index}"


def publication_to_bibtex(publication, index):
    """
    Convierte una comunicación de congreso a BibTeX.
    """

    key = make_bibtex_key(publication, index)

    title = bibtex_escape(
        publication.get("title", "")
    )

    authors = publication.get("authors", [])

    if authors:
        author_text = " and ".join(
            bibtex_escape(author)
            for author in authors
        )
    else:
        author_text = bibtex_escape(
            publication.get("author", "")
        )

    booktitle = publication.get("booktitle", "")

    if not booktitle:
        booktitle = publication.get("journal", "")

    booktitle = bibtex_escape(booktitle)

    year = bibtex_escape(
        publication.get("year", "")
    )

    doi = bibtex_escape(
        publication.get("doi", "")
    )

    url = bibtex_escape(
        publication.get("url", "")
    )

    entry_lines = [
        f"@inproceedings{{{key},",
        f"  title = {{{title}}},",
        f"  author = {{{author_text}}},",
    ]

    if booktitle:
        entry_lines.append(
            f"  booktitle = {{{booktitle}}},"
        )

    if year:
        entry_lines.append(
            f"  year = {{{year}}},"
        )

    if doi:
        entry_lines.append(
            f"  doi = {{{doi}}},"
        )

    if url:
        entry_lines.append(
            f"  url = {{{url}}},"
        )

    entry_lines.append("}")

    return "\n".join(entry_lines)


def save_bibtex(publications, filename):
    """
    Guarda todas las publicaciones en un archivo BibTeX.
    """

    entries = []

    for index, publication in enumerate(
        publications,
        start=1,
    ):
        entries.append(
            publication_to_bibtex(
                publication,
                index,
            )
        )

    with open(
        filename,
        "w",
        encoding="utf-8",
    ) as file:
        file.write("\n\n".join(entries))

    print(
        f"Archivo BibTeX guardado: {filename}"
    )


# ============================================================
# HTML
# ============================================================

def save_html(publications, filename):
    """
    Genera una página HTML con las comunicaciones de congresos.
    """

    rows = []

    for publication in publications:
        title = html.escape(
            publication.get("title", "")
        )

        authors = html.escape(
            ", ".join(
                publication.get("authors", [])
            )
        )

        booktitle = html.escape(
            publication.get("booktitle")
            or publication.get("journal")
            or ""
        )

        year = html.escape(
            publication.get("year", "")
        )

        doi = clean_text(
            publication.get("doi", "")
        )

        url = clean_text(
            publication.get("url", "")
        )

        if doi:
            doi_url = (
                "https://doi.org/"
                + quote(doi)
            )

            doi_html = (
                f'<a href="{html.escape(doi_url)}" '
                f'target="_blank">DOI</a>'
            )
        else:
            doi_html = ""

        if url:
            url_html = (
                f'<a href="{html.escape(url)}" '
                f'target="_blank">Enlace</a>'
            )
        else:
            url_html = ""

        row = f"""
        <tr>
            <td>{title}</td>
            <td>{authors}</td>
            <td>{booktitle}</td>
            <td>{year}</td>
            <td>{doi_html}</td>
            <td>{url_html}</td>
        </tr>
        """

        rows.append(row)

    html_content = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>Comunicaciones de congresos</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 30px;
        }}

        h1 {{
            color: #333;
        }}

        table {{
            border-collapse: collapse;
            width: 100%;
        }}

        th,
        td {{
            border: 1px solid #ddd;
            padding: 8px;
            text-align: left;
            vertical-align: top;
        }}

        th {{
            background-color: #f2f2f2;
        }}

        tr:nth-child(even) {{
            background-color: #fafafa;
        }}

        a {{
            color: #0645ad;
        }}
    </style>
</head>
<body>
    <h1>Comunicaciones de congresos</h1>

    <p>
        Total de comunicaciones:
        <strong>{len(publications)}</strong>
    </p>

    <table>
        <thead>
            <tr>
                <th>Título</th>
                <th>Autores</th>
                <th>Congreso</th>
                <th>Año</th>
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
        file.write(html_content)

    print(
        f"Archivo HTML guardado: {filename}"
    )


# ============================================================
# INVESTIGADORES
# ============================================================

def load_researchers(filename):
    """
    Carga el archivo JSON de investigadores.
    """

    with open(
        filename,
        "r",
        encoding="utf-8",
    ) as file:
        data = json.load(file)

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        if "researchers" in data:
            return data["researchers"]

        return [data]

    raise ValueError(
        "El formato de researchers1.json no es válido."
    )


def get_researcher_name(researcher):
    """
    Obtiene el nombre del investigador.
    """

    possible_fields = [
        "name",
        "nombre",
        "full_name",
        "fullname",
        "researcher_name",
    ]

    for field in possible_fields:
        value = clean_text(
            researcher.get(field, "")
        )

        if value:
            return value

    return ""


def get_researcher_orcid(researcher):
    """
    Obtiene el ORCID del investigador.
    """

    possible_fields = [
        "orcid",
        "ORCID",
        "orcid_id",
        "orcidId",
    ]

    for field in possible_fields:
        value = clean_text(
            researcher.get(field, "")
        )

        if value:
            value = value.replace(
                "https://orcid.org/",
                "",
            )

            value = value.replace(
                "http://orcid.org/",
                "",
            )

            return value.strip()

    return ""


def process_researcher(researcher):
    """
    Procesa un investigador y devuelve sus publicaciones.
    """

    researcher_name = get_researcher_name(
        researcher
    )

    researcher_orcid = get_researcher_orcid(
        researcher
    )

    if not researcher_orcid:
        print(
            f"Sin ORCID para: {researcher_name}"
        )

        return []

    print(
        f"Procesando: {researcher_name} "
        f"({researcher_orcid})"
    )

    work_groups = get_orcid_work_groups(
        researcher_orcid
    )

    publications = []

    for work_group in work_groups:
        summaries = extract_all_summaries(
            work_group
        )

        for summary in summaries:
            put_code = summary.get(
                "put-code"
            )

            if not put_code:
                continue

            work = get_orcid_work(
                researcher_orcid,
                put_code,
            )

            if not work:
                continue

            publication = work_to_publication(
                work,
                researcher_name,
                researcher_orcid,
            )

            if publication:
                publications.append(publication)

            time.sleep(0.1)

    print(
        f"  Obras recuperadas: {len(publications)}"
    )

    return publications


# ============================================================
# GUARDADO JSON
# ============================================================

def save_json(data, filename):
    """
    Guarda datos en formato JSON.
    """

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

    print(
        f"Archivo JSON guardado: {filename}"
    )


# ============================================================
# PROGRAMA PRINCIPAL
# ============================================================

def main():
    researchers = load_researchers(
        INPUT_FILE
    )

    all_publications = []

    print(
        f"Investigadores encontrados: "
        f"{len(researchers)}"
    )

    for researcher in researchers:
        publications = process_researcher(
            researcher
        )

        all_publications.extend(
            publications
        )

    print(
        f"\nTotal de obras recuperadas: "
        f"{len(all_publications)}"
    )

    # Guardar todas las obras obtenidas de ORCID
    save_json(
        all_publications,
        OUTPUT_ALL,
    )

    # Eliminar duplicados
    unique_publications = deduplicate_publications(
        all_publications
    )

    print(
        f"Total después de eliminar duplicados: "
        f"{len(unique_publications)}"
    )

    # Separar comunicaciones de congresos
    conference_publications = []

    excluded_publications = []

    for publication in unique_publications:
        if looks_like_conference(publication):
            conference_publications.append(
                publication
            )
        else:
            excluded_publications.append(
                publication
            )

    print(
        f"Comunicaciones de congresos: "
        f"{len(conference_publications)}"
    )

    print(
        f"Obras excluidas: "
        f"{len(excluded_publications)}"
    )

    # Guardar obras excluidas
    save_json(
        excluded_publications,
        OUTPUT_EXCLUDED,
    )

    # Guardar únicamente comunicaciones de congresos
    save_json(
        conference_publications,
        OUTPUT_JSON,
    )

    # Crear archivo BibTeX
    save_bibtex(
        conference_publications,
        OUTPUT_BIB,
    )

    # Crear archivo HTML
    save_html(
        conference_publications,
        OUTPUT_HTML,
    )

    print("\nProceso terminado correctamente.")
    print(f"- JSON final: {OUTPUT_JSON}")
    print(f"- JSON completo: {OUTPUT_ALL}")
    print(f"- JSON excluido: {OUTPUT_EXCLUDED}")
    print(f"- BibTeX: {OUTPUT_BIB}")
    print(f"- HTML: {OUTPUT_HTML}")


if __name__ == "__main__":
    main()
