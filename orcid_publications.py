import os
import json
import re
import html
import unicodedata
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ============================================================
# CONFIGURACIÓN
# ============================================================

INPUT_FILE = "researchers1.json"

OUTPUT_JSON = "publications.json"
OUTPUT_ALL_JSON = "publications_all_orcid.json"
OUTPUT_EXCLUDED_JSON = "publications_excluded.json"
OUTPUT_HTML = "publications.html"
OUTPUT_BIB = "publications.bib"

ORCID_API = "https://pub.orcid.org/v3.0"

ACCESS_TOKEN = os.getenv("ORCID_ACCESS_TOKEN")

if not ACCESS_TOKEN:
    raise RuntimeError(
        "No se ha encontrado ORCID_ACCESS_TOKEN."
    )


# ORCID permite hasta 100 trabajos en una petición bulk.
BULK_SIZE = 100

# Número de trabajos que pedimos por página de /works.
ROWS_PER_PAGE = 100


HEADERS = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Accept": "application/vnd.orcid+json",
}


# ============================================================
# SESSION HTTP
# ============================================================

def create_session():
    """
    Crea una sesión HTTP reutilizable.

    Se reutilizan conexiones y se reintentan errores temporales.
    """

    session = requests.Session()

    retry = Retry(
        total=5,
        connect=5,
        read=5,
        status=5,
        backoff_factor=1,
        status_forcelist=[
            429,
            500,
            502,
            503,
            504,
        ],
        allowed_methods=[
            "GET",
        ],
        respect_retry_after_header=True,
    )

    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=10,
        pool_maxsize=10,
    )

    session.mount(
        "https://",
        adapter,
    )

    session.headers.update(
        HEADERS
    )

    return session


SESSION = create_session()


# ============================================================
# PETICIONES
# ============================================================

def orcid_get(
    url,
    params=None,
):
    """
    GET a ORCID usando una sesión reutilizable.
    """

    response = SESSION.get(
        url,
        params=params,
        timeout=60,
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# UTILIDADES
# ============================================================

def normalize_text(value):

    if value is None:
        return ""

    value = str(value)

    value = unicodedata.normalize(
        "NFKD",
        value,
    )

    value = "".join(
        c
        for c in value
        if not unicodedata.combining(c)
    )

    value = value.lower()

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def clean_text(value):

    if value is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value),
    ).strip()


def remove_html_tags(value):

    if not value:
        return ""

    value = re.sub(
        r"<[^>]+>",
        " ",
        str(value),
    )

    return html.unescape(value)


def clean_doi(doi):

    if not doi:
        return ""

    doi = str(doi).strip()

    doi = re.sub(
        r"^(https?://)?(dx\.)?doi\.org/",
        "",
        doi,
        flags=re.IGNORECASE,
    )

    return doi.rstrip(".,;")


def safe_bibtex(value):

    if value is None:
        return ""

    value = str(value)

    value = value.replace(
        "\\",
        "\\textbackslash{}",
    )

    value = value.replace(
        "&",
        r"\&",
    )

    value = value.replace(
        "%",
        r"\%",
    )

    value = value.replace(
        "#",
        r"\#",
    )

    value = value.replace(
        "_",
        r"\_",
    )

    return value


# ============================================================
# OBTENER TODOS LOS WORK GROUPS
# ============================================================

def get_orcid_work_groups(orcid):

    all_groups = []

    start = 0

    while True:

        url = (
            f"{ORCID_API}/"
            f"{orcid}/works"
        )

        params = {
            "start": start,
            "rows": ROWS_PER_PAGE,
        }

        data = orcid_get(
            url,
            params=params,
        )

        groups = data.get(
            "group",
            [],
        )

        if not groups:
            break

        all_groups.extend(
            groups
        )

        print(
            f"      Página ORCID "
            f"{start}-{start + len(groups) - 1}"
            f" | grupos: {len(groups)}"
        )

        if len(groups) < ROWS_PER_PAGE:
            break

        start += ROWS_PER_PAGE

    return all_groups


