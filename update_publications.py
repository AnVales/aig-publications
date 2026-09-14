import json
import urllib.parse
import urllib.request
import re
import html
import unicodedata


OPENALEX = "https://api.openalex.org/works"

EXTERNAL_ICON = (
    "https://aig.webs.tsc.uc3m.es/"
    "wp-content/plugins/papercite/img/external.png"
)

INPUT_FILE = "researchers.json"
JSON_OUTPUT = "publications.json"
HTML_OUTPUT = "publications.html"


# ============================================================
# OPENALEX
# ============================================================

def get_works(orcid):
    """Obtiene artículos de OpenAlex para un ORCID."""

    orcid = str(orcid).strip()

    filter_value = urllib.parse.quote(
        f"author.orcid:{orcid}",
        safe=""
    )

    url = (
        f"{OPENALEX}"
        f"?filter={filter_value},type:article"
        f"&per_page=100"
        f"&mailto=publications@uc3m.es"
    )

    try:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "AIG-Publications/1.0"
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=60
        ) as response:
            data = json.load(response)

        return data.get("results", [])

    except Exception as exc:
        print(
            f"ERROR OpenAlex {orcid}: {exc}"
        )
        return []


# ============================================================
# TEXTO
# ============================================================

def normalize_dashes(text):
    """Convierte diferentes guiones Unicode en '-'."""

    if not text:
        return ""

    return (
        str(text)
        .replace("‐", "-")
        .replace("-", "-")
        .replace("‒", "-")
        .replace("–", "-")
        .replace("—", "-")
        .replace("−", "-")
    )


def normalize_spaces(text):
    """Normaliza espacios."""

    if not text:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(text)
    ).strip()


def normalize_text(text):
    """Normaliza texto general."""

    return normalize_spaces(
        normalize_dashes(text)
    )


# ============================================================
# DOI
# ============================================================

def normalize_doi(doi):
    """Devuelve solamente el DOI."""

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
        r"^https?://dx\.doi\.org/",
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

    return doi.rstrip(
        " .,;)"
    )


def is_repository_doi(doi):
    """Detecta DOI de repositorios/preprints."""

    if not doi:
        return False

    doi = doi.lower()

    patterns = [
        "10.5281/zenodo.",
        "10.48550/arxiv.",
        "10.31219/osf.io/",
        "10.20944/preprints",
        "10.21203/rs.3.rs-",
    ]

    return any(
        pattern in doi
        for pattern in patterns
    )


# ============================================================
# TÍTULOS
# ============================================================

def normalize_title(title):
    """Normaliza títulos para detectar duplicados."""

    title = normalize_text(title)

    title = title.lower()

    title = re.sub(
        r"[^\w\s]",
        "",
        title,
        flags=re.UNICODE
    )

    return title


# ============================================================
# REVISTAS
# ============================================================

JOURNAL_FIXES = {
    "Earth s Future": "Earth’s Future",
    "Earth s future": "Earth’s Future",
}


def normalize_journal(journal):
    """Normaliza el nombre de la revista."""

    journal = normalize_text(journal)

    if journal in JOURNAL_FIXES:
        return JOURNAL_FIXES[journal]

    return journal


# ============================================================
# AUTORES
# ============================================================

def normalize_author_name(name):
    """Normaliza el nombre de un autor."""

    return normalize_text(name)


def format_author_for_html(name):
    """
    Formato abreviado para HTML.

    Ejemplos:

    Miguel-Ángel Fernández-Torres
    -> M.-Á. Fernández-Torres

    Gustau Camps-Valls
    -> G. Camps-Valls

    Claudia Montero-Ramírez
    -> C. Montero-Ramírez
    """

    name = normalize_author_name(name)

    if not name:
        return ""

    parts = name.split()

    if len(parts) == 1:
        return parts[0]

    surname = parts[-1]
    given_names = parts[:-1]

    initials = []

    for given in given_names:

        if "-" in given:

            subparts = [
                p for p in given.split("-")
                if p
            ]

            if len(subparts) == 2:
                initials.append(
                    f"{subparts[0][0].upper()}.-"
                    f"{subparts[1][0].upper()}."
                )
            else:
                initials.append(
                    given[0].upper() + "."
                )

        else:

            clean = re.sub(
                r"[^\wÀ-ÿ]",
                "",
                given,
                flags=re.UNICODE
            )

            if clean:
                initials.append(
                    clean[0].upper() + "."
                )

    return (
        " ".join(initials)
        + " "
        + surname
    ).strip()


