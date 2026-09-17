import json
import os
import re
import time
import html
from datetime import datetime
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ============================================================
# CONFIGURACIÓN
# ============================================================

INPUT_FILE = "researchers1.json"

OUTPUT_JSON = "publications.json"
OUTPUT_ALL = "publications_all_orcid.json"
OUTPUT_EXCLUDED = "publications_excluded.json"
OUTPUT_HTML = "publications.html"
OUTPUT_BIB = "publications.bib"

API_BASE = "https://pub.orcid.org/v3.0"

ROWS_PER_PAGE = 100
MAX_PAGES = 1000

REQUEST_TIMEOUT = 30

# Número máximo de works por petición bulk
BULK_SIZE = 100


# ============================================================
# TOKEN ORCID
# ============================================================

TOKEN = os.getenv("ORCID_ACCESS_TOKEN")

if not TOKEN:
    raise RuntimeError(
        "No se ha encontrado ORCID_ACCESS_TOKEN.\n"
        "Configura primero la variable de entorno con tu token ORCID."
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
# UTILIDADES
# ============================================================

def safe_get(url, params=None):
    """
    GET seguro con manejo de errores.
    """
    try:
        response = session.get(
            url,
            headers=HEADERS,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        return response.json()

    except requests.RequestException as e:
        print(f"      ERROR HTTP: {e}")
        return None

    except ValueError as e:
        print(f"      ERROR JSON: {e}")
        return None


def normalize_title(title):
    """
    Normaliza un título para comparar publicaciones.
    """
    if not title:
        return ""

    title = str(title).lower()

    title = re.sub(r"\s+", " ", title)
    title = re.sub(r"[^\w\s]", "", title)

    return title.strip()


def clean_text(value):
    """
    Convierte cualquier valor a texto limpio.
    """
    if value is None:
        return ""

    return str(value).strip()


# ============================================================
# FECHAS
# ============================================================

def get_date(date_obj):
    """
    Extrae una fecha ORCID tolerando campos incompletos.
    """

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

    year = str(year)

    if month:
        month = str(month).zfill(2)
    else:
        month = "01"

    if day:
        day = str(day).zfill(2)
    else:
        day = "01"

    return f"{year}-{month}-{day}"


def get_year(date_obj):
    """
    Extrae solamente el año.
    """

    if not isinstance(date_obj, dict):
        return ""

    year_obj = date_obj.get("year") or {}

    if not isinstance(year_obj, dict):
        return ""

    return clean_text(year_obj.get("value"))


# ============================================================
# ORCID - WORK GROUPS
# ============================================================

def get_orcid_work_groups(orcid):
    """
    Obtiene todas las páginas de /works.

    ORCID agrupa diferentes versiones/fuentes del mismo trabajo.
    Por eso posteriormente se recorren todos los work-summary.
    """

    all_groups = []

    start = 0

    seen_group_keys = set()

    for page_number in range(MAX_PAGES):

        params = {
            "start": start,
            "rows": ROWS_PER_PAGE,
        }

        print(
            f"      Página ORCID {start}-{start + ROWS_PER_PAGE}"
        )

        data = safe_get(
            f"{API_BASE}/{orcid}/works",
            params=params,
        )

        if not data:
            break

        groups = data.get("group") or []

        if not groups:
            print("      No hay más grupos.")
            break

        print(
            f"      Grupos recibidos: {len(groups)}"
        )

        new_groups = []

        for group in groups:

            if not isinstance(group, dict):
                continue

            summaries = group.get("work-summary") or []

            if not isinstance(summaries, list):
                summaries = [summaries]

            # Creamos una clave estable para detectar páginas repetidas.
            put_codes = []

            for summary in summaries:

                if not isinstance(summary, dict):
                    continue

                put_code = (
                    summary
                    .get("put-code")
                )

                if put_code is not None:
                    put_codes.append(
                        str(put_code)
                    )

            group_key = tuple(sorted(put_codes))

            if group_key and group_key in seen_group_keys:
                continue

            if group_key:
                seen_group_keys.add(group_key)

            new_groups.append(group)

        if not new_groups:
            print(
                "      AVISO: la página no contiene grupos nuevos."
            )
            break

        all_groups.extend(new_groups)

        # Si devuelve menos de ROWS, normalmente hemos llegado al final.
        if len(groups) < ROWS_PER_PAGE:
            break

        # MUY IMPORTANTE:
        # avanzar según los grupos recibidos.
        start += len(groups)

    print(
        f"      Grupos obtenidos: {len(all_groups)}"
    )

    return all_groups


# ============================================================
# EXTRAER TODOS LOS SUMMARIES
# ============================================================

def extract_all_summaries(groups):
    """
    Extrae todos los work-summary de todos los grupos.
    """

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

            if put_code in seen_put_codes:
                continue

            seen_put_codes.add(put_code)

            summaries.append(summary)

    return summaries


# ============================================================
# OBTENER WORK COMPLETO
# ============================================================

def get_orcid_work(orcid, put_code):
    """
    Obtiene un work completo.
    """

    url = (
        f"{API_BASE}/{orcid}/work/{put_code}"
    )

    return safe_get(url)


# ============================================================
# EXTERNAL IDS
# ============================================================

def extract_external_ids(work):
    """
    Extrae DOI, PMID, PMCID y otros identificadores.
    """

    result = {
        "doi": "",
        "pmid": "",
        "pmcid": "",
        "other_ids": [],
    }

    if not isinstance(work, dict):
        return result

    external_ids = (
        work.get("external-ids")
        or {}
    )

    external_id_list = (
        external_ids.get("external-id")
        or []
    )

    if not isinstance(external_id_list, list):
        external_id_list = [
            external_id_list
        ]

    for item in external_id_list:

        if not isinstance(item, dict):
            continue

        id_type = clean_text(
            item.get("external-id-type")
        ).lower()

        value = clean_text(
            item.get("external-id-value")
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

        elif id_type in ("pmid", "pubmed"):

            result["pmid"] = value

        elif id_type == "pmcid":

            result["pmcid"] = value

        else:

            result["other_ids"].append(
                {
                    "type": id_type,
                    "value": value,
                }
            )

    return result


# ============================================================
# TÍTULO
# ============================================================

def extract_title(work):
    """
    Extrae el título de un work ORCID.
    """

    if not isinstance(work, dict):
        return ""

    title_obj = work.get("title") or {}

    if not isinstance(title_obj, dict):
        return clean_text(title_obj)

    title = (
        title_obj.get("title")
        or {}
    )

    if isinstance(title, dict):
        return clean_text(
            title.get("value")
        )

    return clean_text(title)


# ============================================================
# REVISTA
# ============================================================

def extract_journal(work):
    """
    Extrae journal-title.
    """

    if not isinstance(work, dict):
        return ""

    journal = (
        work.get("journal-title")
        or {}
    )

    if isinstance(journal, dict):
        return clean_text(
            journal.get("value")
        )

    return clean_text(journal)


# ============================================================
# URL
# ============================================================

def extract_url(work):
    """
    Extrae URL de la publicación.
    """

    if not isinstance(work, dict):
        return ""

    url_obj = work.get("url")

    if isinstance(url_obj, dict):
        return clean_text(
            url_obj.get("value")
        )

    return clean_text(url_obj)


# ============================================================
# AUTORES
# ============================================================

def extract_authors(work):
    """
    Extrae autores de contributors.
    """

    authors = []

    if not isinstance(work, dict):
        return authors

    contributors = (
        work.get("contributors")
        or {}
    )

    contributor_list = (
        contributors.get("contributor")
        or []
    )

    if not isinstance(
        contributor_list,
        list,
    ):
        contributor_list = [
            contributor_list
        ]

    for contributor in contributor_list:

        if not isinstance(
            contributor,
            dict,
        ):
            continue

        credit_name = (
            contributor.get(
                "credit-name"
            )
            or {}
        )

        if isinstance(
            credit_name,
            dict,
        ):
            name = clean_text(
                credit_name.get(
                    "value"
                )
            )
        else:
            name = clean_text(
                credit_name
            )

        if name:
            authors.append(name)

    return authors


# ============================================================
# CONVERTIR WORK A PUBLICACIÓN
# ============================================================

def work_to_publication(work, summary=None):
    """
    Convierte un work ORCID a nuestro formato.
    """

    if not isinstance(work, dict):
        work = {}

    if not isinstance(summary, dict):
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
        work.get("publication-date")
        or summary.get("publication-date")
        or {}
    )

    date = get_date(
        publication_date
    )

    year = get_year(
        publication_date
    )

    if not year:
        year = date[:4] if date else ""

    identifiers = extract_external_ids(
        work
    )

    if not identifiers["doi"]:
        summary_ids = extract_external_ids(
            summary
        )

        if summary_ids["doi"]:
            identifiers["doi"] = (
                summary_ids["doi"]
            )

        if summary_ids["pmid"]:
            identifiers["pmid"] = (
                summary_ids["pmid"]
            )

        if summary_ids["pmcid"]:
            identifiers["pmcid"] = (
                summary_ids["pmcid"]
            )

    url = (
        extract_url(work)
        or extract_url(summary)
    )

    authors = extract_authors(work)

    if not authors:
        authors = extract_authors(summary)

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

    if isinstance(source, dict):
        source_name = clean_text(
            source.get("source-name")
            or source.get("source-name")
        )

    publication = {
        "put_code": str(put_code)
        if put_code is not None
        else "",

        "title": title,

        "type": work_type,

        "journal": journal,

        "date": date,

        "year": year,

        "doi": identifiers["doi"],

        "pmid": identifiers["pmid"],

        "pmcid": identifiers["pmcid"],

        "url": url,

        "authors": authors,

        "source": source_name,

        "raw_type": work_type,
    }

    return publication


# ============================================================
# CLASIFICACIÓN DE ARTÍCULOS
# ============================================================

def looks_like_article(pub):
    """
    Decide si una publicación debe entrar en BibTeX.

    IMPORTANTE:
    No dependemos exclusivamente de type porque ORCID
    puede contener publicaciones con clasificaciones distintas.
    """

    if not isinstance(pub, dict):
        return False

    title = clean_text(
        pub.get("title")
    )

    if not title:
        return False

    work_type = clean_text(
        pub.get("type")
    ).lower()

    journal = clean_text(
        pub.get("journal")
    )

    doi = clean_text(
        pub.get("doi")
    )

    # Tipos explícitos de artículo
    article_types = {
        "journal-article",
        "article",
        "journal article",
    }

    if work_type in article_types:
        return True

    # ORCID puede utilizar "other"
    # para publicaciones que tienen datos de revista.
    if work_type == "other" and journal:
        return True

    # Si ORCID no proporciona tipo pero hay revista + título,
    # preferimos conservarlo.
    if not work_type and journal:
        return True

    # Algunos registros tienen un tipo no estándar pero
    # contienen DOI y revista.
    if journal and doi:
        return True

    return False


# ============================================================
# DEDUPLICACIÓN
# ============================================================

def publication_key(pub):
    """
    Clave de deduplicación segura.

    Prioridad:
    1. DOI
    2. PMID
    3. PMCID
    4. título + año + revista

    NO usamos título solo.
    """

    doi = clean_text(
        pub.get("doi")
    ).lower()

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

    journal = normalize_title(
        pub.get("journal")
    )

    return (
        "fallback",
        title,
        year,
        journal,
    )


def deduplicate_publications(publications):
    """
    Elimina duplicados sin eliminar artículos distintos
    que tengan el mismo título.
    """

    seen = set()

    result = []

    for pub in publications:

        key = publication_key(pub)

        if key in seen:
            continue

        seen.add(key)

        result.append(pub)

    return result


# ============================================================
# BIBTEX
# ============================================================

def bibtex_escape(text):
    """
    Escapa caracteres problemáticos para BibTeX.
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


def make_bibtex_key(pub, index):
    """
    Genera una clave BibTeX.
    """

    authors = pub.get("authors") or []

    if authors:

        first_author = (
            authors[0]
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

    return (
        f"{first_author}"
        f"{year}"
        f"{index}"
    )


def publication_to_bibtex(
    pub,
    index,
):
    """
    Convierte una publicación en BibTeX.
    """

    key = make_bibtex_key(
        pub,
        index,
    )

    authors = pub.get(
        "authors"
    ) or []

    if authors:

        author_text = " and ".join(
            bibtex_escape(
                author
            )
            for author in authors
        )

    else:
        author_text = ""

    lines = [
        "@article{" + key + ",",
    ]

    if pub.get("title"):
        lines.append(
            "  title = {"
            + bibtex_escape(
                pub["title"]
            )
            + "},"
        )

    if author_text:
        lines.append(
            "  author = {"
            + author_text
            + "},"
        )

    if pub.get("journal"):
        lines.append(
            "  journal = {"
            + bibtex_escape(
                pub["journal"]
            )
            + "},"
        )

    if pub.get("year"):
        lines.append(
            "  year = {"
            + bibtex_escape(
                pub["year"]
            )
            + "},"
        )

    if pub.get("doi"):
        lines.append(
            "  doi = {"
            + bibtex_escape(
                pub["doi"]
            )
            + "},"
        )

    if pub.get("url"):
        lines.append(
            "  url = {"
            + bibtex_escape(
                pub["url"]
            )
            + "},"
        )

    lines.append("}")

    return "\n".join(lines)


def save_bibtex(
    publications,
    filename,
):
    """
    Guarda todas las publicaciones como BibTeX.
    """

    entries = []

    for index, pub in enumerate(
        publications,
        start=1,
    ):

        entries.append(
            publication_to_bibtex(
                pub,
                index,
            )
        )

    with open(
        filename,
        "w",
        encoding="utf-8",
    ) as f:

        f.write(
            "\n\n".join(entries)
        )


# ============================================================
# HTML
# ============================================================

def save_html(
    publications,
    filename,
):
    """
    Genera una página HTML sencilla.
    """

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
                f'<a href="{html.escape(doi_url)}">'
                f'{html.escape(doi)}'
                "</a>"
            )

        else:
            doi_html = ""

        if url:

            url_html = (
                f'<a href="{html.escape(url)}">'
                "enlace"
                "</a>"
            )

        else:
            url_html = ""

        rows.append(
            "<tr>"
            f"<td>{title}</td>"
            f"<td>{journal}</td>"
            f"<td>{year}</td>"
            f"<td>{doi_html}</td>"
            f"<td>{url_html}</td>"
            "</tr>"
        )

    document = f"""
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Publicaciones</title>

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
}}