# ============================================================
# EXTRAER TODOS LOS SUMMARIES
# ============================================================

def extract_all_summaries(groups):

    summaries = []

    seen_put_codes = set()

    for group in groups:

        group_summaries = group.get(
            "work-summary",
            [],
        )

        for summary in group_summaries:

            put_code = summary.get(
                "put-code"
            )

            if not put_code:
                continue

            # Evitamos repetir exactamente
            # el mismo put-code.
            if put_code in seen_put_codes:
                continue

            seen_put_codes.add(
                put_code
            )

            summaries.append(
                summary
            )

    return summaries


# ============================================================
# RECUPERACIÓN BULK
# ============================================================

def get_orcid_works_bulk(
    orcid,
    put_codes,
):
    """
    Recupera trabajos completos en bloques de hasta 100.

    En lugar de:

        /work/1
        /work/2
        /work/3
        ...

    hacemos:

        /works/1,2,3,...,100

    """

    works_by_put_code = {}

    put_codes = [
        str(x)
        for x in put_codes
        if x
    ]

    total = len(put_codes)

    for start in range(
        0,
        total,
        BULK_SIZE,
    ):

        batch = put_codes[
            start:start + BULK_SIZE
        ]

        codes = ",".join(
            batch
        )

        url = (
            f"{ORCID_API}/"
            f"{orcid}/works/"
            f"{codes}"
        )

        try:

            data = orcid_get(
                url
            )

        except Exception as exc:

            print(
                f"      ERROR bulk "
                f"{start + 1}-{start + len(batch)}: "
                f"{exc}"
            )

            continue

        # ORCID puede devolver diferentes
        # envoltorios dependiendo del endpoint.
        #
        # Intentamos localizar la lista
        # de trabajos de forma robusta.

        works = []

        if isinstance(data, dict):

            if isinstance(
                data.get("work"),
                list,
            ):
                works = data["work"]

            elif isinstance(
                data.get("works"),
                dict,
            ):

                works = data[
                    "works"
                ].get(
                    "work",
                    [],
                )

            elif isinstance(
                data.get("works"),
                list,
            ):

                works = data["works"]

        # En algunos casos podría venir
        # un único objeto.
        if isinstance(
            works,
            dict,
        ):
            works = [works]

        for work in works:

            if not isinstance(
                work,
                dict,
            ):
                continue

            put_code = work.get(
                "put-code"
            )

            if put_code is None:

                # Intentar obtenerlo desde path.
                path = work.get(
                    "path",
                    "",
                )

                match = re.search(
                    r"/work/(\d+)",
                    str(path),
                )

                if match:
                    put_code = match.group(1)

            if put_code is None:
                continue

            works_by_put_code[
                str(put_code)
            ] = work

        print(
            f"      Bulk "
            f"{start + 1}-{start + len(batch)}"
            f"/{total}"
            f" -> {len(works)} trabajos"
        )

    return works_by_put_code


# ============================================================
# EXTERNAL IDS
# ============================================================

def extract_external_ids(work):

    result = {}

    external_ids_obj = work.get(
        "external-ids",
        {},
    )

    if isinstance(
        external_ids_obj,
        dict,
    ):

        external_ids = (
            external_ids_obj.get(
                "external-id",
                []
            )
        )

    else:

        external_ids = []

    if isinstance(
        external_ids,
        dict,
    ):
        external_ids = [
            external_ids
        ]

    for ext in external_ids:

        ext_type = clean_text(
            ext.get(
                "external-id-type",
                "",
            )
        ).lower()

        ext_value = clean_text(
            ext.get(
                "external-id-value",
                "",
            )
        )

        if not ext_type or not ext_value:
            continue

        result.setdefault(
            ext_type,
            [],
        ).append(
            ext_value
        )

    return result


def get_first_external_id(
    external_ids,
    names,
):

    for name in names:

        values = external_ids.get(
            name,
            [],
        )

        if values:
            return values[0]

    return ""


# ============================================================
# TÍTULO
# ============================================================

