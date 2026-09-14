import json
import urllib.parse
import urllib.request
import re
import html
import unicodedata


# ============================================================
# CONFIGURACIÓN
# ============================================================

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
    """Busca artículos de un investigador en OpenAlex."""

    orcid = orcid.strip()

    # OpenAlex acepta el ORCID directamente en el filtro.
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
                "User-Agent": "aig-publications/1.0"
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
            f"ERROR consultando OpenAlex para "
            f"{orcid}: {exc}"
        )
        return []


# ============================================================
# NORMALIZACIÓN
# ============================================================

def normalize_dashes(text):
    """Normaliza diferentes tipos de guiones."""

    if not text:
        return ""

    return (
        text
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
        text
    ).strip()


def normalize_title(title):
    """Normaliza un título para detectar duplicados."""

    if not title:
        return ""

    title = normalize_dashes(title)
    title = normalize_spaces(title)
    title = title.lower()

    title = re.sub(
        r"[^\w\s]",
        "",
        title,
        flags=re.UNICODE
    )

    return title.strip()


def normalize_doi(doi):
    """Limpia y normaliza un DOI."""

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
        " .;,)"
    )


def is_repository_doi(doi):
    """
    Identifica DOI de repositorios/preprints que no deben
    aparecer como publicación editorial.
    """

    if not doi:
        return False

    doi_lower = doi.lower()

    repository_patterns = [
        "10.5281/zenodo.",
        "10.48550/arxiv.",
        "10.31219/osf.io/",
        "10.20944/preprints",
        "10.21203/rs.3.rs-",
    ]

    return any(
        pattern in doi_lower
        for pattern in repository_patterns
    )


# ============================================================
# REVISTAS
# ============================================================

JOURNAL_FIXES = {
    "Earth s Future": "Earth’s Future",
    "Earth s future": "Earth’s Future",
}


def normalize_journal(journal):
    """Normaliza el nombre de la revista."""

    if not journal:
        return ""

    journal = normalize_spaces(journal)
    journal = normalize_dashes(journal)

    if journal in JOURNAL_FIXES:
        return JOURNAL_FIXES[journal]

    return journal


# ============================================================
# AUTORES
# ============================================================

def normalize_author_name(name):
    """Normaliza un nombre de autor."""

    if not name:
        return ""

    name = normalize_spaces(name)
    name = normalize_dashes(name)

    return name


def format_author(name):
    """
    Convierte un nombre completo en formato bibliográfico.

    Ejemplo:

        Fernando Díaz de María

    ->

        F. D. d. María
    """

    name = normalize_author_name(name)

    if not name:
        return ""

    parts = name.split()

    if len(parts) == 1:
        return parts[0]

    # Partículas habituales que forman parte del apellido.
    particles = {
        "de",
        "del",
        "de la",
        "da",
        "do",
        "dos",
        "di",
        "van",
        "von",
        "der",
        "den",
    }

    # En nombres de OpenAlex, la forma más segura para el
    # listado tipo Papercite es utilizar iniciales para los
    # nombres y conservar el último elemento como apellido.
    surname = parts[-1]

    given_parts = parts[:-1]

    initials = []

    for part in given_parts:
        clean = re.sub(
            r"[^\wÀ-ÿ]",
            "",
            part,
            flags=re.UNICODE
        )

        if not clean:
            continue

        initials.append(
            clean[0].upper() + "."
        )

    if initials:
        return (
            " ".join(initials)
            + " "
            + surname
        )

    return surname


def format_authors(authors):
    """Devuelve autores en formato tipo Papercite."""

    formatted = []

    for author in authors:
        formatted_author = format_author(
            author
        )

        if formatted_author:
            formatted.append(
                formatted_author
            )

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
    """
    Convierte:

        1919 + 1919 -> 1919
        112 + 114 -> 112-114
        76 + 96 -> 76-96
    """

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

    return f"{first_page}-{last_page}"


# ============================================================
# BIBTEX
# ============================================================

