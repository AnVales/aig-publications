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
OUTPUT_ALL = "publications_all_orcid.json"
OUTPUT_EXCLUDED = "publications_excluded.json"
OUTPUT_HTML = "publications.html"
OUTPUT_BIB = "publications.bib"

API_BASE = "https://pub.orcid.org/v3.0"

TOKEN = os.getenv("ORCID_ACCESS_TOKEN")

if not TOKEN:
    raise RuntimeError(
        "No existe la variable de entorno ORCID_ACCESS_TOKEN."
    )

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.orcid+json",
}

ROWS_PER_PAGE = 100

# Límite de seguridad para evitar bucles infinitos.
MAX_PAGES = 1000

# Tiempo máximo por petición.
REQUEST_TIMEOUT = 30


# ============================================================
# SESIÓN HTTP
# ============================================================

session = requests.Session()

retry = Retry(
    total=3,
    connect=3,
    read=3,
    backoff_factor=1,
    status_forcelist=[
        429,
        500,
        502,
        503,
        504,
    ],
    allowed_methods=["GET"],
)

adapter = HTTPAdapter(
    max_retries=retry,
    pool_connections=10,
    pool_maxsize=10,
)

session.mount(
    "https://",
    adapter
)


# ============================================================
# PETICIONES ORCID
# ============================================================