def extract_title(work):

    title_obj = work.get(
        "title",
        {},
    )

    if not title_obj:
        return ""

    title = title_obj.get(
        "title",
        "",
    )

    if isinstance(
        title,
        dict,
    ):
        title = title.get(
            "value",
            "",
        )

    return clean_text(
        remove_html_tags(
            title
        )
    )


# ============================================================
# FECHA
# ============================================================

def extract_date(work):

    publication_date = work.get(
        "publication-date",
        {},
    )

    if not publication_date:
        return {
            "year": "",
            "month": "",
            "day": "",
        }

    def get_value(obj):

        if isinstance(
            obj,
            dict,
        ):
            return obj.get(
                "value",
                "",
            )

        return obj or ""

    return {
        "year": str(
            get_value(
                publication_date.get(
                    "year",
                    "",
                )
            )
        ),
        "month": str(
            get_value(
                publication_date.get(
                    "month",
                    "",
                )
            )
        ),
        "day": str(
            get_value(
                publication_date.get(
                    "day",
                    "",
                )
            )
        ),
    }


# ============================================================
# REVISTA
# ============================================================

def extract_journal(work):

    journal = work.get(
        "journal-title",
        "",
    )

    if isinstance(
        journal,
        dict,
    ):
        journal = journal.get(
            "value",
            "",
        )

    return clean_text(
        journal
    )


# ============================================================
# URL
# ============================================================

def extract_url(
    work,
    doi,
):

    url_obj = work.get(
        "url",
        "",
    )

    if isinstance(
        url_obj,
        dict,
    ):
        url_obj = url_obj.get(
            "value",
            "",
        )

    url = clean_text(
        url_obj
    )

    if url:
        return url

    if doi:
        return (
            f"https://doi.org/{doi}"
        )

    return ""


# ============================================================
# AUTORES
# ============================================================

def extract_authors(work):

    contributors_obj = work.get(
        "contributors",
        {},
    )

    if not isinstance(
        contributors_obj,
        dict,
    ):
        return []

    contributors = (
        contributors_obj.get(
            "contributor",
            [],
        )
    )

    if isinstance(
        contributors,
        dict,
    ):
        contributors = [
            contributors
        ]

    authors = []

    for contributor in contributors:

        credit_name = (
            contributor.get(
                "credit-name",
                {},
            )
        )

        if isinstance(
            credit_name,
            dict,
        ):
            name = credit_name.get(
                "value",
                "",
            )
        else:
            name = credit_name

        name = clean_text(
            name
        )

        if name:
            authors.append(
                name
            )

    return authors


# ============================================================
# TIPO
# ============================================================

def extract_type(work):

    return clean_text(
        work.get(
            "type",
            "",
        )
    ).lower()


# ============================================================
# DETECTAR ARTÍCULO
# ============================================================

ARTICLE_TYPES = {
    "journal-article",
}


def looks_like_article(
    publication
):

    publication_type = (
        publication.get(
            "type",
            "",
        )
        .lower()
        .strip()
    )

    journal = clean_text(
        publication.get(
            "journal",
            "",
        )
    )

    # Clasificación explícita de ORCID.
    if publication_type in ARTICLE_TYPES:
        return True

    # Algunos registros pueden estar
    # clasificados como "other" pero tener
    # claramente una revista.
    if (
        publication_type == "other"
        and journal
    ):
        return True

    return False


# ============================================================
# WORK -> PUBLICATION
# ============================================================

