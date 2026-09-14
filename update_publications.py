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

MAILTO = "publications@uc3m.es"

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

# Elimina cualquier formato Markdown accidental.
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

replacements = {
    "Earth s Future": "Earth’s Future",
}

return replacements.get(journal, journal)

def normalize_author_name(name):
if not name:
return ""

name = normalize_spaces(name)

name = name.replace("‐", "-")
name = name.replace("–", "-")
name = name.replace("—", "-")

return name

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

for part in given_names:

    # Partículas del apellido.
    if part.lower() in {
        "de",
        "del",
        "da",
        "do",
        "dos",
        "das",
        "van",
        "von",
    }:
        continue

    # Nombres compuestos.
    if "-" in part:
        first = part.split("-")[0]

        if first:
            initials.append(
                first[0].upper() + "."
            )
    else:
        initials.append(
            part[0].upper() + "."
        )

if not initials:
    return surname

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
if authors:
first_author = normalize_author_name(authors[0])
else:
first_author = "publication"

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
    "  author = {"
    + " and ".join(authors)
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
    bib_pages = pages.replace("-", "--")
    lines.append(
        f"  pages = {{{bib_pages}}},"
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
    "10.31219/osf.io/",
]

return any(
    doi_lower.startswith(prefix)
    for prefix in excluded
)

def get_works(orcid):
params = {
"filter": f"author.orcid:{orcid},type",
"per-page": 100,
"mailto": MAILTO,
}

response = requests.get(
    OPENALEX,
    params=params,
    timeout=60,
)

response.raise_for_status()

data = response.json()

return data.get("results", [])

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

doi = normalize_doi(
    work.get("doi") or ""
)

if is_repository_doi(doi):
    return None

openalex_id = normalize_openalex_id(
    work.get("id", "")
)

authors = []

for authorship in work.get(
    "authorships",
    [],
):
    author = authorship.get(
        "author",
        {},
    )

    display_name = (
        author.get("display_name")
        or ""
    )

    display_name = normalize_author_name(
        display_name
    )

    if display_name:
        authors.append(display_name)

primary_location = (
    work.get("primary_location")
    or {}
)

source = (
    primary_location.get("source")
    or {}
)

journal = normalize_journal(
    source.get("display_name")
    or ""
)

biblio = (
    work.get("biblio")
    or {}
)

volume = normalize_spaces(
    biblio.get("volume")
    or ""
)

issue = normalize_spaces(
    biblio.get("issue")
    or ""
)

first_page = normalize_spaces(
    biblio.get("first_page")
    or ""
)

last_page = normalize_spaces(
    biblio.get("last_page")
    or ""
)

if first_page and last_page:
    pages = f"{first_page}-{last_page}"
elif first_page:
    pages = first_page
elif last_page:
    pages = last_page
else:
    pages = ""

pages = normalize_pages(pages)

bibtex_key = make_bibtex_key(
    authors,
    year,
)