def format_authors(authors):
    """Formatea autores para la referencia HTML."""

    formatted = []

    for author in authors:

        value = format_author_for_html(
            author
        )

        if value:
            formatted.append(value)

    if not formatted:
        return ""

    if len(formatted) == 1:
        return formatted[0]

    if len(formatted) == 2:
        return (
            f"{formatted[0]} and "
            f"{formatted[1]}"
        )

    return (
        ", ".join(formatted[:-1])
        + ", and "
        + formatted[-1]
    )


# ============================================================
# PÁGINAS
# ============================================================

def normalize_pages(first_page, last_page):
    """Normaliza páginas y números de artículo."""

    first_page = str(
        first_page or ""
    ).strip()

    last_page = str(
        last_page or ""
    ).strip()

    if not first_page:
        return ""

    if not last_page:
        return first_page

    if first_page == last_page:
        return first_page

    return (
        f"{first_page}-{last_page}"
    )


# ============================================================
# BIBTEX
# ============================================================

def escape_bibtex(value):
    """Escapa caracteres especiales de BibTeX."""

    if not value:
        return ""

    value = str(value)

    value = value.replace(
        "\\",
        r"\textbackslash "
    )

    value = value.replace(
        "%",
        r"\%"
    )

    value = value.replace(
        "_",
        r"\_"
    )

    value = value.replace(
        "&",
        r"\&"
    )

    return value


def make_bibtex_key(work):
    """Genera una clave BibTeX."""

    authorships = work.get(
        "authorships",
        []
    )

    surname = "unknown"

    if authorships:

        name = (
            authorships[0]
            .get("author", {})
            .get("display_name", "")
        )

        if name:
            surname = name.split()[-1]

    # Eliminar tildes.
    surname = unicodedata.normalize(
        "NFKD",
        surname
    )

    surname = surname.encode(
        "ascii",
        "ignore"
    ).decode("ascii")

    surname = re.sub(
        r"[^A-Za-z0-9]",
        "",
        surname
    ).lower()

    year = (
        work.get("publication_year")
        or "nd"
    )

    return f"{surname}{year}"


def make_bibtex(work):
    """Genera BibTeX completo."""

    title = normalize_text(
        work.get("title", "")
    )

    year = work.get(
        "publication_year"
    )

    doi = normalize_doi(
        work.get("doi", "")
    )

    authors = []

    for authorship in work.get(
        "authorships",
        []
    ):

        author = authorship.get(
            "author",
            {}
        )

        name = author.get(
            "display_name",
            ""
        )

        if name:
            authors.append(
                normalize_author_name(name)
            )

    location = (
        work.get("primary_location")
        or {}
    )

    source = (
        location.get("source")
        or {}
    )

    journal = normalize_journal(
        source.get(
            "display_name",
            ""
        )
    )

    biblio = (
        work.get("biblio")
        or {}
    )

    volume = biblio.get(
        "volume"
    ) or ""

    issue = biblio.get(
        "issue"
    ) or ""

    pages = normalize_pages(
        biblio.get("first_page"),
        biblio.get("last_page")
    )

    fields = []

    if title:
        fields.append(
            "  title = "
            f"{{{escape_bibtex(title)}}}"
        )

    if authors:
        fields.append(
            "  author = {"
            + " and ".join(
                escape_bibtex(author)
                for author in authors
            )
            + "}"
        )

    if journal:
        fields.append(
            "  journal = "
            f"{{{escape_bibtex(journal)}}}"
        )

    if volume:
        fields.append(
            "  volume = "
            f"{{{escape_bibtex(volume)}}}"
        )

    if issue:
        fields.append(
            "  number = "
            f"{{{escape_bibtex(issue)}}}"
        )

    if pages:

        bib_pages = pages.replace(
            "-",
            "--"
        )

        fields.append(
            "  pages = "
            f"{{{escape_bibtex(bib_pages)}}}"
        )

    if year:
        fields.append(
            f"  year = {{{year}}}"
        )

    if doi:
        fields.append(
            "  doi = "
            f"{{{escape_bibtex(doi)}}}"
        )

    key = make_bibtex_key(
        work
    )

    return (
        f"@article{{{key},\n"
        + ",\n".join(fields)
        + "\n}"
    )


# ============================================================
# CONVERSIÓN OPENALEX -> PUBLICACIÓN
# ============================================================

