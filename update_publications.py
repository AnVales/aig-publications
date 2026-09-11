```python
import json
import urllib.request
import urllib.parse
import re
import html


OPENALEX = "https://api.openalex.org/works"

EXTERNAL_ICON = (
    "https://aig.webs.tsc.uc3m.es/"
    "wp-content/plugins/papercite/img/external.png"
)


def get_works(orcid):
    """Busca artículos de un investigador en OpenAlex."""

    url = (
        f"{OPENALEX}"
        f"?filter=author.orcid:{urllib.parse.quote(orcid)},type:article"
        f"&per-page=200"
    )

    try:
        with urllib.request.urlopen(url) as response:
            data = json.loads(response.read().decode("utf-8"))

        return data.get("results", [])

    except Exception as e:
        print(f"Error buscando {orcid}: {e}")
        return []


def normalize_title(title):
    """Normaliza títulos para detectar duplicados."""

    if not title:
        return ""

    title = title.lower()
    title = re.sub(r"[^\w\s]", "", title)
    title = re.sub(r"\s+", " ", title).strip()

    return title


def normalize_doi(doi):
    """Normaliza un DOI eliminando URLs y prefijos."""

    if not doi:
        return ""

    doi = doi.strip().lower()

    prefixes = [
        "https://doi.org/",
        "http://doi.org/",
        "http://dx.doi.org/",
        "https://dx.doi.org/",
        "doi:"
    ]

    for prefix in prefixes:
        if doi.startswith(prefix):
            doi = doi[len(prefix):]

    return doi


def is_repository_doi(doi):
    """Detecta DOI de repositorios/preprints que no queremos mostrar."""

    if not doi:
        return False

    doi = doi.lower()

    repositories = [
        "zenodo.org",
        "10.5281/zenodo",
    ]

    return any(repo in doi for repo in repositories)


def format_author(name):
    """
    Convierte, por ejemplo:

    'Fernando Díaz-de-María'
    en:

    'F. Díaz-de-María'
    """

    if not name:
        return ""

    name = name.strip()

    parts = name.split()

    if len(parts) == 1:
        return name

    surname = parts[-1]
    given_names = parts[:-1]

    initials = []

    for given in given_names:
        if given:
            initials.append(given[0].upper() + ".")

    return " ".join(initials + [surname])


def format_authors(authors):
    """Da formato a la lista de autores."""

    formatted = [
        format_author(author)
        for author in authors
        if author
    ]

    if not formatted:
        return ""

    if len(formatted) == 1:
        return formatted[0]

    if len(formatted) == 2:
        return f"{formatted[0]} and {formatted[1]}"

    return (
        ", ".join(formatted[:-1])
        + ", and "
        + formatted[-1]
    )


def escape_bibtex(value):
    """Escapa caracteres básicos para BibTeX."""

    if not value:
        return ""

    return (
        value
        .replace("&", r"\&")
        .replace("%", r"\%")
        .replace("_", r"\_")
    )


def make_bibtex(pub):
    """Genera un registro BibTeX."""

    first_author = (
        pub["authors"][0]
        if pub["authors"]
        else "publication"
    )

    author_key = re.sub(
        r"[^a-zA-Z0-9]",
        "",
        first_author.split()[-1].lower()
    )

    year = pub.get("year") or ""

    title_words = re.findall(
        r"[A-Za-z0-9]+",
        pub.get("title", "")
    )

    title_key = (
        title_words[0].lower()
        if title_words else "article"
    )

    key = f"{author_key}{year}{title_key}"

    fields = []

    fields.append(
        f"  author = {{{' and '.join(pub['authors'])}}}"
    )

    fields.append(
        f"  title = {{{escape_bibtex(pub['title'])}}}"
    )

    if pub.get("journal"):
        fields.append(
            f"  journal = {{{escape_bibtex(pub['journal'])}}}"
        )

    if pub.get("year"):
        fields.append(
            f"  year = {{{pub['year']}}}"
        )

    if pub.get("volume"):
        fields.append(
            f"  volume = {{{pub['volume']}}}"
        )

    if pub.get("issue"):
        fields.append(
            f"  number = {{{pub['issue']}}}"
        )

    if pub.get("pages"):
        fields.append(
            f"  pages = {{{pub['pages']}}}"
        )

    if pub.get("doi"):
        fields.append(
            f"  doi = {{{normalize_doi(pub['doi'])}}}"
        )

    return (
        "@article{" + key + ",\n"
        + ",\n".join(fields)
        + "\n}"
    )


# ============================================================
# CARGAR INVESTIGADORES
# ============================================================

with open("researchers.json", encoding="utf-8") as f:
    researchers = json.load(f)["researchers"]


publications_by_doi = {}
publications_by_title = {}


# ============================================================
# BUSCAR PUBLICACIONES
# ============================================================

for researcher in researchers:

    print(f"Buscando publicaciones de {researcher['name']}...")

    works = get_works(researcher["orcid"])

    for work in works:

        # Solo artículos
        if work.get("type") != "article":
            continue

        title = work.get("title")

        if not title:
            continue

        doi = work.get("doi")

        # Ignorar Zenodo y otros repositorios
        if is_repository_doi(doi):
            continue

        normalized_doi = normalize_doi(doi)
        normalized_title = normalize_title(title)

        # ----------------------------------------------------
        # DATOS DE LA REVISTA
        # ----------------------------------------------------

        journal = ""

        primary_location = work.get("primary_location") or {}
        source_info = primary_location.get("source") or {}

        if source_info:
            journal = source_info.get("display_name") or ""

        # ----------------------------------------------------
        # AUTORES
        # ----------------------------------------------------

        authors = []

        for authorship in work.get("authorships", []):

            author = (
                authorship
                .get("author", {})
                .get("display_name")
            )

            if author and author not in authors:
                authors.append(author)

        # ----------------------------------------------------
        # DATOS BIBLIOGRÁFICOS
        # ----------------------------------------------------

        biblio = work.get("biblio") or {}

        volume = biblio.get("volume")
        issue = biblio.get("issue")

        first_page = biblio.get("first_page")
        last_page = biblio.get("last_page")

        pages = ""

        if first_page and last_page:

            if str(first_page) == str(last_page):
                pages = str(first_page)
            else:
                pages = f"{first_page}-{last_page}"

        elif first_page:
            pages = str(first_page)

        publication = {
            "title": title,
            "authors": authors,
            "year": work.get("publication_year"),
            "journal": journal,
            "doi": doi,
            "volume": volume,
            "issue": issue,
            "pages": pages,
            "openalex_id": work.get("id")
        }

        # ----------------------------------------------------
        # ELIMINAR DUPLICADOS POR DOI
        # ----------------------------------------------------

        if (
            normalized_doi
            and normalized_doi in publications_by_doi
        ):
            continue

        # ----------------------------------------------------
        # ELIMINAR DUPLICADOS POR TÍTULO
        # ----------------------------------------------------

        if normalized_title in publications_by_title:

            existing = publications_by_title[normalized_title]

            # Preferimos el registro que tenga DOI
            if not existing.get("doi") and doi:

                publications_by_title[
                    normalized_title
                ] = publication

                if normalized_doi:
                    publications_by_doi[
                        normalized_doi
                    ] = publication

            continue

        # ----------------------------------------------------
        # GUARDAR PUBLICACIÓN
        # ----------------------------------------------------

        publications_by_title[
            normalized_title
        ] = publication

        if normalized_doi:
            publications_by_doi[
                normalized_doi
            ] = publication


# ============================================================
# CONVERTIR A LISTA
# ============================================================

all_publications = list(
    publications_by_title.values()
)


# ============================================================
# ORDENAR
# ============================================================

all_publications.sort(
    key=lambda x: (
        x.get("year") or 0,
        x.get("title") or ""
    ),
    reverse=True
)


# ============================================================
# GUARDAR JSON
# ============================================================

with open(
    "publications.json",
    "w",
    encoding="utf-8"
) as f:

    json.dump(
        all_publications,
        f,
        ensure_ascii=False,
        indent=2
    )


# ============================================================
# GENERAR HTML PARA WORDPRESS
# ============================================================

html_output = []

current_year = None


for index, pub in enumerate(all_publications):

    year = pub.get("year")

    # --------------------------------------------------------
    # CABECERA DEL AÑO
    # --------------------------------------------------------

    if year != current_year:

        html_output.append(f"<h3>{year}</h3>")

        current_year = year

    # --------------------------------------------------------
    # DATOS
    # --------------------------------------------------------

    authors = format_authors(pub["authors"])

    title = html.escape(
        pub["title"],
        quote=True
    )

    journal = html.escape(
        pub.get("journal") or "",
        quote=True
    ).upper()

    doi = pub.get("doi")

    volume = pub.get("volume")
    issue = pub.get("issue")
    pages = pub.get("pages")

    # --------------------------------------------------------
    # CONSTRUIR REFERENCIA
    # --------------------------------------------------------

    reference = ""

    # --------------------------------------------------------
    # DOI + ICONO
    #
    # FORMATO:
    #
    # <a href="http://dx.doi.org/..." title="View document
    # on publisher site">[DOI]</a>
    # (<img src="...external.png">)
    # --------------------------------------------------------

    if doi:

        doi_clean = normalize_doi(doi)

        doi_url = (
            f"http://dx.doi.org/{doi_clean}"
        )

        reference += (
            f'<a href="{html.escape(doi_url, quote=True)}" '
            f'title="View document on publisher site" '
            f'target="_blank">[DOI]</a> '
        )

        reference += (
            f'(<img src="{EXTERNAL_ICON}" '
            f'alt="external link" '
            f'style="width:12px;height:12px;">) '
        )

    # --------------------------------------------------------
    # AUTORES
    # --------------------------------------------------------

    reference += (
        f"{html.escape(authors)}, "
    )

    # --------------------------------------------------------
    # TÍTULO
    # --------------------------------------------------------

    reference += (
        f"“{title},” "
    )

    # --------------------------------------------------------
    # REVISTA
    # --------------------------------------------------------

    if journal:
        reference += f"<em>{journal}</em>"

    # --------------------------------------------------------
    # VOLUMEN
    # --------------------------------------------------------

    if volume:
        reference += f", vol. {volume}"

    # --------------------------------------------------------
    # ISSUE
    # --------------------------------------------------------

    if issue:
        reference += f", iss. {issue}"

    # --------------------------------------------------------
    # PÁGINAS
    # --------------------------------------------------------

    if pages:
        reference += f", pp. {pages}"

    # --------------------------------------------------------
    # AÑO
    # --------------------------------------------------------

    reference += f", {year}."

    # --------------------------------------------------------
    # BIBTEX DESPLEGABLE
    # --------------------------------------------------------

    bibtex = html.escape(
        make_bibtex(pub)
    )

    bibtex_id = f"bibtex-{index}"

    reference_html = (
        f"<p>{reference}<br>"
        f'<a href="#" '
        f'onclick="var e=document.getElementById(\'{bibtex_id}\');'
        f"e.style.display=(e.style.display==='none' ? 'block' : 'none');"
        f'return false;">[Bibtex]</a>'
        f'<pre id="{bibtex_id}" '
        f'style="display:none; white-space:pre-wrap;">'
        f"{bibtex}</pre>"
        f"</p>"
    )

    html_output.append(reference_html)


# ============================================================
# GUARDAR HTML
# ============================================================

with open(
    "publications.html",
    "w",
    encoding="utf-8"
) as f:

    f.write("\n".join(html_output))


print()
print(
    f"Total de publicaciones únicas: "
    f"{len(all_publications)}"
)
print("Archivos generados correctamente.")
```