def orcid_get(url, params=None):

    response = session.get(
        url,
        headers=HEADERS,
        params=params,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# NORMALIZACIÓN
# ============================================================

def normalize_text(value):

    if not value:
        return ""

    value = str(value)

    value = unicodedata.normalize(
        "NFKD",
        value
    )

    value = (
        value
        .encode(
            "ascii",
            "ignore"
        )
        .decode("ascii")
    )

    value = value.lower()

    value = re.sub(
        r"\s+",
        " ",
        value
    )

    return value.strip()


def clean_doi(value):

    if not value:
        return ""

    value = str(value).strip()

    value = re.sub(
        r"^https?://doi\.org/",
        "",
        value,
        flags=re.I,
    )

    value = re.sub(
        r"^doi:\s*",
        "",
        value,
        flags=re.I,
    )

    return value.strip().rstrip(".")


# ============================================================
# OBTENER GRUPOS DE WORKS
# ============================================================

def get_orcid_work_groups(orcid):

    url = f"{API_BASE}/{orcid}/works"

    all_groups = []

    start = 0
    total = None
    page_number = 0

    seen_put_codes = set()

    while True:

        page_number += 1

        if page_number > MAX_PAGES:

            print(
                f"      SEGURIDAD: alcanzado "
                f"MAX_PAGES={MAX_PAGES}."
            )

            break

        params = {
            "start": start,
            "rows": ROWS_PER_PAGE,
        }

        data = orcid_get(
            url,
            params=params
        )

        groups = data.get(
            "group",
            []
        )

        # ----------------------------------------------------
        # TOTAL DECLARADO POR ORCID
        # ----------------------------------------------------

        if total is None:

            total = data.get(
                "num-found"
            )

            try:

                if total is not None:
                    total = int(total)

            except (
                TypeError,
                ValueError,
            ):

                total = None

        print(
            f"      Página ORCID "
            f"{start}-{start + ROWS_PER_PAGE} "
            f"| grupos: {len(groups)}"
            + (
                f" | total declarado: {total}"
                if total is not None
                else ""
            )
        )

        # ----------------------------------------------------
        # NO HAY MÁS RESULTADOS
        # ----------------------------------------------------

        if not groups:
            break

        # ----------------------------------------------------
        # DETECTAR REPETICIONES
        # ----------------------------------------------------

        page_put_codes = []

        for group in groups:

            summaries = group.get(
                "work-summary",
                []
            )

            for summary in summaries:

                put_code = summary.get(
                    "put-code"
                )

                if put_code is not None:

                    page_put_codes.append(
                        str(put_code)
                    )

        # Si todos los put-codes de esta página
        # ya habían aparecido, estamos ante una repetición.

        new_put_codes = [
            pc
            for pc in page_put_codes
            if pc not in seen_put_codes
        ]

        if page_put_codes and not new_put_codes:

            print(
                "      AVISO: ORCID ha devuelto "
                "una página repetida. "
                "Se detiene la paginación."
            )

            break

        for put_code in new_put_codes:

            seen_put_codes.add(
                put_code
            )

        all_groups.extend(
            groups
        )

        # ----------------------------------------------------
        # FINAL SEGÚN TOTAL
        # ----------------------------------------------------

        if total is not None:

            if start + len(groups) >= total:
                break

        # ----------------------------------------------------
        # MENOS RESULTADOS DE LOS SOLICITADOS
        # ----------------------------------------------------

        if len(groups) < ROWS_PER_PAGE:
            break

        # ----------------------------------------------------
        # SIGUIENTE PÁGINA
        # ----------------------------------------------------

        start += len(groups)

    return all_groups


# ============================================================
# EXTRAER TODOS LOS WORK SUMMARY
# ============================================================

def extract_all_summaries(groups):

    summaries = []

    seen_put_codes = set()

    for group in groups:

        for summary in group.get(
            "work-summary",
            []
        ):

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


# ============================================================
# OBTENER WORK COMPLETO
# ============================================================

def get_orcid_work(
    orcid,
    put_code
):

    url = (
        f"{API_BASE}/{orcid}/work/{put_code}"
    )

    return orcid_get(url)


# ============================================================
# TÍTULO
# ============================================================

def get_title(work):

    title_obj = work.get(
        "title"
    )

    if not isinstance(
        title_obj,
        dict
    ):
        return ""

    title = title_obj.get(
        "title"
    )

    if not isinstance(
        title,
        dict
    ):
        return ""

    value = title.get(
        "value"
    )

    return (
        str(value).strip()
        if value
        else ""
    )


# ============================================================
# REVISTA
# ============================================================

def get_journal(work):

    journal_obj = work.get(
        "journal-title"
    )

    if not isinstance(
        journal_obj,
        dict
    ):
        return ""

    value = journal_obj.get(
        "value"
    )

    return (
        str(value).strip()
        if value
        else ""
    )


# ============================================================
# IDENTIFICADORES EXTERNOS
# ============================================================

def get_external_ids(work):

    result = {}

    external_ids_obj = work.get(
        "external-ids"
    )

    if not isinstance(
        external_ids_obj,
        dict
    ):
        return result

    external_ids = external_ids_obj.get(
        "external-id",
        []
    )

    if not isinstance(
        external_ids,
        list
    ):
        return result

    for item in external_ids:

        if not isinstance(
            item,
            dict
        ):
            continue

        id_type = (
            item.get(
                "external-id-type"
            )
            or ""
        ).lower().strip()

        value = (
            item.get(
                "external-id-value"
            )
            or ""
        ).strip()

        if not value:
            continue

        result[id_type] = value

    return result


# ============================================================
# DOI
# ============================================================

def get_doi(work):

    ids = get_external_ids(
        work
    )

    value = (
        ids.get("doi")
        or ids.get("DOI")
        or ""
    )

    return clean_doi(
        value
    )


# ============================================================
# FECHA
# ============================================================

def get_date(work):

    date_obj = work.get(
        "publication-date"
    )

    if not isinstance(
        date_obj,
        dict
    ):
        return ""

    year_obj = date_obj.get(
        "year"
    )

    month_obj = date_obj.get(
        "month"
    )

    day_obj = date_obj.get(
        "day"
    )

    year = (
        year_obj.get("value")
        if isinstance(
            year_obj,
            dict
        )
        else None
    )

    month = (
        month_obj.get("value")
        if isinstance(
            month_obj,
            dict
        )
        else None
    )

    day = (
        day_obj.get("value")
        if isinstance(
            day_obj,
            dict
        )
        else None
    )

    if year and month and day:

        return (
            f"{year}-{month}-{day}"
        )

    if year and month:

        return (
            f"{year}-{month}"
        )

    if year:

        return str(year)

    return ""


# ============================================================
# AÑO
# ============================================================

def get_year(work):

    date_obj = work.get(
        "publication-date"
    )

    if not isinstance(
        date_obj,
        dict
    ):
        return ""

    year_obj = date_obj.get(
        "year"
    )

    if not isinstance(
        year_obj,
        dict
    ):
        return ""

    year = year_obj.get(
        "value"
    )

    if not year:
        return ""

    return str(
        year
    )


# ============================================================
# URL
# ============================================================

def get_url(work):

    url_obj = work.get(
        "url"
    )

    if not isinstance(
        url_obj,
        dict
    ):
        return ""

    value = url_obj.get(
        "value"
    )

    return (
        str(value).strip()
        if value
        else ""
    )


# ============================================================
# AUTORES
# ============================================================

def get_authors(work):

    authors = []

    contributors_obj = work.get(
        "contributors"
    )

    if not isinstance(
        contributors_obj,
        dict
    ):
        return authors

    contributors = contributors_obj.get(
        "contributor",
        []
    )

    if not isinstance(
        contributors,
        list
    ):
        return authors

    for contributor in contributors:

        if not isinstance(
            contributor,
            dict
        ):
            continue

        credit_name = contributor.get(
            "credit-name"
        )

        if not isinstance(
            credit_name,
            dict
        ):
            continue

        value = credit_name.get(
            "value"
        )

        if value:

            authors.append(
                str(value).strip()
            )

    return authors


# ============================================================
# CONVERTIR WORK A PUBLICACIÓN
# ============================================================

def work_to_publication(
    work,
    researcher,
    orcid,
    put_code=None
):

    if not isinstance(
        work,
        dict
    ):
        return None

    title = get_title(
        work
    )

    if not title:
        return None

    work_type = (
        work.get(
            "type"
        )
        or ""
    )

    work_type = str(
        work_type
    ).lower().strip()

    journal = get_journal(
        work
    )

    publication = {

        "researcher": researcher,

        "orcid": orcid,

        "title": title,

        "doi": get_doi(
            work
        ),

        "url": get_url(
            work
        ),

        "authors": get_authors(
            work
        ),

        "year": get_year(
            work
        ),

        "date": get_date(
            work
        ),

        "journal": journal,

        "type": work_type,

        "put_code": put_code,
    }

    return publication


# ============================================================
# DETERMINAR SI ES ARTÍCULO
# ============================================================

def looks_like_article(
    publication
):

    work_type = (
        publication.get(
            "type",
            ""
        )
        .lower()
        .strip()
    )

    journal = (
        publication.get(
            "journal",
            ""
        )
        .strip()
    )

    # ORCID lo identifica explícitamente
    # como artículo de revista.
    if work_type == "journal-article":
        return True

    # Algunos registros pueden venir como "other"
    # pero contener una revista.
    if work_type == "other" and journal:
        return True

    return False


# ============================================================
# DEDUPLICACIÓN
# ============================================================

def deduplicate_publications(
    publications
):

    result = []

    seen_doi = set()
    seen_title = set()

    for pub in publications:

        doi = clean_doi(
            pub.get(
                "doi",
                ""
            )
        )

        title = normalize_text(
            pub.get(
                "title",
                ""
            )
        )

        if not title:
            continue

        # ----------------------------------------------------
        # DEDUPLICAR POR DOI
        # ----------------------------------------------------

        if doi:

            doi_key = doi.lower()

            if doi_key in seen_doi:
                continue

            seen_doi.add(
                doi_key
            )

        # ----------------------------------------------------
        # DEDUPLICAR POR TÍTULO
        # ----------------------------------------------------

        if title in seen_title:
            continue

        seen_title.add(
            title
        )

        result.append(
            pub
        )

    return result


# ============================================================
# ESCAPE BIBTEX
# ============================================================

def bibtex_escape(
    value
):

    if not value:
        return ""

    value = str(
        value
    )

    value = value.replace(
        "\\",
        "\\textbackslash{}"
    )

    return value


# ============================================================
# CLAVE BIBTEX
# ============================================================

def make_bib_key(
    pub,
    index
):

    authors = pub.get(
        "authors",
        []
    )

    if authors:

        first_author = (
            authors[0]
        )

        surname = (
            first_author
            .split()[-1]
        )

    else:

        researcher = (
            pub.get(
                "researcher",
                "author"
            )
        )

        surname = (
            researcher
            .split()[0]
            if researcher
            else "author"
        )

    surname = re.sub(
        r"[^A-Za-z0-9]",
        "",
        surname
    )

    year = (
        pub.get(
            "year"
        )
        or "nd"
    )

    return (
        f"{surname}"
        f"{year}"
        f"_{index}"
    )


# ============================================================
# GENERAR BIBTEX
# ============================================================

def make_bibtex(
    publications
):

    entries = []

    for index, pub in enumerate(
        publications,
        start=1
    ):

        key = make_bib_key(
            pub,
            index
        )

        title = bibtex_escape(
            pub.get(
                "title",
                ""
            )
        )

        journal = bibtex_escape(
            pub.get(
                "journal",
                ""
            )
        )

        year = (
            pub.get(
                "year"
            )
            or ""
        )

        doi = (
            pub.get(
                "doi"
            )
            or ""
        )

        url = (
            pub.get(
                "url"
            )
            or ""
        )

        authors = pub.get(
            "authors",
            []
        )

        if authors:

            author_text = (
                " and ".join(
                    bibtex_escape(
                        author
                    )
                    for author in authors
                )
            )

        else:

            author_text = ""

        lines = [
            f"@article{{{key},",
            f"  title = {{{title}}},",
        ]

        if author_text:

            lines.append(
                f"  author = "
                f"{{{author_text}}},"
            )

        if journal:

            lines.append(
                f"  journal = "
                f"{{{journal}}},"
            )

        if year:

            lines.append(
                f"  year = "
                f"{{{year}}},"
            )

        if doi:

            lines.append(
                f"  doi = "
                f"{{{doi}}},"
            )

        if url:

            lines.append(
                f"  url = "
                f"{{{url}}},"
            )

        lines.append(
            "}"
        )

        entries.append(
            "\n".join(
                lines
            )
        )

    return "\n\n".join(
        entries
    )


# ============================================================
# GENERAR HTML
# ============================================================

def make_html(
    publications
):

    items = []

    for pub in publications:

        title = html.escape(
            pub.get(
                "title",
                ""
            )
        )

        researcher = html.escape(
            pub.get(
                "researcher",
                ""
            )
        )

        year = html.escape(
            pub.get(
                "year",
                ""
            )
        )

        journal = html.escape(
            pub.get(
                "journal",
                ""
            )
        )

        doi = pub.get(
            "doi",
            ""
        )

        url = pub.get(
            "url",
            ""
        )

        block = f"""
        <li>
            <strong>{title}</strong><br>
            Investigador: {researcher}<br>
            Año: {year}<br>
            Revista: {journal}<br>
        """

        if doi:

            safe_doi = html.escape(
                doi,
                quote=True
            )

            block += (
                "DOI: "
                f'<a href="https://doi.org/'
                f'{safe_doi}" '
                f'target="_blank">'
                f'{safe_doi}'
                "</a><br>"
            )

        if url:

            safe_url = html.escape(
                url,
                quote=True
            )

            block += (
                f'<a href="{safe_url}" '
                f'target="_blank">'
                "Enlace"
                "</a>"
            )

        block += "</li>"

        items.append(
            block
        )

    return f"""<!DOCTYPE html>
<html lang="es">

<head>

<meta charset="UTF-8">

<title>Publicaciones</title>

<style>

body {{
    font-family: Arial, sans-serif;
    margin: 40px;
}}

li {{
    margin-bottom: 25px;
}}

</style>

</head>

<body>

<h1>Publicaciones</h1>

<ol>

{''.join(items)}

</ol>

</body>

</html>
"""


# ============================================================
# MAIN
# ============================================================

def main():

    start_time = time.time()

    # --------------------------------------------------------
    # CARGAR INVESTIGADORES
    # --------------------------------------------------------

    with open(
        INPUT_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        researchers = json.load(
            f
        )

    # --------------------------------------------------------
    # VARIABLES
    # --------------------------------------------------------

    all_publications = []

    excluded = []

    total_groups = 0
    total_summaries = 0
    total_full = 0
    total_errors = 0

    # ========================================================
    # CABECERA
    # ========================================================

    print()

    print(
        "=" * 70
    )

    print(
        " ORCID → BIBTEX"
    )

    print(
        "=" * 70
    )

    print()

    # ========================================================
    # INVESTIGADORES
    # ========================================================

    for researcher_index, researcher_data in enumerate(
        researchers,
        start=1
    ):

        researcher = (
            researcher_data.get(
                "name"
            )
            or researcher_data.get(
                "researcher"
            )
            or ""
        )

        orcid = (
            researcher_data.get(
                "orcid"
            )
            or ""
        ).strip()

        print(
            f"[{researcher_index}/"
            f"{len(researchers)}] "
            f"{researcher}"
        )

        # ----------------------------------------------------
        # SIN ORCID
        # ----------------------------------------------------

        if not orcid:

            print(
                "      AVISO: investigador "
                "sin ORCID."
            )

            continue

        print(
            f"      ORCID: {orcid}"
        )

        # ====================================================
        # 1. OBTENER GRUPOS
        # ====================================================

        try:

            groups = (
                get_orcid_work_groups(
                    orcid
                )
            )

        except Exception as e:

            total_errors += 1

            print(
                f"      ERROR obteniendo obras: "
                f"{e}"
            )

            continue

        total_groups += len(
            groups
        )

        print(
            f"      Grupos obtenidos: "
            f"{len(groups)}"
        )

        # ====================================================
        # 2. OBTENER SUMMARIES
        # ====================================================

        summaries = (
            extract_all_summaries(
                groups
            )
        )

        total_summaries += len(
            summaries
        )

        print(
            f"      Work summaries: "
            f"{len(summaries)}"
        )

        # ====================================================
        # 3. OBTENER WORKS COMPLETOS
        # ====================================================

        full_works = []

        for i, summary in enumerate(
            summaries,
            start=1
        ):

            put_code = summary.get(
                "put-code"
            )

            # Mostrar progreso cada 25
            # y también el primero/último.

            if (
                i == 1
                or i % 25 == 0
                or i == len(summaries)
            ):

                print(
                    f"      Obras: "
                    f"{i}/{len(summaries)}"
                )

            try:

                work = get_orcid_work(
                    orcid,
                    put_code
                )

                full_works.append(
                    (
                        work,
                        put_code
                    )
                )

                total_full += 1

            except Exception as e:

                total_errors += 1

                print(
                    f"      AVISO: fallo en "
                    f"put-code {put_code}: "
                    f"{e}"
                )

                # ------------------------------------------------
                # MUY IMPORTANTE:
                # NO perdemos el registro.
                # Usamos el summary.
                # ------------------------------------------------

                full_works.append(
                    (
                        summary,
                        put_code
                    )
                )

        print(
            f"      Obras recuperadas: "
            f"{len(full_works)}"
        )

        # ====================================================
        # 4. CONVERTIR CADA WORK
        # ====================================================

        for work, put_code in full_works:

            try:

                publication = (
                    work_to_publication(
                        work,
                        researcher,
                        orcid,
                        put_code
                    )
                )

            except Exception as e:

                total_errors += 1

                print(
                    f"      AVISO: no se pudo "
                    f"procesar put-code "
                    f"{put_code}: {e}"
                )

                continue

            if publication is None:
                continue

            all_publications.append(
                publication
            )

    # ========================================================
    # GUARDAR TODO LO RECUPERADO
    # ========================================================

    with open(
        OUTPUT_ALL,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            all_publications,
            f,
            ensure_ascii=False,
            indent=2
        )

    # ========================================================
    # FILTRAR ARTÍCULOS
    # ========================================================

    article_candidates = []

    for publication in all_publications:

        if looks_like_article(
            publication
        ):

            article_candidates.append(
                publication
            )

        else:

            excluded.append(
                publication
            )

    # ========================================================
    # DEDUPLICAR
    # ========================================================

    publications = (
        deduplicate_publications(
            article_candidates
        )
    )

    # ========================================================
    # JSON PRINCIPAL
    # ========================================================

    with open(
        OUTPUT_JSON,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            publications,
            f,
            ensure_ascii=False,
            indent=2
        )

    # ========================================================
    # EXCLUIDOS
    # ========================================================

    with open(
        OUTPUT_EXCLUDED,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            excluded,
            f,
            ensure_ascii=False,
            indent=2
        )

    # ========================================================
    # BIBTEX
    # ========================================================

    bibtex = make_bibtex(
        publications
    )

    with open(
        OUTPUT_BIB,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            bibtex
        )

    # ========================================================
    # HTML
    # ========================================================

    html_content = make_html(
        publications
    )

    with open(
        OUTPUT_HTML,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            html_content
        )

    # ========================================================
    # ESTADÍSTICAS
    # ========================================================

    elapsed = (
        time.time()
        - start_time
    )

    print()

    print(
        "=" * 70
    )

    print(
        " RESULTADO"
    )

    print(
        "=" * 70
    )

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
        f"Works recuperados: "
        f"{total_full}"
    )

    print(
        f"Total trabajos guardados: "
        f"{len(all_publications)}"
    )

    print(
        f"Candidatos a artículo: "
        f"{len(article_candidates)}"
    )

    print(
        f"Artículos después de deduplicar: "
        f"{len(publications)}"
    )

    print(
        f"Excluidos: "
        f"{len(excluded)}"
    )

    print(
        f"Errores/avisos: "
        f"{total_errors}"
    )

    print(
        f"TIEMPO TOTAL: "
        f"{elapsed:.1f} segundos"
    )

    print()

    print(
        "Archivos generados:"
    )

    print(
        f"  - {OUTPUT_JSON}"
    )

    print(
        f"  - {OUTPUT_ALL}"
    )

    print(
        f"  - {OUTPUT_EXCLUDED}"
    )

    print(
        f"  - {OUTPUT_HTML}"
    )

    print(
        f"  - {OUTPUT_BIB}"
    )

    print()

    print(
        "FIN"
    )


# ============================================================
# EJECUTAR
# ============================================================

if __name__ == "__main__":
    main()
