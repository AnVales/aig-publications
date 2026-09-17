import json
import re
import html
import requests
from collections import defaultdict

OPENALEX = "https://api.openalex.org/works"
EXTERNAL_ICON = (
    "https://aig.webs.tsc.uc3m.es/wp-content/plugins/papercite/img/external.png"
)

OUTPUT_JSON = "publications.json"
OUTPUT_HTML = "publications.html"
OUTPUT_BIB = "publications.bib"


def normalize_spaces(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def normalize_doi(doi):
    if not doi:
        return ""

    doi = str(doi).strip()

    doi = re.sub(
        r"^https?://(dx\.)?doi\.org/",
        "",
        doi,
        flags=re.IGNORECASE,
    )

    doi = re.sub(
        r"^doi:\s*",
        "",
        doi,
        flags=re.IGNORECASE,
    )

    return doi.strip().rstrip(").,;")


def normalize_openalex_id(value):
    if not value:
        return ""

    value = str(value).strip()

    match = re.search(
        r"https?://openalex\.org/[A-Za-z0-9]+",
        value,
        flags=re.IGNORECASE,
    )

    if match:
        return match.group(0)

    return value


def normalize_pages(pages):
    if not pages:
        return ""

    pages = normalize_spaces(pages)

    if "-" in pages:
        parts = [part.strip() for part in pages.split("-")]

        if len(parts) == 2 and parts[0] == parts[1]:
            return parts[0]

    return pages


def normalize_journal(journal):
    if not journal:
        return ""

    journal = normalize_spaces(journal)

    return {
        "Earth s Future": "Earth’s Future"
    }.get(journal, journal)


def normalize_author_name(name):
    if not name:
        return ""

    name = normalize_spaces(name)

    return (
        name.replace("‐", "-")
        .replace("–", "-")
        .replace("—", "-")
    )


def format_author_for_html(name):
    name = normalize_author_name(name)

    if not name:
        return ""

    parts = name.split()

    if len(parts) == 1:
        return parts[0]

    surname = parts[-1]
    given_names = parts[:-1]

    initials = []

    # Keep particles as initials.
    # Example:
    # Rodrigo Andrade Botelho de Almeida
    # -> R. A. B. D. Almeida
    for part in given_names:
        initials.append(part[0].upper() + ".")

    return " ".join(initials) + " " + surname


def format_authors_for_html(authors):
    formatted = [
        format_author_for_html(author)
        for author in authors
        if author
    ]

    if not formatted:
        return ""

    if len(formatted) == 1:
        return formatted[0]

    if len(formatted) == 2:
        return " and ".join(formatted)

    return ", ".join(formatted[:-1]) + ", and " + formatted[-1]


def make_bibtex_key(authors, year):
    first_author = (
        normalize_author_name(authors[0])
        if authors
        else "publication"
    )

    surname = first_author.split()[-1]

    surname = re.sub(
        r"[^A-Za-z0-9]",
        "",
        surname,
    ).lower()

    return f"{surname}{year}"


def make_bibtex(
    title,
    authors,
    journal,
    year,
    volume="",
    issue="",
    pages="",
    doi="",
    key=None,
):
    if key is None:
        key = make_bibtex_key(authors, year)

    lines = [
        f"@article{{{key},",
        f"  title = {{{title}}},",
        "  author = {" + " and ".join(authors) + "},",
        f"  journal = {{{journal}}},",
    ]

    if volume:
        lines.append(f"  volume = {{{volume}}},")

    if issue:
        lines.append(f"  number = {{{issue}}},")

    if pages:
        lines.append(
            f"  pages = {{{pages.replace('-', '--')}}},"
        )

    lines.append(f"  year = {{{year}}},")

    if doi:
        lines.append(f"  doi = {{{doi}}}")

    lines.append("}")

    return "\n".join(lines)


def is_repository_doi(doi):
    if not doi:
        return False

    doi_lower = doi.lower()

    excluded = [
        "10.5281/zenodo.",
        "10.48550/arxiv.",
        "10.17632/",
        "10.6084/m9.figshare.",
        "10.31219/osf.io/",
    ]

    return any(
        doi_lower.startswith(prefix)
        for prefix in excluded
    )


def get_works(orcid):
    params = {
        "filter": f"author.orcid:{orcid},type:article",
        "per-page": 100,
    }

    response = requests.get(
        OPENALEX,
        params=params,
        timeout=60,
    )

    response.raise_for_status()

    return response.json().get("results", [])


def work_to_publication(work):
    title = normalize_spaces(
        work.get("display_name")
        or work.get("title")
        or ""
    )

    year = (
        work.get("publication_year")
        or work.get("year")
        or ""
    )

    doi = normalize_doi(work.get("doi") or "")

    if is_repository_doi(doi):
        return None

    openalex_id = normalize_openalex_id(
        work.get("id", "")
    )

    authors = []

    for authorship in work.get("authorships", []):
        author = authorship.get("author", {})

        display_name = normalize_author_name(
            author.get("display_name") or ""
        )

        if display_name:
            authors.append(display_name)

    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}

    journal = normalize_journal(
        source.get("display_name") or ""
    )

    biblio = work.get("biblio") or {}

    volume = normalize_spaces(biblio.get("volume") or "")
    issue = normalize_spaces(biblio.get("issue") or "")
    first_page = normalize_spaces(biblio.get("first_page") or "")
    last_page = normalize_spaces(biblio.get("last_page") or "")

    if first_page and last_page:
        pages = f"{first_page}-{last_page}"
    elif first_page:
        pages = first_page
    elif last_page:
        pages = last_page
    else:
        pages = ""

    pages = normalize_pages(pages)

    bibtex_key = make_bibtex_key(authors, year)

    bibtex = make_bibtex(
        title,
        authors,
        journal,
        year,
        volume,
        issue,
        pages,
        doi,
        bibtex_key,
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
        "bibtex": bibtex,
        "openalex_id": openalex_id,
    }


