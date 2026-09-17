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

# IMPORTANTE:
# 100 es el máximo que queremos pedir por página.
ROWS_PER_PAGE = 100

# Seguridad absoluta para evitar otro bucle infinito.
MAX_PAGES = 1000

# Tiempo máximo de espera por petición.
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
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"],
)

adapter = HTTPAdapter(
    max_retries=retry,
    pool_connections=10,
    pool_maxsize=10,
)

session.mount("https://", adapter)


# ============================================================
# PETICIÓN ORCID
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
    ).encode(
        "ascii",
        "ignore"
    ).decode(
        "ascii"
    )

    value = value.lower()

    value = re.sub(
        r"\s+",
        " ",
        value
    ).strip()

    return value


def clean_doi(value):
    if not value:
        return ""

    value = str(value).strip()

    value = re.sub(
        r"^https?://doi\.org/",
        "",
        value,
        flags=re.I
    )

    value = re.sub(
        r"^doi:\s*",
        "",
        value,
        flags=re.I
    )

    return value.strip().rstrip(".")


# ============================================================
# PAGINACIÓN SEGURA DE ORCID
# ============================================================

def get_orcid_work_groups(orcid):

    url = f"{API_BASE}/{orcid}/works"

    all_groups = []

    start = 0
    total = None
    page_number = 0

    seen_signatures = set()

    while True:

        page_number += 1

        if page_number > MAX_PAGES:
            print(
                f"      SEGURIDAD: se alcanzó MAX_PAGES={MAX_PAGES}. "
                f"Se detiene la paginación."
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

        # ORCID normalmente devuelve:
        # num-found
        # pero no vamos a depender exclusivamente de ello.
        if total is None:
            total = data.get("num-found")

            if total is not None:
                try:
                    total = int(total)
                except Exception:
                    total = None

        print(
            f"      Página ORCID {start}-{start + ROWS_PER_PAGE} "
            f"| grupos: {len(groups)}"
            + (
                f" | total declarado: {total}"
                if total is not None
                else ""
            )
        )

        if not groups:
            break

        # ----------------------------------------------------
        # DETECCIÓN DE PÁGINAS REPETIDAS
        # ----------------------------------------------------

        signature_parts = []

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
                    signature_parts.append(
                        str(put_code)
                    )

        signature = "|".join(
            signature_parts
        )

        if signature in seen_signatures:
            print(
                "      AVISO: ORCID ha devuelto una página "
                "repetida. Se detiene la paginación."
            )
            break

        seen_signatures.add(signature)

        all_groups.extend(groups)

        # ----------------------------------------------------
        # CONDICIONES DE FINALIZACIÓN
        # ----------------------------------------------------

        if total is not None:

            if start + len(groups) >= total:
                break

        # Si ORCID devuelve menos de lo solicitado,
        # normalmente hemos llegado al final.
        if len(groups) < ROWS_PER_PAGE:
            break

        # Avanzar exactamente el número real recibido.
        start += len(groups)

    return all_groups


# ============================================================
# EXTRAER TODOS LOS SUMMARY
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
# RECUPERAR UNA OBRA COMPLETA
# ============================================================

def get_orcid_work(orcid, put_code):

    url = (
        f"{API_BASE}/{orcid}/work/{put_code}"
    )

    return orcid_get(url)


# ============================================================
# TEXTO
# ============================================================

def get_title(work):

    title_obj = work.get(
        "title",
        {}
    )

    return (
        title_obj.get(
            "title",
            {}
        ).get(
            "value"
        )
        or ""
    )


def get_journal(work):

    journal_title = (
        work
        .get("journal-title", {})
        .get("value")
    )

    if journal_title:
        return journal_title.strip()

    return ""


# ============================================================
# DOI / IDENTIFICADORES
# ============================================================

def get_external_ids(work):

    result = {}

    external_ids = (
        work
        .get("external-ids", {})
        .get("external-id", [])
    )

    for item in external_ids:

        id_type = (
            item.get("external-id-type")
            or ""
        ).lower()

        value = (
            item.get("external-id-value")
            or ""
        ).strip()

        if not value:
            continue

        result[id_type] = value

    return result


def get_doi(work):

    ids = get_external_ids(work)

    for key in (
        "doi",
        "DOI",
    ):

        if key in ids:
            return clean_doi(
                ids[key]
            )

    return ""


# ============================================================
# FECHA
# ============================================================

def get_date(work):

    date_obj = work.get(
        "publication-date"
    )

    if not date_obj:
        return ""

    year = (
        date_obj
        .get("year", {})
        .get("value")
    )

    month = (
        date_obj
        .get("month", {})
        .get("value")
    )

    day = (
        date_obj
        .get("day", {})
        .get("value")
    )

    if year and month and day:
        return f"{year}-{month}-{day}"

    if year and month:
        return f"{year}-{month}"

    if year:
        return str(year)

    return ""


def get_year(work):

    date_obj = work.get(
        "publication-date"
    )

    if not date_obj:
        return ""

    year = (
        date_obj
        .get("year", {})
        .get("value")
    )

    return str(year) if year else ""


# ============================================================
# URL
# ============================================================

def get_url(work):

    url_obj = work.get(
        "url"
    )

    if isinstance(
        url_obj,
        dict
    ):
        return (
            url_obj
            .get("value")
            or ""
        )

    return ""


# ============================================================
# AUTORES
# ============================================================

def get_authors(work):

    authors = []

    contributors = (
        work
        .get("contributors", {})
        .get("contributor", [])
    )

    for contributor in contributors:

        credit_name = (
            contributor
            .get("credit-name", {})
            .get("value")
        )

        if credit_name:
            authors.append(
                credit_name.strip()
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

    title = get_title(work)

    if not title:
        return None

    work_type = (
        work.get("type")
        or ""
    ).lower()

    journal = get_journal(
        work
    )

    publication = {
        "researcher": researcher,
        "orcid": orcid,
        "title": title,
        "doi": get_doi(work),
        "url": get_url(work),
        "authors": get_authors(work),
        "year": get_year(work),
        "date": get_date(work),
        "journal": journal,
        "type": work_type,
        "put_code": put_code,
    }

    return publication


# ============================================================
# ¿ES ARTÍCULO?
# ============================================================

def looks_like_article(publication):

    work_type = (
        publication
        .get("type", "")
        .lower()
        .strip()
    )

    journal = (
        publication
        .get("journal", "")
        .strip()
    )

    # Artículo explícitamente declarado por ORCID
    if work_type == "journal-article":
        return True

    # Algunos artículos aparecen con otro tipo
    # pero tienen revista.
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

    seen = set()

    for pub in publications:

        doi = clean_doi(
            pub.get("doi", "")
        )

        title_key = normalize_text(
            pub.get("title", "")
        )

        if doi:
            key = f"doi:{doi.lower()}"

        else:
            key = f"title:{title_key}"

        if not title_key:
            continue

        if key in seen:
            continue

        seen.add(key)

        result.append(
            pub
        )

    return result


# ============================================================
# BIBTEX
# ============================================================

def bibtex_escape(value):

    if not value:
        return ""

    value = str(value)

    value = value.replace(
        "\\",
        "\\textbackslash{}"
    )

    value = value.replace(
        "{",
        "\\{"
    )

    value = value.replace(
        "}",
        "\\}"
    )

    return value


def make_bib_key(pub, index):

    authors = pub.get(
        "authors",
        []
    )

    if authors:

        surname = (
            authors[0]
            .split()[-1]
        )

    else:

        surname = (
            pub
            .get("researcher", "author")
            .split()[0]
        )

    year = (
        pub.get("year")
        or "nd"
    )

    surname = re.sub(
        r"[^A-Za-z0-9]",
        "",
        surname
    )

    return (
        f"{surname}"
        f"{year}"
        f"_{index}"
    )


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
            pub.get("title", "")
        )

        journal = bibtex_escape(
            pub.get("journal", "")
        )

        year = (
            pub.get("year")
            or ""
        )

        doi = (
            pub.get("doi")
            or ""
        )

        url = (
            pub.get("url")
            or ""
        )

        authors = pub.get(
            "authors",
            []
        )

        if authors:

            author_text = " and ".join(
                bibtex_escape(a)
                for a in authors
            )

        else:

            author_text = ""

        lines = [
            f"@article{{{key},",
            f"  title = {{{title}}},",
        ]

        if author_text:
            lines.append(
                f"  author = {{{author_text}}},"
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

        lines.append("}")

        entries.append(
            "\n".join(lines)
        )

    return "\n\n".join(
        entries
    )


# ============================================================
# HTML
# ============================================================

def make_html(
    publications
):

    items = []

    for pub in publications:

        title = html.escape(
            pub.get("title", "")
        )

        researcher = html.escape(
            pub.get("researcher", "")
        )

        year = html.escape(
            pub.get("year", "")
        )

        journal = html.escape(
            pub.get("journal", "")
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
                f'DOI: '
                f'<a href="https://doi.org/{safe_doi}" '
                f'target="_blank">'
                f'{safe_doi}'
                f'</a><br>'
            )

        if url:
            safe_url = html.escape(
                url,
                quote=True
            )

            block += (
                f'<a href="{safe_url}" '
                f'target="_blank">'
                f'Enlace'
                f'</a>'
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

    with open(
        INPUT_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        researchers = json.load(f)

    all_publications = []

    excluded = []

    total_groups = 0
    total_summaries = 0
    total_full = 0
    total_errors = 0

    print()
    print("=" * 70)
    print(" ORCID → BIBTEX")
    print("=" * 70)
    print()

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

        if not orcid:
            print(
                f"[{researcher_index}/{len(researchers)}] "
                f"{researcher}: SIN ORCID"
            )
            continue

        print(
            f"[{researcher_index}/{len(researchers)}] "
            f"{researcher}"
        )

        print(
            f"      ORCID: {orcid}"
        )

        # ----------------------------------------------------
        # 1. OBTENER GRUPOS
        # ----------------------------------------------------

        try:

            groups = get_orcid_work_groups(
                orcid
            )

        except Exception as e:

            total_errors += 1

            print(
                f"      ERROR obteniendo obras: {e}"
            )

            continue

        total_groups += len(groups)

        print(
            f"      Grupos obtenidos: "
            f"{len(groups)}"
        )

        # ----------------------------------------------------
        # 2. OBTENER TODOS LOS SUMMARIES
        # ----------------------------------------------------

        summaries = extract_all_summaries(
            groups
        )

        total_summaries += len(
            summaries
        )

        print(
            f"      Work summaries: "
            f"{len(summaries)}"
        )

        # ----------------------------------------------------
        # 3. OBTENER OBRAS COMPLETAS
        # ----------------------------------------------------

        full_works = []

        for i, summary in enumerate(
            summaries,
            start=1
        ):

            put_code = summary.get(
                "put-code"
            )

            if i == 1 or i % 25 == 0 or i == len(summaries):

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

                # Aunque falle la obra completa,
                # NO la perdemos.
                # Usamos el summary disponible.

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

        # ----------------------------------------------------
        # 4. CONVERTIR A PUBLICACIONES
        # ----------------------------------------------------

        for work, put_code in full_works:

            publication = work_to_publication(
                work,
                researcher,
                orcid,
                put_code
            )

            if publication is None:
                continue

            all_publications.append(
                publication
            )

    # ========================================================
    # GUARDAR TODO LO QUE ORCID DEVOLVIÓ
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

    excluded = []

    for pub in all_publications:

        if looks_like_article(pub):

            article_candidates.append(
                pub
            )

        else:

            excluded.append(
                pub
            )

    # ========================================================
    # DEDUPLICAR
    # ========================================================

    publications = deduplicate_publications(
        article_candidates
    )

    # ========================================================
    # GUARDAR JSON PRINCIPAL
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
    # GUARDAR EXCLUIDOS
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
    print("=" * 70)
    print(" RESULTADO")
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
        f"Works recuperados: "
        f"{total_full}"
    )

    print(
        f"Total de trabajos guardados: "
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
        f"Errores: "
        f"{total_errors}"
    )

    print(
        f"TIEMPO TOTAL: "
        f"{elapsed:.1f} segundos"
    )

    print()
    print("Archivos generados:")

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
    print("FIN")


# ============================================================
# EJECUTAR
# ============================================================

if __name__ == "__main__":
    main()