def escape_bibtex(value):
    """Escapa caracteres problemáticos para BibTeX."""

    if not value:
        return ""

    value = str(value)

    value = value.replace(
        "\\",
        r"\textbackslash "
    )

    value = value.replace(
        "{",
        r"\{"
    )

    value = value.replace(
        "}",
        r"\}"
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


def bibtex_key(work):
    """Genera una clave BibTeX básica."""

    authorships = work.get(
        "authorships",
        []
    )

    first_author = "unknown"

    if authorships:
        author = (
            authorships[0]
            .get("author", {})
            .get("display_name", "")
        )

        if author:
            first_author = (
                author
                .split()[-1]
            )

    first_author = unicodedata.normalize(
        "NFKD",
        first_author
    )

    first_author = (
        first_author
        .encode(
            "ascii",
            "ignore"
        )
        .decode("ascii")
    )

    first_author = re.sub(
        r"[^A-Za-z0-9]",
        "",
        first_author
    ).lower()

    year = (
        work.get("publication_year")
        or "nd"
    )

    return f"{first_author}{year}"


def make_bibtex(work):
    """Genera una entrada BibTeX."""

    title = normalize_spaces(
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
            "display_name"
        )

        if name:
            authors.append(
                normalize_author_name(
                    name
                )
            )

    primary_location = (
        work.get("primary_location")
        or {}
    )

    source = (
        primary_location.get("source")
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
            f"  title = {{{escape_bibtex(title)}}}"
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
            f"  journal = {{{escape_bibtex(journal)}}}"
        )

    if volume:
        fields.append(
            f"  volume = {{{escape_bibtex(volume)}}}"
        )

    if issue:
        fields.append(
            f"  number = {{{escape_bibtex(issue)}}}"
        )

    if pages:
        fields.append(
            f"  pages = {{{escape_bibtex(pages.replace('-', '--'))}}}"
        )

    if year:
        fields.append(
            f"  year = {{{year}}}"
        )

    if doi:
        fields.append(
            f"  doi = {{{escape_bibtex(doi)}}}"
        )

    key = bibtex_key(work)

    return (
        f"@article{{{key},\n"
        + ",\n".join(fields)
        + "\n}"
    )


# ============================================================
# PROCESAMIENTO
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


def work_to_publication(work):
    """Convierte un registro OpenAlex a nuestra estructura."""

    title = normalize_spaces(
        work.get("title", "")
    )

    year = work.get(
        "publication_year"
    )

    doi = normalize_doi(
        work.get("doi", "")
    )

    primary_location = (
        work.get("primary_location")
        or {}
    )

    source = (
        primary_location.get("source")
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
            "display_name"
        )

        if name:
            authors.append(
                normalize_author_name(
                    name
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


def process_publications():
    """Obtiene todas las publicaciones."""

    researchers = load_researchers()

    publications = []

    for researcher in researchers:

        if isinstance(
            researcher,
            str
        ):
            researcher_name = researcher
            orcid = researcher

        else:
            researcher_name = (
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
                f"AVISO: {researcher_name} "
                f"no tiene ORCID."
            )
            continue

        print(
            f"Consultando OpenAlex: "
            f"{researcher_name} ({orcid})"
        )

        works = get_works(orcid)

        print(
            f"  -> {len(works)} registros"
        )

        for work in works:

            title = work.get(
                "title",
                ""
            )

            if not title:
                continue

            # Solo artículos.
            if work.get("type") != "article":
                continue

            # Ignorar repositorios/preprints.
            doi = normalize_doi(
                work.get("doi", "")
            )

            if is_repository_doi(doi):
                print(
                    f"  -> Ignorado repositorio: "
                    f"{doi}"
                )
                continue

            publication = work_to_publication(
                work
            )

            if not publication["year"]:
                continue

            publications.append(
                publication
            )

    return publications


# ============================================================
# DEDUPLICACIÓN
# ============================================================

def deduplicate_publications(
    publications
):
    """
    Elimina duplicados.

    Prioridad:
      1. DOI
      2. título normalizado
    """

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

        if not key:
            continue

        if key not in unique:
            unique[key] = publication

    return list(
        unique.values()
    )


# ============================================================
# CLAVES BIBTEX ÚNICAS
# ============================================================

def make_unique_bibtex_keys(
    publications
):
    """
    Evita claves BibTeX repetidas.

    Ejemplo:

        campsvalls2025
        campsvalls2025a
        campsvalls2025b
    """

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

        base_key = match.group(1)

        count = used.get(
            base_key,
            0
        )

        if count == 0:
            new_key = base_key
        else:
            new_key = (
                f"{base_key}"
                f"{chr(96 + count + 1)}"
            )

        used[base_key] = count + 1

        publication["bibtex"] = (
            bibtex.replace(
                f"@article{{{base_key},",
                f"@article{{{new_key},",
                1
            )
        )


# ============================================================
# HTML
# ============================================================

def make_doi_html(doi):
    """Genera el enlace DOI."""

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
    """Genera HTML para una publicación."""

    title = html.escape(
        publication.get(
            "title",
            ""
        )
    )

    journal = html.escape(
        publication.get(
            "journal",
            ""
        ).upper()
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
            f", "
            f"{html.escape(str(year))}"
        )

    # Si no hay páginas, no añadimos pp.
    if metadata.endswith("."):
        citation_metadata = metadata
    else:
        citation_metadata = (
            metadata + "."
        )

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
        f"{citation_metadata}"
        "<br>"
        f'<a href="#" '
        f'onclick="var e=document.getElementById(\'{bib_id}\');'
        f'e.style.display=(e.style.display===\'none\' '
        f'? \'block\' : \'none\');'
        f'return false;">[Bibtex]</a>'
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
    """Genera publications.html agrupado por año."""

    output = []

    output.append(
        '<div class="publications">'
    )

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
                f"<h3>"
                f"{html.escape(str(year))}"
                f"</h3>"
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
        "Actualización de publicaciones"
    )

    print(
        "========================================"
    )

    publications = (
        process_publications()
    )

    print(
        f"\nPublicaciones obtenidas: "
        f"{len(publications)}"
    )

    publications = (
        deduplicate_publications(
            publications
        )
    )

    print(
        f"Después de eliminar duplicados: "
        f"{len(publications)}"
    )

    # Claves BibTeX únicas.
    make_unique_bibtex_keys(
        publications
    )

    # Orden:
    # año descendente
    # título ascendente
    publications.sort(
        key=lambda p: (
            -(p.get("year") or 0),
            p.get(
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
        f"JSON generado: "
        f"{JSON_OUTPUT}"
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
        f"HTML generado: "
        f"{HTML_OUTPUT}"
    )

    print(
        "========================================"
    )

    print(
        "Proceso terminado correctamente"
    )

    print(
        "========================================"
    )


if __name__ == "__main__":
    main()