def deduplicate_publications(publications):
    unique = {}

    for publication in publications:
        doi = normalize_doi(
            publication.get("doi", "")
        ).lower()

        title = normalize_spaces(
            publication.get("title", "")
        ).lower()

        if doi:
            key = f"doi:{doi}"
        else:
            key = f"title:{title}"

        unique[key] = publication

    return list(unique.values())


def ensure_unique_bibtex_keys(publications):
    counters = defaultdict(int)

    for publication in publications:
        base_key = make_bibtex_key(
            publication.get("authors", []),
            publication.get("year", ""),
        )

        counters[base_key] += 1
        count = counters[base_key]

        final_key = (
            base_key
            if count == 1
            else f"{base_key}{count}"
        )

        publication["bibtex"] = re.sub(
            r"@article\{[^,]+,",
            f"@article{{{final_key},",
            publication.get("bibtex", ""),
            count=1,
        )

    return publications


def publication_to_html(publication, bibtex_index):
    title = html.escape(
        publication.get("title", ""),
        quote=True,
    )

    doi = normalize_doi(publication.get("doi", ""))

    authors = html.escape(
        format_authors_for_html(
            publication.get("authors", [])
        ),
        quote=True,
    )

    journal = html.escape(
        publication.get("journal", "")
    ).upper()

    volume = html.escape(publication.get("volume", ""))
    issue = html.escape(publication.get("issue", ""))
    pages = html.escape(publication.get("pages", ""))
    year = html.escape(str(publication.get("year", "")))

    doi_html = ""

    if doi:
        doi_url = html.escape(
            "https://doi.org/" + doi,
            quote=True,
        )

        icon_url = html.escape(
            EXTERNAL_ICON,
            quote=True,
        )

        doi_html = (
            f'<a href="{doi_url}" '
            f'title="View document on publisher site" '
            f'target="_blank">[DOI]</a> '
            f'(<img src="{icon_url}" '
            f'alt="external link" '
            f'style="width:12px;height:12px;">) '
        )

    metadata = ""

    if journal:
        metadata += f"<em>{journal}</em>"

    if volume:
        metadata += f", vol. {volume}"

    if issue:
        metadata += f", iss. {issue}"

    if pages:
        metadata += f", {pages}"

    if year:
        metadata += f", {year}"

    bib_id = f"bibtex-{bibtex_index}"

    bibtex = html.escape(
        publication.get("bibtex", "")
    )

    bibtex_html = (
        "<br>"
        '<a href="#" '
        f'onclick="var e=document.getElementById(\'{bib_id}\');'
        "e.style.display=(e.style.display==='none' "
        "? 'block' : 'none');"
        'return false;">[Bibtex]</a>'
        f'<pre id="{bib_id}" '
        'style="display:none; white-space:pre-wrap;">'
        f"{bibtex}"
        "</pre>"
    )

    return (
        f"<p>{doi_html}"
        f"{authors}, "
        f"“{title},” "
        f"{metadata}."
        f"{bibtex_html}"
        "</p>"
    )