def work_to_publication(
    researcher,
    orcid,
    work,
    put_code,
):

    if not work:
        return None

    title = extract_title(
        work
    )

    if not title:
        return None

    external_ids = (
        extract_external_ids(
            work
        )
    )

    doi = clean_doi(
        get_first_external_id(
            external_ids,
            [
                "doi",
            ],
        )
    )

    pmid = get_first_external_id(
        external_ids,
        [
            "pmid",
            "pubmed",
        ],
    )

    pmcid = get_first_external_id(
        external_ids,
        [
            "pmcid",
        ],
    )

    issn = get_first_external_id(
        external_ids,
        [
            "issn",
            "issn-print",
            "issn-electronic",
        ],
    )

    date = extract_date(
        work
    )

    year = date["year"]
    month = date["month"]
    day = date["day"]

    publication_date = "-".join(
        x
        for x in [
            year,
            month,
            day,
        ]
        if x
    )

    journal = extract_journal(
        work
    )

    authors = extract_authors(
        work
    )

    publication_type = extract_type(
        work
    )

    url = extract_url(
        work,
        doi,
    )

    return {
        "researcher": researcher,
        "orcid": orcid,
        "title": title,
        "doi": doi,
        "pmid": pmid,
        "pmcid": pmcid,
        "issn": issn,
        "url": url,
        "authors": authors,
        "year": year,
        "month": month,
        "day": day,
        "date": publication_date,
        "journal": journal,
        "type": publication_type,
        "put_code": str(
            put_code
        ),
    }


# ============================================================
# CLAVES DE DUPLICACIÓN
# ============================================================

def publication_keys(
    publication
):

    keys = []

    doi = clean_doi(
        publication.get(
            "doi",
            "",
        )
    )

    if doi:

        keys.append(
            (
                "doi",
                normalize_text(
                    doi
                ),
            )
        )

    pmid = clean_text(
        publication.get(
            "pmid",
            "",
        )
    )

    if pmid:

        keys.append(
            (
                "pmid",
                normalize_text(
                    pmid
                ),
            )
        )

    pmcid = clean_text(
        publication.get(
            "pmcid",
            "",
        )
    )

    if pmcid:

        keys.append(
            (
                "pmcid",
                normalize_text(
                    pmcid
                ),
            )
        )

    title = normalize_text(
        publication.get(
            "title",
            "",
        )
    )

    if title:

        keys.append(
            (
                "title",
                title,
            )
        )

    return keys


def completeness_score(
    publication
):

    fields = [
        "title",
        "doi",
        "pmid",
        "pmcid",
        "issn",
        "url",
        "journal",
        "year",
        "month",
        "day",
        "type",
    ]

    score = sum(
        1
        for field in fields
        if publication.get(field)
    )

    score += len(
        publication.get(
            "authors",
            [],
        )
    )

    return score


def deduplicate_publications(
    publications
):

    registry = {}

    for publication in publications:

        keys = publication_keys(
            publication
        )

        if not keys:
            continue

        existing = None

        for key in keys:

            if key in registry:

                existing = registry[
                    key
                ]

                break

        if existing is None:

            for key in keys:
                registry[
                    key
                ] = publication

        else:

            old_score = (
                completeness_score(
                    existing
                )
            )

            new_score = (
                completeness_score(
                    publication
                )
            )

            if new_score > old_score:

                for key in keys:

                    registry[
                        key
                    ] = publication

    unique = []

    seen = set()

    for publication in registry.values():

        marker = id(
            publication
        )

        if marker in seen:
            continue

        seen.add(
            marker
        )

        unique.append(
            publication
        )

    return unique


# ============================================================
# BIBTEX
# ============================================================

def make_bibtex_key(
    publication,
    existing_keys,
):

    authors = publication.get(
        "authors",
        [],
    )

    if authors:

        surname = authors[0].split()[-1]

    else:

        surname = (
            publication.get(
                "researcher",
                "Unknown",
            )
            .split()[-1]
        )

    surname = re.sub(
        r"[^A-Za-z0-9]",
        "",
        surname,
    )

    year = publication.get(
        "year",
        "",
    )

    title = normalize_text(
        publication.get(
            "title",
            "",
        )
    )

    words = re.findall(
        r"[a-z0-9]+",
        title,
    )

    title_part = (
        words[0]
        if words
        else "article"
    )

    base = (
        f"{surname}"
        f"{year}"
        f"{title_part}"
    )

    base = re.sub(
        r"[^A-Za-z0-9]",
        "",
        base,
    )

    if not base:
        base = "article"

    key = base
    counter = 2

    while key in existing_keys:

        key = (
            f"{base}"
            f"{counter}"
        )

        counter += 1

    existing_keys.add(
        key
    )

    return key


