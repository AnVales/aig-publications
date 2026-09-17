import os
import json
import re
import html
import unicodedata
import requests


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
        "No se ha encontrado ORCID_ACCESS_TOKEN en las variables de entorno."
    )


HEADERS = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Accept": "application/vnd.orcid+json",
}


# ORCID permite recuperar trabajos en bloques.
ROWS_PER_PAGE = 100


# ============================================================
# PETICIONES A ORCID
# ============================================================

def orcid_get(url, params=None):
    """
    Realiza una petición GET a ORCID.
    """
    response = requests.get(
        url,
        headers=HEADERS,
        params=params,
        timeout=60,
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# UTILIDADES GENERALES
# ============================================================

def normalize_text(value):
    """
    Normaliza texto para comparaciones.
    """
    if value is None:
        return ""

    value = str(value)

    value = unicodedata.normalize("NFKD", value)
    value = "".join(
        c for c in value
        if not unicodedata.combining(c)
    )

    value = value.lower()

    value = re.sub(r"\s+", " ", value)
    value = value.strip()

    return value


def clean_text(value):
    """
    Limpia un texto conservando caracteres normales.
    """
    if value is None:
        return ""

    return re.sub(r"\s+", " ", str(value)).strip()


def clean_doi(doi):
    """
    Limpia y normaliza un DOI.
    """
    if not doi:
        return ""

    doi = str(doi).strip()

    doi = re.sub(
        r"^(https?://)?(dx\.)?doi\.org/",
        "",
        doi,
        flags=re.IGNORECASE,
    )

    doi = doi.strip()

    doi = doi.rstrip(".,;")

    return doi


def safe_bibtex(value):
    """
    Escapa caracteres problemáticos para BibTeX.
    """
    if value is None:
        return ""

    value = str(value)

    value = value.replace("\\", "\\textbackslash{}")
    value = value.replace("&", r"\&")
    value = value.replace("%", r"\%")
    value = value.replace("#", r"\#")
    value = value.replace("_", r"\_")

    return value


def remove_html_tags(value):
    """
    Elimina etiquetas HTML/XML sencillas.
    """
    if not value:
        return ""

    value = re.sub(r"<[^>]+>", " ", str(value))

    return html.unescape(value)


# ============================================================
# OBTENER WORKS DE ORCID
# ============================================================

def get_orcid_works(orcid):
    """
    Recupera TODOS los grupos de works del ORCID.

    Se hace paginación explícita para evitar quedarse
    únicamente con la primera página.
    """

    all_groups = []

    start = 0

    while True:

        url = f"{ORCID_API}/{orcid}/works"

        params = {
            "start": start,
            "rows": ROWS_PER_PAGE,
        }

        data = orcid_get(url, params=params)

        groups = data.get("group", [])

        if not groups:
            break

        all_groups.extend(groups)

        print(
            f"    ORCID {orcid}: "
            f"página start={start}, "
            f"grupos={len(groups)}"
        )

        # Si hemos recibido menos que el máximo,
        # normalmente ya hemos llegado al final.
        if len(groups) < ROWS_PER_PAGE:
            break

        start += ROWS_PER_PAGE

    return all_groups


def get_orcid_work(orcid, put_code):
    """
    Recupera un work completo mediante su put-code.
    """

    url = f"{ORCID_API}/{orcid}/work/{put_code}"

    try:
        return orcid_get(url)
    except requests.HTTPError as exc:
        print(
            f"      ERROR recuperando work "
            f"{put_code}: {exc}"
        )
        return None


# ============================================================
# EXTERNAL IDS
# ============================================================

def extract_external_ids(work):
    """
    Extrae DOI, PMID, ISSN, etc. desde external-ids.
    """

    result = {}

    external_ids = (
        work.get("external-ids")
        or work.get("external-ids", {}).get("external-id", [])
    )

    if isinstance(external_ids, dict):
        external_ids = external_ids.get(
            "external-id",
            []
        )

    for ext in external_ids:

        ext_type = clean_text(
            ext.get("external-id-type")
        ).lower()

        ext_value = clean_text(
            ext.get("external-id-value")
        )

        if not ext_type or not ext_value:
            continue

        result.setdefault(
            ext_type,
            []
        ).append(ext_value)

    return result


def get_first_external_id(external_ids, names):
    """
    Devuelve el primer identificador encontrado
    entre varios nombres posibles.
    """

    for name in names:

        values = external_ids.get(name, [])

        if values:
            return values[0]

    return ""


# ============================================================
# TÍTULO
# ============================================================

def extract_title(work):
    """
    Extrae el título del trabajo.
    """

    title_obj = work.get("title", {})

    if not title_obj:
        return ""

    title = title_obj.get("title", "")

    if isinstance(title, dict):
        title = title.get("value", "")

    return clean_text(
        remove_html_tags(title)
    )


# ============================================================
# FECHA
# ============================================================

def extract_date(work):
    """
    Extrae la fecha de publicación.
    """

    publication_date = work.get(
        "publication-date",
        {}
    )

    if not publication_date:
        return {
            "year": "",
            "month": "",
            "day": "",
        }

    year = publication_date.get(
        "year",
        {}
    )

    month = publication_date.get(
        "month",
        {}
    )

    day = publication_date.get(
        "day",
        {}
    )

    if isinstance(year, dict):
        year = year.get("value", "")

    if isinstance(month, dict):
        month = month.get("value", "")

    if isinstance(day, dict):
        day = day.get("value", "")

    return {
        "year": str(year or ""),
        "month": str(month or ""),
        "day": str(day or ""),
    }


# ============================================================
# REVISTA
# ============================================================

def extract_journal(work):
    """
    Extrae el nombre de la revista.
    """

    journal = work.get(
        "journal-title"
    )

    if journal:
        return clean_text(journal)

    journal_obj = work.get(
        "journal-title",
        {}
    )

    if isinstance(journal_obj, dict):
        return clean_text(
            journal_obj.get("value", "")
        )

    return ""


# ============================================================
# URL
# ============================================================

def extract_url(work, doi):
    """
    Extrae una URL útil para el trabajo.
    """

    url_obj = work.get("url")

    if isinstance(url_obj, dict):
        url = url_obj.get("value", "")

        if url:
            return clean_text(url)

    if doi:
        return f"https://doi.org/{doi}"

    return ""


# ============================================================
# AUTORES
# ============================================================

def extract_authors(work):
    """
    Extrae los autores desde contributors.
    """

    contributors_obj = work.get(
        "contributors",
        {}
    )

    contributors = contributors_obj.get(
        "contributor",
        []
    )

    if isinstance(contributors, dict):
        contributors = [contributors]

    authors = []

    for contributor in contributors:

        credit_name = (
            contributor
            .get("credit-name", {})
        )

        if isinstance(credit_name, dict):
            name = credit_name.get(
                "value",
                ""
            )
        else:
            name = credit_name

        name = clean_text(name)

        if name:
            authors.append(name)

    return authors


# ============================================================
# TIPO
# ============================================================

def extract_type(work):
    """
    Devuelve el tipo ORCID del trabajo.
    """

    return clean_text(
        work.get("type", "")
    ).lower()


# ============================================================
# DETECTAR SI ES ARTÍCULO
# ============================================================

ARTICLE_TYPES = {
    "journal-article",
}


def looks_like_article(publication):
    """
    Decide si un trabajo debe entrar en la bibliografía
    de artículos.

    Regla principal:
        journal-article

    Regla adicional:
        ORCID lo clasifica como 'other' pero existe
        una revista asociada.

    Esto evita perder algunos artículos que han sido
    cargados en ORCID con una clasificación imperfecta.
    """

    publication_type = (
        publication.get("type", "")
        .lower()
        .strip()
    )

    journal = clean_text(
        publication.get("journal", "")
    )

    if publication_type in ARTICLE_TYPES:
        return True

    if publication_type == "other" and journal:
        return True

    return False


# ============================================================
# CONVERTIR WORK A PUBLICACIÓN
# ============================================================

def work_to_publication(
    researcher,
    orcid,
    work,
    put_code,
):
    """
    Convierte un work completo de ORCID
    a nuestro formato interno.
    """

    if not work:
        return None

    title = extract_title(work)

    if not title:
        return None

    external_ids = extract_external_ids(
        work
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

    date = extract_date(work)

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

    publication = {
        "researcher": researcher,
        "orcid": orcid,
        "title": title,
        "doi": doi,
        "pmid": pmid,
        "pmcid": pmcid,
        "issn": issn,
        "url": url,
        "authors": authors,
        "year": date["year"],
        "month": date["month"],
        "day": date["day"],
        "date": (
            "-".join(
                x
                for x in [
                    date["year"],
                    date["month"],
                    date["day"],
                ]
                if x
            )
        ),
        "journal": journal,
        "type": publication_type,
        "put_code": put_code,
    }

    return publication


# ============================================================
# CLAVES DE DUPLICACIÓN
# ============================================================

def publication_keys(publication):
    """
    Devuelve distintas claves que permiten detectar
    que dos registros son el mismo artículo.
    """

    keys = []

    doi = clean_doi(
        publication.get("doi")
    )

    if doi:
        keys.append(
            ("doi", normalize_text(doi))
        )

    pmid = clean_text(
        publication.get("pmid")
    )

    if pmid:
        keys.append(
            ("pmid", normalize_text(pmid))
        )

    pmcid = clean_text(
        publication.get("pmcid")
    )

    if pmcid:
        keys.append(
            ("pmcid", normalize_text(pmcid))
        )

    title = normalize_text(
        publication.get("title")
    )

    if title:
        keys.append(
            ("title", title)
        )

    return keys


# ============================================================
# DEDUPLICACIÓN
# ============================================================

def deduplicate_publications(
    publications
):
    """
    Elimina duplicados sin perder información.

    Prioridad:
        DOI
        PMID
        PMCID
        título

    Si dos registros representan el mismo artículo,
    conservamos el registro más completo.
    """

    by_key = {}

    for publication in publications:

        keys = publication_keys(
            publication
        )

        if not keys:
            continue

        existing = None

        for key in keys:

            if key in by_key:
                existing = by_key[key]
                break

        if existing is None:

            for key in keys:
                by_key[key] = publication

        else:

            # Conservamos el que tenga más información.
            existing_score = completeness_score(
                existing
            )

            new_score = completeness_score(
                publication
            )

            if new_score > existing_score:

                for key in keys:
                    by_key[key] = publication

    # Recuperar objetos únicos
    unique = []

    seen_ids = set()

    for publication in by_key.values():

        object_id = id(publication)

        if object_id in seen_ids:
            continue

        seen_ids.add(object_id)

        unique.append(publication)

    return unique


def completeness_score(
    publication
):
    """
    Puntúa cuánto detalle tiene un registro.
    """

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

    score = 0

    for field in fields:

        if publication.get(field):
            score += 1

    score += len(
        publication.get(
            "authors",
            []
        )
    )

    return score


# ============================================================
# CLAVE BIBTEX
# ============================================================

def make_bibtex_key(
    publication,
    existing_keys,
):
    """
    Genera una clave BibTeX estable.
    """

    authors = publication.get(
        "authors",
        []
    )

    if authors:

        surname = authors[0].split()[-1]

    else:

        researcher = publication.get(
            "researcher",
            "Unknown"
        )

        surname = researcher.split()[-1]

    surname = re.sub(
        r"[^A-Za-z0-9]",
        "",
        surname
    )

    year = publication.get(
        "year",
        ""
    )

    title = normalize_text(
        publication.get(
            "title",
            ""
        )
    )

    title_words = re.findall(
        r"[a-z0-9]+",
        title
    )

    title_part = (
        title_words[0]
        if title_words
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
        base
    )

    key = base or "article"

    counter = 2

    while key in existing_keys:

        key = f"{base}{counter}"

        counter += 1

    existing_keys.add(key)

    return key


# ============================================================
# BIBTEX
# ============================================================

def publication_to_bibtex(
    publication
):
    """
    Convierte una publicación a BibTeX.
    """

    key = publication["bibtex_key"]

    authors = publication.get(
        "authors",
        []
    )

    title = safe_bibtex(
        publication.get(
            "title",
            ""
        )
    )

    journal = safe_bibtex(
        publication.get(
            "journal",
            ""
        )
    )

    year = publication.get(
        "year",
        ""
    )

    doi = clean_doi(
        publication.get(
            "doi",
            ""
        )
    )

    url = publication.get(
        "url",
        ""
    )

    lines = [
        f"@article{{{key},",
    ]

    if authors:

        author_text = " and ".join(
            safe_bibtex(author)
            for author in authors
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

    lines.append("}")

    return "\n".join(lines)


# ============================================================
# HTML
# ============================================================

def publications_to_html(
    publications
):
    """
    Genera HTML.
    """

    items = []

    for publication in publications:

        title = html.escape(
            publication.get(
                "title",
                ""
            )
        )

        researcher = html.escape(
            publication.get(
                "researcher",
                ""
            )
        )

        year = html.escape(
            publication.get(
                "year",
                ""
            )
        )

        journal = html.escape(
            publication.get(
                "journal",
                ""
            )
        )

        doi = clean_doi(
            publication.get(
                "doi",
                ""
            )
        )

        url = publication.get(
            "url",
            ""
        )

        item = "<li>"

        item += f"<strong>{title}</strong>"

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
                f'<br>DOI: '
                f'<a href="{html.escape(doi_url)}">'
                f'{html.escape(doi)}'
                f"</a>"
            )

        elif url:

            item += (
                f'<br><a href="'
                f'{html.escape(url)}'
                f'">Enlace</a>'
            )

        item += "</li>"

        items.append(item)

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
# GUARDAR JSON
# ============================================================

def save_json(
    filename,
    data
):
    """
    Guarda JSON con UTF-8.
    """

    with open(
        filename,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )


# ============================================================
# LEER INVESTIGADORES
# ============================================================

def load_researchers():
    """
    Carga researchers1.json.

    Admite:
        [...]
    o:
        {"researchers": [...]}
    """

    with open(
        INPUT_FILE,
        "r",
        encoding="utf-8"
    ) as file:

        data = json.load(file)

    if isinstance(data, list):
        return data

    if isinstance(data, dict):

        if isinstance(
            data.get("researchers"),
            list,
        ):
            return data["researchers"]

    raise ValueError(
        "El formato de researchers1.json "
        "no contiene una lista de investigadores."
    )


# ============================================================
# OBTENER ORCID DEL INVESTIGADOR
# ============================================================

def get_researcher_orcid(
    researcher
):
    """
    Busca ORCID en varios nombres de campo
    para hacer el script más tolerante.
    """

    possible_fields = [
        "orcid",
        "ORCID",
        "orcid_id",
        "orcidId",
        "ORCID_ID",
    ]

    for field in possible_fields:

        value = researcher.get(
            field
        )

        if value:
            return clean_text(value)

    return ""


def get_researcher_name(
    researcher
):
    """
    Busca el nombre del investigador.
    """

    possible_fields = [
        "name",
        "nombre",
        "researcher",
        "researcher_name",
        "full_name",
        "author",
    ]

    for field in possible_fields:

        value = researcher.get(
            field
        )

        if value:
            return clean_text(value)

    return "Unknown researcher"


# ============================================================
# MAIN
# ============================================================

def main():

    researchers = load_researchers()

    all_publications = []
    excluded = []

    total_groups = 0
    total_summaries = 0
    total_full_works = 0
    total_errors = 0

    print()
    print("=" * 70)
    print("RECUPERACIÓN DE PUBLICACIONES DESDE ORCID")
    print("=" * 70)
    print()

    for researcher in researchers:

        name = get_researcher_name(
            researcher
        )

        orcid = get_researcher_orcid(
            researcher
        )

        if not orcid:

            print(
                f"[AVISO] {name}: "
                f"no tiene ORCID."
            )

            continue

        print()
        print(
            f"Investigador: {name}"
        )

        print(
            f"ORCID: {orcid}"
        )

        try:

            groups = get_orcid_works(
                orcid
            )

        except Exception as exc:

            print(
                f"  ERROR obteniendo works: "
                f"{exc}"
            )

            total_errors += 1

            continue

        total_groups += len(groups)

        print(
            f"  Grupos ORCID encontrados: "
            f"{len(groups)}"
        )

        # ----------------------------------------------------
        # IMPORTANTE:
        # NO hacemos summaries[0]
        # ----------------------------------------------------

        for group_index, group in enumerate(
            groups,
            start=1
        ):

            summaries = group.get(
                "work-summary",
                []
            )

            if not summaries:
                continue

            total_summaries += len(
                summaries
            )

            print(
                f"    Grupo {group_index}: "
                f"{len(summaries)} "
                f"summary(s)"
            )

            # ------------------------------------------------
            # Procesamos TODOS los summaries
            # ------------------------------------------------

            for summary in summaries:

                put_code = summary.get(
                    "put-code"
                )

                if not put_code:
                    continue

                complete_work = (
                    get_orcid_work(
                        orcid,
                        put_code
                    )
                )

                # --------------------------------------------
                # Si no podemos recuperar el work completo,
                # usamos el summary como respaldo.
                # Así NO perdemos el artículo.
                # --------------------------------------------

                if complete_work is None:

                    complete_work = summary

                    total_errors += 1

                else:

                    total_full_works += 1

                publication = (
                    work_to_publication(
                        name,
                        orcid,
                        complete_work,
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
                            "un título válido"
                        ),
                    })

                    continue

                # --------------------------------------------
                # Guardamos SIEMPRE una copia en el inventario
                # completo de ORCID.
                # --------------------------------------------

                all_publications.append(
                    publication.copy()
                )

                # --------------------------------------------
                # Decidir si entra en publications.json/BIB
                # --------------------------------------------

                if looks_like_article(
                    publication
                ):

                    all_publications[-1][
                        "included_as_article"
                    ] = True

                    # La copia que realmente irá
                    # a la bibliografía.
                    #
                    # Se vuelve a generar más adelante
                    # para poder deduplicar.
                    continue

                else:

                    publication["reason"] = (
                        "Tipo ORCID no considerado "
                        "artículo de revista"
                    )

                    excluded.append(
                        publication
                    )


    # ========================================================
    # DEDUPLICACIÓN DE TODO LO RECUPERADO
    # ========================================================

    print()
    print("=" * 70)
    print("PROCESANDO RESULTADOS")
    print("=" * 70)

    # Nos quedamos con los que tienen marcado
    # included_as_article.
    candidate_articles = [
        p
        for p in all_publications
        if p.get(
            "included_as_article"
        )
    ]

    print(
        f"Works recuperados: "
        f"{len(all_publications)}"
    )

    print(
        f"Candidatos a artículo: "
        f"{len(candidate_articles)}"
    )

    publications = deduplicate_publications(
        candidate_articles
    )

    print(
        f"Artículos después de deduplicar: "
        f"{len(publications)}"
    )

    # ========================================================
    # CLAVES BIBTEX
    # ========================================================

    existing_keys = set()

    for publication in publications:

        publication["bibtex_key"] = (
            make_bibtex_key(
                publication,
                existing_keys
            )
        )

    # ========================================================
    # ORDENAR
    # ========================================================

    publications.sort(
        key=lambda p: (
            -(int(p["year"])
              if str(p.get("year", "")).isdigit()
              else 0),
            normalize_text(
                p.get("title", "")
            ),
        )
    )

    all_publications.sort(
        key=lambda p: (
            -(int(p["year"])
              if str(p.get("year", "")).isdigit()
              else 0),
            normalize_text(
                p.get("title", "")
            ),
        )
    )

    # ========================================================
    # GUARDAR JSON PRINCIPAL
    # ========================================================

    save_json(
        OUTPUT_JSON,
        publications
    )

    # ========================================================
    # GUARDAR TODO LO QUE ORCID DEVOLVIÓ
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

    html_content = publications_to_html(
        publications
    )

    with open(
        OUTPUT_HTML,
        "w",
        encoding="utf-8"
    ) as file:

        file.write(
            html_content
        )

    # ========================================================
    # BIBTEX
    # ========================================================

    bib_entries = []

    for publication in publications:

        bib_entries.append(
            publication_to_bibtex(
                publication
            )
        )

    with open(
        OUTPUT_BIB,
        "w",
        encoding="utf-8"
    ) as file:

        file.write(
            "\n\n".join(
                bib_entries
            )
        )

        file.write("\n")

    # ========================================================
    # RESUMEN FINAL
    # ========================================================

    print()
    print("=" * 70)
    print("RESULTADO FINAL")
    print("=" * 70)

    print(
        f"Investigadores procesados: "
        f"{len(researchers)}"
    )

    print(
        f"Grupos ORCID encontrados: "
        f"{total_groups}"
    )

    print(
        f"Work summaries encontrados: "
        f"{total_summaries}"
    )

    print(
        f"Works completos recuperados: "
        f"{total_full_works}"
    )

    print(
        f"Errores de recuperación: "
        f"{total_errors}"
    )

    print(
        f"Works recuperados en total: "
        f"{len(all_publications)}"
    )

    print(
        f"Artículos candidatos: "
        f"{len(candidate_articles)}"
    )

    print(
        f"Artículos finales en BIB: "
        f"{len(publications)}"
    )

    print()
    print("Archivos generados:")

    print(
        f"  - {OUTPUT_JSON}"
    )

    print(
        f"  - {OUTPUT_ALL_JSON}"
    )

    print(
        f"  - {OUTPUT_EXCLUDED_JSON}"
    )

    print(
        f"  - {OUTPUT_HTML}"
    )

    print(
        f"  - {OUTPUT_BIB}"
    )

    print()
    print("Proceso terminado.")


# ============================================================
# EJECUCIÓN
# ============================================================

if __name__ == "__main__":
    main()