def generate_html(publications):
    grouped = defaultdict(list)

    for publication in publications:
        grouped[publication.get("year", "")].append(publication)

    years = sorted(
        grouped.keys(),
        reverse=True,
    )

    output = ['<div class="publications">']

    bibtex_index = 0

    for year in years:
        output.append(
            f"<h3>{html.escape(str(year))}</h3>"
        )

        publications_year = sorted(
            grouped[year],
            key=lambda publication: publication.get(
                "title", ""
            ).lower(),
        )

        for publication in publications_year:
            output.append(
                publication_to_html(
                    publication,
                    bibtex_index,
                )
            )

            bibtex_index += 1

    output.append("</div>")

    return "\n".join(output)


def generate_bibtex_file(publications):
    entries = []

    for publication in publications:
        bibtex = publication.get("bibtex", "").strip()

        if bibtex:
            entries.append(bibtex)

    if not entries:
        return ""

    return "\n\n".join(entries) + "\n"


def main():
    print("Leyendo researchers.json...")

    with open(
        "researchers.json",
        "r",
        encoding="utf-8",
    ) as file:
        data = json.load(file)

    researchers = data["researchers"]
    all_publications = []

    for researcher in researchers:
        name = researcher.get("name", "Unknown")
        orcid = researcher.get("orcid", "")

        if not orcid:
            print(f"⚠️ Sin ORCID para {name}")
            continue

        print(
            f"Buscando publicaciones de {name} ({orcid})..."
        )

        try:
            works = get_works(orcid)
        except Exception as exc:
            print(f"❌ Error con {name}: {exc}")
            continue

        print(f"   Encontrados: {len(works)}")

        for work in works:
            publication = work_to_publication(work)

            if publication is not None:
                all_publications.append(publication)

    all_publications = deduplicate_publications(
        all_publications
    )

    all_publications = ensure_unique_bibtex_keys(
        all_publications
    )

    all_publications.sort(
        key=lambda publication: (
            -int(publication.get("year", 0))
            if str(publication.get("year", "")).isdigit()
            else 0,
            publication.get("title", "").lower(),
        )
    )

    print(f"Guardando {OUTPUT_JSON}...")

    with open(
        OUTPUT_JSON,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            all_publications,
            file,
            ensure_ascii=False,
            indent=2,
        )

    print(f"Generando {OUTPUT_HTML}...")

    with open(
        OUTPUT_HTML,
        "w",
        encoding="utf-8",
    ) as file:
        file.write(generate_html(all_publications))

    print(f"Generando {OUTPUT_BIB}...")

    with open(
        OUTPUT_BIB,
        "w",
        encoding="utf-8",
    ) as file:
        file.write(generate_bibtex_file(all_publications))

    print()
    print("✅ Proceso terminado")
    print(f"   Publicaciones: {len(all_publications)}")
    print(f"   JSON: {OUTPUT_JSON}")
    print(f"   HTML: {OUTPUT_HTML}")
    print(f"   BibTeX: {OUTPUT_BIB}")


if __name__ == "__main__":
    main()