def publication_to_bibtex(
    publication
):

    key = publication[
        "bibtex_key"
    ]

    authors = publication.get(
        "authors",
        [],
    )

    title = safe_bibtex(
        publication.get(
            "title",
            "",
        )
    )

    journal = safe_bibtex(
        publication.get(
            "journal",
            "",
        )
    )

    year = publication.get(
        "year",
        "",
    )

    doi = clean_doi(
        publication.get(
            "doi",
            "",
        )
    )

    url = publication.get(
        "url",
        "",
    )

    lines = [
        f"@article{{{key},",
    ]

    if authors:

        author_text = (
            " and ".join(
                safe_bibtex(
                    author
                )
                for author in authors
            )
        )

        lines.append(
            f"  author = {{{author_text}}},"
        )

    lines.append(
        f"  title = {{{title}}},"
    )

    if journal:

        lines.append(
            f"  journal = {{{journal}}},"
        )

    if year:

        lines.append(
            f"  year = {{{year}}},"
        )

    if doi:

        lines.append(
            f"  doi = {{{doi}}},"
        )

    if url:

        lines.append(
            f"  url = {{{url}}},"
        )

    lines.append(
        "}"
    )

    return "\n".join(
        lines
    )


# ============================================================
# HTML
# ============================================================

def publications_to_html(
    publications
):

    items = []

    for publication in publications:

        title = html.escape(
            publication.get(
                "title",
                "",
            )
        )

        researcher = html.escape(
            publication.get(
                "researcher",
                "",
            )
        )

        year = html.escape(
            publication.get(
                "year",
                "",
            )
        )

        journal = html.escape(
            publication.get(
                "journal",
                "",
            )
        )

        doi = clean_doi(
            publication.get(
                "doi",
                "",
            )
        )

        url = publication.get(
            "url",
            "",
        )

        item = "<li>"

        item += (
            f"<strong>{title}</strong>"
        )

        if researcher:

            item += (
                f"<br>Investigador: "
                f"{researcher}"
            )

        if year:

            item += (
                f"<br>Año: {year}"
            )

        if journal:

            item += (
                f"<br>Revista: {journal}"
            )

        if doi:

            doi_url = (
                f"https://doi.org/{doi}"
            )

            item += (
                "<br>DOI: "
                f'<a href="{html.escape(doi_url)}">'
                f"{html.escape(doi)}"
                "</a>"
            )

        elif url:

            item += (
                '<br><a href="'
                f'{html.escape(url)}'
                '">Enlace</a>'
            )

        item += "</li>"

        items.append(
            item
        )

    return f"""<!DOCTYPE html>
<html lang="es">

<head>

<meta charset="UTF-8">

<title>Publicaciones ORCID</title>

<style>

body {{
    font-family: Arial, sans-serif;
    margin: 40px;
    line-height: 1.5;
}}

li {{
    margin-bottom: 20px;
}}

</style>

</head>

<body>

<h1>Publicaciones ORCID</h1>

<p>
Total de artículos: {len(publications)}
</p>

<ol>
{"".join(items)}
</ol>

</body>

</html>
"""


# ============================================================
# JSON
# ============================================================