def work_to_publication(work):
    """Convierte un registro OpenAlex."""

    title = normalize_text(
        work.get("title", "")
    )

    year = work.get(
        "publication_year"
    )

    doi = normalize_doi(
        work.get("doi", "")
    )

    location = (
        work.get("primary_location")
        or {}
    )

    source = (
        location.get("source")
        or {}
    )

    journal = normalize_journal(
        source.get(
            "display_name",
            ""
        )
    )

    authors = []

    for authorship in work.get(
        "authorships",
        []
    ):

        author = authorship.get(
            "author",
            {}
        )

        name = author.get(
            "display_name",
            ""
        )

        if name:
            authors.append(
                normalize_author_name(name)
            )

    biblio = (
        work.get("biblio")
        or {}
    )

    volume = biblio.get(
        "volume"
    ) or ""

    issue = biblio.get(
        "issue"
    ) or ""

    pages = normalize_pages(
        biblio.get("first_page"),
        biblio.get("last_page")
    )

    # IMPORTANTE:
    # OpenAlex devuelve una URL normal.
    # No añadimos Markdown.
    openalex_id = work.get(
        "id",
        ""
    )

    return {
        "title": title,
        "year": year,
        "doi": doi,
        "authors": authors,
        "journal": journal,
        "volume": volume,
        "issue": issue,
        "pages": pages,
        "bibtex": make_bibtex(work),
        "openalex_id": openalex_id,
    }


# ============================================================
# INVESTIGADORES
# ============================================================

def load_researchers():
    """Carga researchers.json."""

    with open(
        INPUT_FILE,
        "r",
        encoding="utf-8"
    ) as file:

        data = json.load(file)

    if isinstance(data, dict):

        if "researchers" in data:
            return data["researchers"]

        return [
            {
                "name": name,
                "orcid": orcid
            }
            for name, orcid in data.items()
        ]

    return data


# ============================================================
# OBTENER PUBLICACIONES
# ============================================================

def collect_publications():

    researchers = load_researchers()

    publications = []

    for researcher in researchers:

        if isinstance(
            researcher,
            str
        ):
            name = researcher
            orcid = researcher

        else:

            name = (
                researcher.get("name")
                or researcher.get(
                    "display_name"
                )
                or ""
            )

            orcid = researcher.get(
                "orcid",
                ""
            )

        if not orcid:
            print(
                f"AVISO: {name} "
                f"no tiene ORCID"
            )
            continue

        print(
            f"Consultando: {name} "
            f"({orcid})"
        )

        works = get_works(
            orcid
        )

        print(
            f"  {len(works)} registros"
        )

        for work in works:

            # Solo artículos.
            if work.get("type") != "article":
                continue

            doi = normalize_doi(
                work.get("doi", "")
            )

            # Eliminar repositorios/preprints.
            if is_repository_doi(doi):

                print(
                    f"  OMITIDO repositorio: "
                    f"{doi}"
                )

                continue

            title = work.get(
                "title",
                ""
            )

            if not title:
                continue

            publication = (
                work_to_publication(
                    work
                )
            )

            if not publication["year"]:
                continue

            publications.append(
                publication
            )

    return publications


# ============================================================
# DUPLICADOS
# ============================================================

def deduplicate(publications):

    unique = {}

    for publication in publications:

        doi = normalize_doi(
            publication.get(
                "doi",
                ""
            )
        )

        title = normalize_title(
            publication.get(
                "title",
                ""
            )
        )

        if doi:
            key = (
                "doi:"
                + doi.lower()
            )

        else:
            key = (
                "title:"
                + title
            )

        if key not in unique:
            unique[key] = publication

    return list(
        unique.values()
    )


# ============================================================
# BIBTEX: CLAVES ÚNICAS
# ============================================================

def make_unique_bibtex_keys(
    publications
):

    used = {}

    for publication in publications:

        bibtex = publication.get(
            "bibtex",
            ""
        )

        match = re.match(
            r"@article\{([^,]+),",
            bibtex
        )

        if not match:
            continue

        base = match.group(1)

        count = used.get(
            base,
            0
        )

        if count == 0:
            key = base

        else:
            key = (
                f"{base}"
                f"{chr(96 + count + 1)}"
            )

        used[base] = count + 1

        publication["bibtex"] = (
            re.sub(
                r"^@article\{[^,]+,",
                f"@article{{{key},",
                bibtex,
                count=1
            )
        )


