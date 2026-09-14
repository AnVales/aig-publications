import json
import urllib.parse
import urllib.request
import re
import html


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

    # OpenAlex permite utilizar el ORCID directamente en el filtro.
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

        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.load(response)

        return data.get("results", [])

    except Exception as exc:
        print(f"ERROR consultando OpenAlex para {orcid}: {exc}")
        return []


# ============================================================
# UTILIDADES
# ============================================================

def normalize_title(title):
    """Normaliza un título para detectar duplicados."""

    if not title:
        return ""

    title = title.lower()
    title = re.sub(r"\s+", " ", title)
    title = re.sub(r"[^\w\s]", "", title)

    return title.strip()


def normalize_doi(doi):
    """Limpia y normaliza un DOI."""

    if not doi:
        return ""

    doi = doi.strip()

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

    return doi.rstrip(" .;,)")


def is_repository_doi(doi):
    """
    Devuelve True para DOI que no deberían utilizarse como
    enlace principal de publicación.
    """

    if not doi:
        return False

    doi_lower = doi.lower()

    repository_domains = [
        "zenodo.",
        "hal.science",
        "arxiv.org",
        "doi.org/10.48550",
    ]

    return any(
        domain in doi_lower
        for domain in repository_domains
    )


# ============================================================
# AUTORES
# ============================================================

def format_author(name):
    """
    Convierte:

        Fernando Díaz de María

    en:

        F. D. d. M.

    manteniendo el apellido final completo cuando resulta
    identificable.
    """

    if not name:
        return ""

    name = re.sub(r"\s+", " ", name.strip())

    parts = name.split()

    if len(parts) == 1:
        return parts[0]

    surname = parts[-1]
    given_names = parts[:-1]

    initials = []

    for part in given_names:
        # Eliminamos puntuación residual.
        clean = re.sub(r"[^\wÀ-ÿ'-]", "", part)

        if not clean:
            continue

        initials.append(clean[0].upper() + ".")

    if initials:
        return " ".join(initials) + f" {surname}"

    return surname


def format_authors(authorships):
    """Devuelve los autores en formato bibliográfico."""

    authors = []

    for authorship in authorships:
        author = authorship.get("author", {})

        name = author.get("display_name", "")

        if not name:
            continue

        authors.append(format_author(name))

    if not authors:
        return ""

    if len(authors) == 1:
        return authors[0]

    if len(authors) == 2:
        return f"{authors[0]} and {authors[1]}"

    return ", ".join(authors[:-1]) + ", and " + authors[-1]


# ============================================================
# BIBTEX
# ============================================================

def escape_bibtex(value):
    """Escapa caracteres problemáticos para BibTeX."""

    if not value:
        return ""

    value = str(value)

    value = value.replace("\\", r"\textbackslash ")
    value = value.replace("{", r"\{")
    value = value.replace("}", r"\}")
    value = value.replace("%", r"\%")
    value = value.replace("_", r"\_")
    value = value.replace("&", r"\&")

    return value


def make_bibtex(work):
    """Genera una entrada BibTeX a partir de un registro OpenAlex."""

    title = work.get("title", "").strip()

    publication_year = work.get("publication_year")

    doi = normalize_doi(work.get("doi", ""))

    authors = []

    for authorship in work.get("authorships", []):
        author = authorship.get("author", {})
        name = author.get("display_name")

        if name:
            authors.append(name)

    journal = ""

    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}

    journal = source.get("display_name", "") or ""

    biblio = work.get("biblio") or {}

    volume = biblio.get("volume") or ""
    issue = biblio.get("issue") or ""
    first_page = biblio.get("first_page") or ""
    last_page = biblio.get("last_page") or ""

    pages = ""

    if first_page and last_page:
        pages = f"{first_page}--{last_page}"
    elif first_page:
        pages = first_page

    # Crear una clave BibTeX razonablemente estable.
    first_author = "unknown"

    if authors:
        first_author = re.sub(
            r"[^A-Za-z0-9]",
            "",
            authors[0].split()[-1]
        ).lower()

    year = publication_year or "nd"

    key = f"{first_author}{year}"

    fields = [
        f"  title = {{{escape_bibtex(title)}}}",
    ]

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
            f"  pages = {{{escape_bibtex(pages)}}}"
        )

    if publication_year:
        fields.append(
            f"  year = {{{publication_year}}}"
        )

    if doi:
        fields.append(
            f"  doi = {{{escape_bibtex(doi)}}}"
        )

    return (
        f"@article{{{key},\n"
        + ",\n".join(fields)
        + "\n}"
    )


# ============================================================
# PROCESAR PUBLICACIONES
# ============================================================

def load_researchers():
    """Carga researchers.json."""

    with open(INPUT_FILE, "r", encoding="utf-8") as file:
        data = json.load(file)

    if isinstance(data, dict):
        # Permite tanto:
        #
        # {"researchers": [...]}
        #
        # como:
        #
        # {"Fernando": "0000-..."}
        researchers = data.get("researchers")

        if researchers is not None:
            return researchers

        return [
            {
                "name": name,
                "orcid": orcid
            }
            for name, orcid in data.items()
        ]

    return data


