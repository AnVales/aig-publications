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

```
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
```

def normalize_title(title):
"""Normaliza títulos para detectar duplicados."""

```
if not title:
    return ""

title = title.lower()
title = re.sub(r"[^\w\s]", "", title)
title = re.sub(r"\s+", " ", title).strip()

return title
```

def normalize_doi(doi):
"""Normaliza un DOI eliminando prefijos URL."""

```
if not doi:
    return ""

doi = doi.lower().strip()

prefixes = [
    "https://doi.org/",
    "http://doi.org/",
    "http://dx.doi.org/",
    "https://dx.doi.org/",
]

for prefix in prefixes:
    if doi.startswith(prefix):
        doi = doi[len(prefix):]

return doi
```

def is_repository_doi(doi):
"""Detecta DOI de repositorios/preprints que no queremos mostrar."""

```
if not doi:
    return False

doi = doi.lower()

repositories = [
    "zenodo.org",
    "10.5281/zenodo",
]

return any(repo in doi for repo in repositories)
```

def format_author(name):
"""
Convierte:
'Fernando Díaz-de-María'
en:
'F. Díaz-de-María'
"""

```
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
```

def format_authors(authors):
"""Da formato a la lista de autores."""

```
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
```

def escape_bibtex(value):
"""Escapa caracteres básicos para BibTeX."""

```
if not value:
    return ""

return (
    value
    .replace("&", r"\&")
    .replace("%", r"\%")
    .replace("_", r"\_")
)
```

def make_bibtex(pub):
"""Genera un registro BibTeX básico."""

```
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
    if title_words
    else "article"
)

key = f"{author_key}{year}{title_key}"

fields = []

if pub.get("authors"):
    fields.append(
        f"  author = {{{' and '.join(pub['authors'])}}}"
    )

if pub.get("title"):
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

return "@article{" + key + ",\n" + ",\n".join(fields) + "\n}"
```

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

```
print(f"Buscando publicaciones de {researcher['name']}...")

works = get_works(researcher["orcid"])

for work in works:

    if work.get("type") != "article":
        continue

    title = work.get("title")

    if not title:
        continue

    doi = work.get("doi")

    # Ignorar Zenodo y otros registros de repositorio
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

    # ---
```