bibtex = make_bibtex(
    title=title,
    authors=authors,
    journal=journal,
    year=year,
    volume=volume,
    issue=issue,
    pages=pages,
    doi=doi,
    key=bibtex_key,
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

for pub in publications:

    doi = normalize_doi(
        pub.get("doi", "")
    ).lower()

    title = normalize_spaces(
        pub.get("title", "")
    ).lower()

    if doi:
        key = f"doi:{doi}"
    else:
        key = f"title:{title}"

    unique[key] = pub

return list(unique.values())

def ensure_unique_bibtex_keys(publications):
counters = defaultdict(int)

for pub in publications:

    authors = pub.get(
        "authors",
        [],
    )

    year = pub.get(
        "year",
        "",
    )

    base_key = make_bibtex_key(
        authors,
        year,
    )

    counters[base_key] += 1

    count = counters[base_key]

    if count == 1:
        final_key = base_key
    else:
        final_key = (
            f"{base_key}{count}"
        )

    bibtex = pub.get(
        "bibtex",
        "",
    )

    bibtex = re.sub(
        r"@article\{[^,]+,",
        f"@article{{{final_key},",
        bibtex,
        count=1,
    )

    pub["bibtex"] = bibtex

return publications

def publication_to_html(
pub,
bibtex_index,
):
title = html.escape(
pub.get("title", "")
)

doi = pub.get(
    "doi",
    "",
)

authors = format_authors_for_html(
    pub.get(
        "authors",
        [],
    )
)

authors = html.escape(
    authors
)

journal = html.escape(
    pub.get(
        "journal",
        "",
    )
).upper()

volume = html.escape(
    pub.get(
        "volume",
        "",
    )
)

issue = html.escape(
    pub.get(
        "issue",
        "",
    )
)

pages = html.escape(
    pub.get(
        "pages",
        "",
    )
)

year = html.escape(
    str(
        pub.get(
            "year",
            "",
        )
    )
)

doi_html = ""

if doi:
    doi_url = (
        "http://dx.doi.org/"
        + html.escape(doi)
    )

    doi_html = (
        f'<a href="{doi_url}" '
        'title="View document on publisher site" '
        'target="_blank">[DOI]</a> '
        f'(<img src="{EXTERNAL_ICON}" '
        'alt="external link" '
        'style="width:12px;height:12px;">) '
    )

metadata = ""

if journal:
    metadata += (
        f"<em>{journal}</em>"
    )

if volume:
    metadata += (
        f", vol. {volume}"
    )

if issue:
    metadata += (
        f", iss. {issue}"
    )

if pages:
    metadata += (
        f", {pages}"
    )

if year:
    metadata += (
        f", {year}"
    )

bib_id = (
    f"bibtex-{bibtex_index}"
)

bibtex = html.escape(
    pub.get(
        "bibtex",
        "",
    )
)

bibtex_html = (
    "<br>"
    f'<a href="#" '
    f'onclick="var e=document.getElementById(\'{bib_id}\');'
    f'e.style.display=(e.style.display===\'none\' ? '
    f'\'block\' : \'none\');'
    f'return false;">[Bibtex]</a>'
    f'<pre id="{bib_id}" '
    'style="display:none; '
    'white-space:pre-wrap;">'
    f'{bibtex}'
    "</pre>"
)

return (
    "<p>"
    f"{doi_html}"
    f"{authors}, "
    f"“{title},” "
    f"{metadata}."
    f"{bibtex_html}"
    "</p>"
)

def generate_html(publications):
grouped = defaultdict(list)

for pub in publications:
    grouped[
        pub.get("year", "")
    ].append(pub)

years = sorted(
    grouped.keys(),
    reverse=True,
)

output = []

output.append(
    '<div class="publications">'
)

bibtex_index = 0

for year in years:

    output.append(
        f'<h3>{html.escape(str(year))}</h3>'
    )

    publications_year = sorted(
        grouped[year],
        key=lambda p: p.get(
            "title",
            "",
        ).lower(),
    )

    for pub in publications_year:

        output.append(
            publication_to_html(
                pub,
                bibtex_index,
            )
        )

        bibtex_index += 1

output.append(
    "</div>"
)

return "\n".join(output)

def main():

print(
    "Leyendo researchers.json..."
)

with open(
    "researchers.json",
    "r",
    encoding="utf-8",
) as f:
    researchers = json.load(f)

all_publications = []

for researcher in researchers:

    name = researcher.get(
        "name",
        "Unknown",
    )

    orcid = researcher.get(
        "orcid",
        "",
    )

    if not orcid:
        print(
            f"⚠️ Sin ORCID para {name}"
        )
        continue

    print(
        f"Buscando publicaciones de "
        f"{name} ({orcid})..."
    )

    try:
        works = get_works(orcid)

    except Exception as exc:
        print(
            f"❌ Error con {name}: {exc}"
        )
        continue

    print(
        f"   Encontrados: {len(works)}"
    )

    for work in works:

        publication = (
            work_to_publication(work)
        )

        if publication is not None:
            all_publications.append(
                publication
            )

all_publications = (
    deduplicate_publications(
        all_publications
    )
)

all_publications = (
    ensure_unique_bibtex_keys(
        all_publications
    )
)

all_publications.sort(
    key=lambda p: (
        -int(p.get("year", 0))
        if str(
            p.get("year", "")
        ).isdigit()
        else 0,
        p.get(
            "title",
            "",
        ).lower(),
    )
)

print(
    f"Guardando {OUTPUT_JSON}..."
)

with open(
    OUTPUT_JSON,
    "w",
    encoding="utf-8",
) as f:
    json.dump(
        all_publications,
        f,
        ensure_ascii=False,
        indent=2,
    )

print(
    f"Generando {OUTPUT_HTML}..."
)

generated_html = generate_html(
    all_publications
)

with open(
    OUTPUT_HTML,
    "w",
    encoding="utf-8",
) as f:
    f.write(generated_html)

print()
print(
    "✅ Proceso terminado"
)
print(
    f"   Publicaciones: "
    f"{len(all_publications)}"
)
print(
    f"   JSON: {OUTPUT_JSON}"
)
print(
    f"   HTML: {OUTPUT_HTML}"
)

if name == "main":
main()
