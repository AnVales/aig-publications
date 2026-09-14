```python
import json
import re
import html
import requests
from collections import defaultdict

OPENALEX = "https://api.openalex.org/works"

EXTERNAL_ICON = (
    "https://aig.webs.tsc.uc3m.es/"
    "wp-content/plugins/papercite/img/external.png"
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
        parts = [p.strip() for p in pages.split("-")]

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
        name
        .replace("‐", "-")
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
    #
    # Example:
    # Rodrigo Andrade Botelho de Almeida
    # -> R. A. B. D. Almeida
    #
    for part in given_names:
        if part:
            initials.append(part[0].upper() + ".")

    return " ".join(initials) + " " + surname


def format_authors_for_html(authors):
    formatted = [
        format_author_for_html(a)
        for a in authors
        if a
    ]

    if not formatted:
        return ""

    if len(formatted) == 1:
        return formatted[0]

    if len(formatted) == 2:
        return " and ".join(formatted)

    return ", ".join(formatted[:-1]) + ", and " + formatted[-1]


def escape_bibtex_value(value):
    """
    Escapa caracteres problemáticos dentro de valores BibTeX.

    No escapamos las llaves porque se utilizan para
    proteger el contenido de los campos.
    """
    if not value:
        return ""

    value = str(value)

    value = value.replace("\\", "\\\\")

    return value


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

    year = str(year)

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
        key = make_bibtex_key(
            authors,
            year,
        )

    title = escape_bibtex_value(title)
    journal = escape_bibtex_value(journal)
    year = escape_bibtex_value(year)
    volume = escape_bibtex_value(volume)
    issue = escape_bibtex_value(issue)
    pages = escape_bibtex_value(
        pages.replace("-", "--")
    )
    doi = escape_bibtex_value(doi)

    escaped_authors = [
        escape_bibtex_value(author)
        for author in authors
        if author
    ]

    lines = [
        f"@article{{{key},",
        f"  title = {{{title}}},",
        "  author = {"
        + " and ".join(escaped_authors)
        + "},",
        f"  journal = {{{journal}}},",
    ]

    if volume:
        lines.append(
            f"  volume = {{{volume}}},"
        )

    if issue:
        lines.append(
            f"  number = {{{issue}}},"
        )

    if pages:
        lines.append(
            f"  pages = {{{pages}}},"
        )

    lines.append(
        f"  year = {{{year}}},"
    )

    if doi:
        lines.append(
            f"  doi = {{{doi}}}"
        )

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
```