# ============================================================
# HTML
# ============================================================

def make_doi_html(doi):

    if not doi:
        return ""

    safe_doi = html.escape(
        doi,
        quote=True
    )

    return (
        f'<a href="http://dx.doi.org/'
        f'{safe_doi}" '
        f'title="View document on publisher site" '
        f'target="_blank">[DOI]</a> '
        f'(<img src="{EXTERNAL_ICON}" '
        f'alt="external link" '
        f'style="width:12px;height:12px;">)'
    )


def make_publication_html(
    publication,
    index
):

    title = html.escape(
        publication.get(
            "title",
            ""
        )
    )

    authors = format_authors(
        publication.get(
            "authors",
            []
        )
    )

    authors = html.escape(
        authors
    )

    journal = publication.get(
        "journal",
        ""
    )

    journal = html.escape(
        journal.upper()
    )

    year = publication.get(
        "year",
        ""
    )

    volume = publication.get(
        "volume",
        ""
    )

    issue = publication.get(
        "issue",
        ""
    )

    pages = publication.get(
        "pages",
        ""
    )

    doi = normalize_doi(
        publication.get(
            "doi",
            ""
        )
    )

    doi_html = make_doi_html(
        doi
    )

    metadata = ""

    if journal:
        metadata += (
            f"<em>{journal}</em>"
        )

    if volume:
        metadata += (
            f", vol. "
            f"{html.escape(str(volume))}"
        )

    if issue:
        metadata += (
            f", iss. "
            f"{html.escape(str(issue))}"
        )

    if pages:
        metadata += (
            f", pp. "
            f"{html.escape(str(pages))}"
        )

    if year:
        metadata += (
            f", {html.escape(str(year))}"
        )

    metadata += "."

    bibtex = html.escape(
        publication.get(
            "bibtex",
            ""
        )
    )

    bib_id = (
        f"bibtex-{index}"
    )

    return (
        "<p>"
        f"{doi_html} "
        f"{authors}, "
        f"“{title},” "
        f"{metadata}"
        "<br>"
        f'<a href="#" '
        f'onclick="var e=document.getElementById('
        f"'{bib_id}'"
        f');e.style.display=('
        f"e.style.display==='none' "
        f"? 'block' : 'none');"
        f"return false;"
        f'">[Bibtex]</a>'
        f'<pre id="{bib_id}" '
        f'style="display:none; '
        f'white-space:pre-wrap;">'
        f"{bibtex}"
        "</pre>"
        "</p>"
    )


def generate_html(
    publications
):

    output = [
        '<div class="publications">'
    ]

    current_year = None

    for index, publication in enumerate(
        publications
    ):

        year = publication.get(
            "year"
        )

        if year != current_year:

            if current_year is not None:
                output.append("")

            output.append(
                f"<h3>{html.escape(str(year))}</h3>"
            )

            current_year = year

        output.append(
            make_publication_html(
                publication,
                index
            )
        )

    output.append(
        "</div>"
    )

    return "\n".join(
        output
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "========================================"
    )

    print(
        "AIG Publications updater"
    )

    print(
        "========================================"
    )

    publications = (
        collect_publications()
    )

    print(
        f"\nObtenidas: "
        f"{len(publications)}"
    )

    publications = deduplicate(
        publications
    )

    print(
        f"Después de duplicados: "
        f"{len(publications)}"
    )

    make_unique_bibtex_keys(
        publications
    )

    publications.sort(
        key=lambda item: (
            -(item.get("year") or 0),
            item.get(
                "title",
                ""
            ).lower()
        )
    )

    # --------------------------------------------------------
    # JSON
    # --------------------------------------------------------

    with open(
        JSON_OUTPUT,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            publications,
            file,
            ensure_ascii=False,
            indent=2
        )

    print(
        f"Generado: {JSON_OUTPUT}"
    )

    # --------------------------------------------------------
    # HTML
    # --------------------------------------------------------

    html_content = (
        generate_html(
            publications
        )
    )

    with open(
        HTML_OUTPUT,
        "w",
        encoding="utf-8"
    ) as file:

        file.write(
            html_content
        )

    print(
        f"Generado: {HTML_OUTPUT}"
    )

    print(
        "========================================"
    )

    print(
        "FIN OK"
    )

    print(
        "========================================"
    )


if __name__ == "__main__":
    main()