def save_json(
    filename,
    data
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
# INVESTIGADORES
# ============================================================

def load_researchers():

    with open(
        INPUT_FILE,
        "r",
        encoding="utf-8",
    ) as file:

        data = json.load(
            file
        )

    if isinstance(
        data,
        list,
    ):
        return data

    if isinstance(
        data,
        dict,
    ):

        researchers = data.get(
            "researchers"
        )

        if isinstance(
            researchers,
            list,
        ):
            return researchers

    raise ValueError(
        "Formato incorrecto en "
        "researchers1.json."
    )


def get_researcher_orcid(
    researcher
):

    fields = [
        "orcid",
        "ORCID",
        "orcid_id",
        "orcidId",
        "ORCID_ID",
    ]

    for field in fields:

        value = researcher.get(
            field
        )

        if value:
            return clean_text(
                value
            )

    return ""


def get_researcher_name(
    researcher
):

    fields = [
        "name",
        "nombre",
        "researcher",
        "researcher_name",
        "full_name",
        "author",
    ]

    for field in fields:

        value = researcher.get(
            field
        )

        if value:
            return clean_text(
                value
            )

    return "Unknown researcher"


# ============================================================
# MAIN
# ============================================================

def main():

    start_time = time.time()

    researchers = load_researchers()

    all_publications = []
    excluded = []

    total_groups = 0
    total_summaries = 0
    total_full_works = 0
    total_fallbacks = 0
    total_errors = 0

    print()
    print("=" * 70)
    print(
        "ORCID -> BIBTEX"
    )
    print(
        "MODO OPTIMIZADO"
    )
    print("=" * 70)
    print()

    for researcher_index, researcher in enumerate(
        researchers,
        start=1,
    ):

        name = get_researcher_name(
            researcher
        )

        orcid = get_researcher_orcid(
            researcher
        )

        print()
        print(
            "-" * 70
        )

        print(
            f"[{researcher_index}/"
            f"{len(researchers)}] "
            f"{name}"
        )

        if not orcid:

            print(
                "  AVISO: no tiene ORCID."
            )

            continue

        print(
            f"  ORCID: {orcid}"
        )

        # ----------------------------------------------------
        # 1. Obtener todos los grupos
        # ----------------------------------------------------

        try:

            groups = (
                get_orcid_work_groups(
                    orcid
                )
            )

        except Exception as exc:

            print(
                f"  ERROR obteniendo works: "
                f"{exc}"
            )

            total_errors += 1

            continue

        total_groups += len(
            groups
        )

        # ----------------------------------------------------
        # 2. Extraer TODOS los summaries
        # ----------------------------------------------------

        summaries = (
            extract_all_summaries(
                groups
            )
        )

        total_summaries += len(
            summaries
        )

        print(
            f"  Grupos ORCID: "
            f"{len(groups)}"
        )

        print(
            f"  Work summaries: "
            f"{len(summaries)}"
        )

        if not summaries:
            continue

        # ----------------------------------------------------
        # 3. Obtener put-codes
        # ----------------------------------------------------

        put_codes = [
            str(
                summary.get(
                    "put-code"
                )
            )
            for summary in summaries
            if summary.get(
                "put-code"
            )
        ]

        # ----------------------------------------------------
        # 4. RECUPERACIÓN BULK
        #
        # Hasta 100 trabajos por petición.
        # ----------------------------------------------------

        works_by_put_code = (
            get_orcid_works_bulk(
                orcid,
                put_codes,
            )
        )

        total_full_works += len(
            works_by_put_code
        )

        print(
            f"  Works completos: "
            f"{len(works_by_put_code)}"
            f"/{len(put_codes)}"
        )

        # ----------------------------------------------------
        # 5. Convertir TODOS los trabajos
        # ----------------------------------------------------

        for summary in summaries:

            put_code = str(
                summary.get(
                    "put-code"
                )
            )

            # Preferimos el work completo.
            work = (
                works_by_put_code.get(
                    put_code
                )
            )

            # Si el bulk no lo devolvió,
            # usamos el summary como respaldo.
            if work is None:

                work = summary

                total_fallbacks += 1

            publication = (
                work_to_publication(
                    name,
                    orcid,
                    work,
                    put_code,
                )
            )

            if publication is None:

                excluded.append({
                    "researcher": name,
                    "orcid": orcid,
                    "put_code": put_code,
                    "reason": (
                        "No se pudo obtener "
                        "un título válido."
                    ),
                })

                continue

            # ------------------------------------------------
            # GUARDAMOS TODO LO RECUPERADO
            # ------------------------------------------------

            publication[
                "included_as_article"
            ] = looks_like_article(
                publication
            )

            all_publications.append(
                publication
            )

            if not publication[
                "included_as_article"
            ]:

                excluded.append({
                    **publication,
                    "reason": (
                        "Tipo ORCID no "
                        "identificado como "
                        "artículo de revista."
                    ),
                })

        print(
            f"  Inventario acumulado: "
            f"{len(all_publications)}"
        )

    # ========================================================
    # CANDIDATOS
    # ========================================================

    candidate_articles = [
        p
        for p in all_publications
        if p.get(
            "included_as_article"
        )
    ]

    # ========================================================
    # DEDUPLICACIÓN
    # ========================================================

    publications = (
        deduplicate_publications(
            candidate_articles
        )
    )

    # ========================================================
    # BIBTEX KEYS
    # ========================================================

    existing_keys = set()

    for publication in publications:

        publication[
            "bibtex_key"
        ] = make_bibtex_key(
            publication,
            existing_keys,
        )

    # ========================================================
    # ORDEN
    # ========================================================

    def sort_key(
        publication
    ):

        year = publication.get(
            "year",
            "",
        )

        if str(year).isdigit():
            year_value = int(
                year
            )
        else:
            year_value = 0

        return (
            -year_value,
            normalize_text(
                publication.get(
                    "title",
                    "",
                )
            ),
        )

    all_publications.sort(
        key=sort_key
    )

    publications.sort(
        key=sort_key
    )

    # ========================================================
    # GUARDAR JSON PRINCIPAL
    # ========================================================

    save_json(
        OUTPUT_JSON,
        publications
    )

    # ========================================================
    # GUARDAR TODO ORCID
    # ========================================================

    save_json(
        OUTPUT_ALL_JSON,
        all_publications
    )

    # ========================================================
    # GUARDAR EXCLUIDOS
    # ========================================================

    save_json(
        OUTPUT_EXCLUDED_JSON,
        excluded
    )

    # ========================================================
    # HTML
    # ========================================================

    with open(
        OUTPUT_HTML,
        "w",
        encoding="utf-8",
    ) as file:

        file.write(
            publications_to_html(
                publications
            )
        )

    # ========================================================
    # BIBTEX
    # ========================================================

    bib_entries = [
        publication_to_bibtex(
            publication
        )
        for publication in publications
    ]

    with open(
        OUTPUT_BIB,
        "w",
        encoding="utf-8",
    ) as file:

        file.write(
            "\n\n".join(
                bib_entries
            )
        )

        file.write(
            "\n"
        )

    # ========================================================
    # ESTADÍSTICAS
    # ========================================================

    elapsed = (
        time.time()
        - start_time
    )

    print()
    print()
    print("=" * 70)
    print(
        "RESULTADO FINAL"
    )
    print("=" * 70)

    print(
        f"Investigadores: "
        f"{len(researchers)}"
    )

    print(
        f"Grupos ORCID: "
        f"{total_groups}"
    )

    print(
        f"Work summaries: "
        f"{total_summaries}"
    )

    print(
        f"Works completos: "
        f"{total_full_works}"
    )

    print(
        f"Fallbacks a summary: "
        f"{total_fallbacks}"
    )

    print(
        f"Errores: "
        f"{total_errors}"
    )

    print(
        f"Works recuperados: "
        f"{len(all_publications)}"
    )

    print(
        f"Candidatos a artículo: "
        f"{len(candidate_articles)}"
    )

    print(
        f"Artículos después de "
        f"deduplicar: "
        f"{len(publications)}"
    )

    print(
        f"Excluidos: "
        f"{len(excluded)}"
    )

    print()
    print(
        f"TIEMPO TOTAL: "
        f"{elapsed:.1f} segundos"
    )

    print()
    print(
        "Archivos:"
    )

    print(
        f"  {OUTPUT_JSON}"
    )

    print(
        f"  {OUTPUT_ALL_JSON}"
    )

    print(
        f"  {OUTPUT_EXCLUDED_JSON}"
    )

    print(
        f"  {OUTPUT_HTML}"
    )

    print(
        f"  {OUTPUT_BIB}"
    )

    print()
    print(
        "FIN."
    )


# ============================================================
# EJECUTAR
# ============================================================

if __name__ == "__main__":
    main()