def process_publications():
    """Obtiene y procesa todas las publicaciones."""

    researchers = load_researchers()

    publications = []

    for researcher in researchers:

        if isinstance(researcher, str):
            researcher_name = researcher
            orcid = researcher

        else:
            researcher_name = (
                researcher.get("name")
                or researcher.get("display_name")
                or ""
            )

            orcid = researcher.get("orcid", "")

        if not orcid:
            print(
                f"AVISO: {researcher_name} no tiene ORCID."
            )
            continue

        print(
            f"Consultando OpenAlex: "
            f"{researcher_name} ({orcid})"
        )

        works = get_works(orcid)

        print(
            f"  -> {len(works)} publicaciones encontradas"
        )

        for work in works:

            title = (work.get("title") or "").strip()

            if not title:
                continue

            year = work.get("publication_year")

            if not year:
                continue

            doi = normalize_doi(work.get("doi", ""))

            # Información de revista.
            primary_location = (
                work.get("primary_location") or {}
            )

            source = (
                primary_location.get("source") or {}
            )

            journal = (
                source.get("display_name") or ""
            ).strip()

            # Bibliografía.
            biblio = work.get("biblio") or {}

            volume = biblio.get("volume") or ""
            issue = biblio.get("issue") or ""
            first_page = biblio.get("first_page") or ""
            last_page = biblio.get("last_page") or ""

            pages = ""

            if first_page and last_page:
                pages = f"{first_page}-{last_page}"
            elif first_page:
                pages = first_page

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
                    authors.append(name)

            publication = {
                "title": title,
                "year": year,
                "doi": doi,
                "authors": authors,
                "journal": journal,
                "volume": volume,
                "issue": issue,
                "pages": pages,
                "bibtex": make_bibtex(work),
                "openalex_id": work.get("id", ""),
            }

            publications.append(publication)

    return publications


# ============================================================
# ELIMINAR DUPLICADOS
# ============================================================

def deduplicate_publications(publications):
    """Elimina publicaciones duplicadas por DOI o título."""

    unique = {}

    for publication in publications:

        doi = normalize_doi(
            publication.get("doi", "")
        )

        title = normalize_title(
            publication.get("title", "")
        )

        if doi and not is_repository_doi(doi):
            key = f"doi:{doi.lower()}"
        else:
            key = f"title:{title}"

        if not key:
            continue

        # Si ya existe, conservamos la primera entrada.
        if key not in unique:
            unique[key] = publication

    return list(unique.values())


# ============================================================
# HTML
# ============================================================

def make_doi_html(doi):
    """Genera el enlace DOI."""

    if not doi:
        return ""

    return (
        f'<a href="http://dx.doi.org/{html.escape(doi)}" '
        f'title="View document on publisher site" '
        f'target="_blank">[DOI]</a> '
        f'(<img src="{EXTERNAL_ICON}" '
        f'alt="external link" '
        f'style="width:12px;height:12px;">)'
    )


def make_publication_html(publication, index):
    """Genera el HTML de una publicación."""

    title = html.escape(
        publication.get("title", "")
    )

    journal = html.escape(
        publication.get("journal", "")
    ).upper()

    authors = format_authors(
        [
            {
                "author": {
                    "display_name": author
                }
            }
            for author in publication.get(
                "authors",
                []
            )
        ]
    )

    authors = html.escape(authors)

    year = publication.get("year", "")

    volume = publication.get("volume", "")
    issue = publication.get("issue", "")
    pages = publication.get("pages", "")

    doi = normalize_doi(
        publication.get("doi", "")
    )

    doi_html = make_doi_html(doi)

    metadata = ""

    if journal:
        metadata += f"<em>{journal}</em>"

    if volume:
        metadata += f", vol. {html.escape(str(volume))}"

    if issue:
        metadata += f", iss. {html.escape(str(issue))}"

    if pages:
        metadata += f", pp. {html.escape(str(pages))}"

    if year:
        metadata += f", {html.escape(str(year))}"

    bibtex = html.escape(
        publication.get("bibtex", "")
    )

    bib_id = f"bibtex-{index}"

    return (
        "<p>"
        f"{doi_html} "
        f"{authors}, "
        f"“{title},” "
        f"{metadata}."
        "<br>"
        f'<a href="#" '
        f'onclick="var e=document.getElementById(\'{bib_id}\');'
        f'e.style.display=(e.style.display===\'none\' ? '
        f'\'block\' : \'none\');'
        f'return false;">[Bibtex]</a>'
        f'<pre id="{bib_id}" '
        f'style="display:none; white-space:pre-wrap;">'
        f"{bibtex}"
        "</pre>"
        "</p>"
    )


def generate_html(publications):
    """Genera publications.html agrupado por año."""

    html_output = []

    html_output.append(
        '<div class="publications">'
    )

    current_year = None

    for index, publication in enumerate(
        publications
    ):

        year = publication.get("year")

        if year != current_year:
            if current_year is not None:
                html_output.append("")

            html_output.append(
                f"<h3>{html.escape(str(year))}</h3>"
            )

            current_year = year

        html_output.append(
            make_publication_html(
                publication,
                index
            )
        )

    html_output.append(
        "</div>"
    )

    return "\n".join(html_output)


# ============================================================
# MAIN
# ============================================================

def main():

    print("========================================")
    print("Actualización de publicaciones")
    print("========================================")

    publications = process_publications()

    print(
        f"\nPublicaciones antes de deduplicar: "
        f"{len(publications)}"
    )

    publications = deduplicate_publications(
        publications
    )

    # Ordenar por año descendente y título.
    publications.sort(
        key=lambda publication: (
            -(publication.get("year") or 0),
            publication.get("title", "").lower()
        )
    )

    print(
        f"Publicaciones después de deduplicar: "
        f"{len(publications)}"
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
        f"JSON generado: {JSON_OUTPUT}"
    )

    # --------------------------------------------------------
    # HTML
    # --------------------------------------------------------

    html_content = generate_html(
        publications
    )

    with open(
        HTML_OUTPUT,
        "w",
        encoding="utf-8"
    ) as file:

        file.write(html_content)

    print(
        f"HTML generado: {HTML_OUTPUT}"
    )

    print("========================================")
    print("Proceso terminado correctamente")
    print("========================================")


if __name__ == "__main__":
    main()