th {{
    background: #eee;
}}

</style>

</head>

<body>

<h1>Publicaciones</h1>

<table>

<thead>

<tr>
<th>Título</th>
<th>Revista</th>
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
    ) as f:

        f.write(document)


# ============================================================
# CARGAR INVESTIGADORES
# ============================================================

def load_researchers(filename):
    """
    Carga researchers1.json.
    """

    with open(
        filename,
        "r",
        encoding="utf-8",
    ) as f:

        data = json.load(f)

    if isinstance(data, dict):

        # Posibles formatos habituales
        for key in (
            "researchers",
            "investigadores",
            "people",
        ):

            if key in data:
                data = data[key]
                break

    if not isinstance(
        data,
        list,
    ):
        raise ValueError(
            "researchers1.json debe contener una lista de investigadores."
        )

    return data


# ============================================================
# EXTRAER NOMBRE Y ORCID
# ============================================================

def get_researcher_name(researcher):

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

        if researcher.get(key):
            return clean_text(
                researcher[key]
            )

    return "Investigador"


def get_researcher_orcid(researcher):

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


# ============================================================
# PROCESAR INVESTIGADOR
# ============================================================

def process_researcher(
    researcher,
    position,
    total,
):
    """
    Procesa un investigador completo.
    """

    name = get_researcher_name(
        researcher
    )

    orcid = get_researcher_orcid(
        researcher
    )

    print()
    print(
        f"[{position}/{total}] {name}"
    )

    print(
        f"      ORCID: {orcid}"
    )

    if not orcid:

        print(
            "      ERROR: investigador sin ORCID."
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
                f"{index}/{total_summaries}"
            )

        work = get_orcid_work(
            orcid,
            put_code,
        )

        if work is None:

            # Si falla el work completo,
            # usamos el summary para no perderlo.
            work = summary

        try:

            pub = work_to_publication(
                work,
                summary,
            )

            # Guardamos también el investigador
            pub["researcher"] = name
            pub["orcid"] = orcid

            publications.append(
                pub
            )

        except Exception as e:

            print(
                f"      AVISO: error procesando "
                f"put-code {put_code}: {e}"
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
    ) as f:

        json.dump(
            data,
            f,
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
    print("=" * 70)
    print("PROCESAMIENTO TERMINADO")
    print("=" * 70)

    print(
        f"Trabajos recuperados de ORCID: "
        f"{len(all_publications)}"
    )

    # --------------------------------------------------------
    # Guardamos ABSOLUTAMENTE TODO lo recuperado
    # --------------------------------------------------------

    save_json(
        all_publications,
        OUTPUT_ALL,
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
    # Filtrar artículos
    # --------------------------------------------------------

    articles = []

    excluded = []

    for pub in unique_publications:

        if looks_like_article(pub):

            articles.append(
                pub
            )

        else:

            excluded.append(
                pub
            )

    # --------------------------------------------------------
    # Guardar excluidos
    # --------------------------------------------------------

    save_json(
        excluded,
        OUTPUT_EXCLUDED,
    )

    # --------------------------------------------------------
    # Guardar publicaciones finales
    # --------------------------------------------------------

    save_json(
        articles,
        OUTPUT_JSON,
    )

    # --------------------------------------------------------
    # BibTeX
    # --------------------------------------------------------

    save_bibtex(
        articles,
        OUTPUT_BIB,
    )

    # --------------------------------------------------------
    # HTML
    # --------------------------------------------------------

    save_html(
        articles,
        OUTPUT_HTML,
    )

    # --------------------------------------------------------
    # Estadísticas
    # --------------------------------------------------------

    elapsed = (
        time.time() - start_time
    )

    print()
    print("=" * 70)
    print("RESULTADOS")
    print("=" * 70)

    print(
        f"Trabajos ORCID:        "
        f"{len(all_publications)}"
    )

    print(
        f"Tras deduplicación:    "
        f"{len(unique_publications)}"
    )

    print(
        f"Artículos incluidos:   "
        f"{len(articles)}"
    )

    print(
        f"Trabajos excluidos:    "
        f"{len(excluded)}"
    )

    print(
        f"Tiempo total:          "
        f"{elapsed:.1f} segundos"
    )

    print()
    print("Archivos generados:")
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

    print()
    print(
        "IMPORTANTE:"
    )

    print(
        "Si una publicación aparece en "
        f"{OUTPUT_ALL} pero no en {OUTPUT_BIB}, "
        "está siendo excluida por la clasificación."
    )

    print(
        f"Si no aparece en {OUTPUT_ALL}, "
        "el problema está en la recuperación desde ORCID."
    )


# ============================================================
# EJECUCIÓN
# ============================================================

if __name__ == "__main__":
    main()
