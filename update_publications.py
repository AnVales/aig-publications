import json
import urllib.request
import urllib.parse
from datetime import datetime

OPENALEX = "https://api.openalex.org/works"


def get_works(orcid):
    """Busca publicaciones de un investigador en OpenAlex."""
    
    url = (
        f"{OPENALEX}"
        f"?filter=author.orcid:{orcid},type:article"
        f"&per-page=200"
    )

    try:
        with urllib.request.urlopen(url) as response:
            data = json.loads(response.read().decode())

        return data.get("results", [])

    except Exception as e:
        print(f"Error buscando {orcid}: {e}")
        return []


def reconstruct_abstract(inverted_index):
    """Reconstruye el abstract si OpenAlex lo proporciona."""

    if not inverted_index:
        return ""

    words = []

    for word, positions in inverted_index.items():
        for position in positions:
            words.append((position, word))

    words.sort()

    return " ".join(word for _, word in words)


# Cargar investigadores
with open("researchers.json", encoding="utf-8") as f:
    researchers = json.load(f)["researchers"]

publications = {}
all_publications = []

for researcher in researchers:

    print(f"Buscando publicaciones de {researcher['name']}...")

    works = get_works(researcher["orcid"])

    for work in works:

        # Solo artículos de revista
        if work.get("type") != "article":
            continue

        title = work.get("title")

        if not title:
            continue

        doi = work.get("doi")

        # Identificador para eliminar duplicados
        key = doi.lower() if doi else title.lower()

        if key in publications:
            continue

        publication_year = work.get("publication_year")

        source = None

        if work.get("primary_location"):
            source_info = work["primary_location"].get("source")

            if source_info:
                source = source_info.get("display_name")

        authors = []

        for authorship in work.get("authorships", []):

            author = authorship.get("author", {}).get("display_name")

            if author:
                authors.append(author)

        publication = {
            "title": title,
            "authors": authors,
            "year": publication_year,
            "journal": source,
            "doi": doi,
            "url": work.get("doi"),
            "openalex_id": work.get("id")
        }

        publications[key] = publication
        all_publications.append(publication)


# Ordenar por año descendente
all_publications.sort(
    key=lambda x: x.get("year") or 0,
    reverse=True
)


# Guardar JSON
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


# Generar un HTML sencillo para WordPress
html = []

current_year = None

for pub in all_publications:

    year = pub.get("year")

    if year != current_year:

        html.append(f"<h3>{year}</h3>")
        current_year = year

    authors = ", ".join(pub["authors"])

    title = pub["title"]

    journal = pub.get("journal") or ""

    doi = pub.get("doi")

    text = (
        f"<strong>{authors}</strong>. "
        f"“{title}.” "
        f"<em>{journal}</em>"
    )

    if doi:

        text += (
            f' <a href="{doi}" target="_blank">'
            f"[DOI]</a>"
        )

    html.append(f"<p>{text}</p>")


with open(
    "publications.html",
    "w",
    encoding="utf-8"
) as f:

    f.write("\n".join(html))


print()
print(f"Total de publicaciones únicas: {len(all_publications)}")
print("Archivos generados correctamente.")
