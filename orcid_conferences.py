import urllib.request
import urllib.parse
import json
import re

# Lista de identificadores ORCID
ORCID_IDS = [
    "0000-0002-8051-7872",
    "0000-0002-0238-2321",
    "0000-0001-8316-2917",
    "0000-0002-3151-2292"
]

OUTPUT_FILE = "conferencias_orcid.bib"

def clean_author_name(author_str):
    """
    Normaliza la cadena de autores al formato: 'Apellidos, I. N.'
    Mantiene autores ya formateados y convierte nombres completos a iniciales.
    """
    if not author_str:
        return author_str
        
    authors = [a.strip() for a in author_str.split(' and ')]
    cleaned_authors = []
    
    for author in authors:
        if not author:
            continue
            
        if ',' in author:
            # Formato "Apellidos, Nombre(s)"
            parts = author.split(',', 1)
            last_name = parts[0].strip()
            first_names = parts[1].strip()
        else:
            # Formato "Nombre(s) Apellidos"
            tokens = author.split()
            if len(tokens) == 1:
                cleaned_authors.append(tokens[0])
                continue
            last_name = tokens[-1]
            first_names = " ".join(tokens[:-1])
            
        # Extraer palabras del nombre para convertirlas en iniciales
        tokens = first_names.split()
        initials = []
        for tok in tokens:
            # Si ya es una inicial con punto (ej. "J." o "J.M.")
            if re.match(r'^[A-ZÀ-Ý]\.+$', tok, re.IGNORECASE):
                initials.append(tok)
            elif '.' in tok:
                # Caso de iniciales pegadas tipo "J.M."
                sub_toks = [f"{t.strip('.').upper()}." for t in tok.split('.') if t]
                initials.extend(sub_toks)
            else:
                # Caso de nombre completo (ej. "Iván" -> "I.")
                clean_tok = re.sub(r'[^a-zA-ZáéíóúÁÉÍÓÚñÑüÜàèìòùÀÈÌÒÙ]', '', tok)
                if clean_tok:
                    initials.append(f"{clean_tok[0].upper()}.")
                    
        formatted_initials = " ".join(initials)
        if formatted_initials:
            cleaned_authors.append(f"{last_name}, {formatted_initials}")
        else:
            cleaned_authors.append(last_name)
            
    return " and ".join(cleaned_authors)

def fetch_crossref_data(orcid):
    url = f"https://api.crossref.org/works?filter=orcid:{orcid}&rows=200"
    req = urllib.request.Request(url, headers={'User-Agent': 'ORCID-Fetcher/1.0'})
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            return data.get('message', {}).get('items', [])
    except Exception as e:
        print(f"Error consultando ORCID {orcid}: {e}")
        return []

def item_to_bibtex(item):
    # Solo procesamos publicaciones de congresos/conferencias
    if item.get('type') != 'proceedings-article':
        return None, None
        
    doi = item.get('DOI', '')
    title = item.get('title', [''])[0] if item.get('title') else ''
    
    # Extraer año
    year = 0
    if 'published-print' in item and 'date-parts' in item['published-print']:
        year = item['published-print']['date-parts'][0][0]
    elif 'published-online' in item and 'date-parts' in item['published-online']:
        year = item['published-online']['date-parts'][0][0]
    elif 'created' in item and 'date-parts' in item['created']:
        year = item['created']['date-parts'][0][0]
        
    # Extraer autores y normalizar a iniciales
    authors = []
    for a in item.get('author', []):
        given = a.get('given', '')
        family = a.get('family', '')
        if family:
            if given:
                authors.append(f"{family}, {given}")
            else:
                authors.append(family)
    
    author_str = clean_author_name(" and ".join(authors))
    
    # Extraer actas / booktitle
    booktitle = ""
    if item.get('container-title'):
        booktitle = item['container-title'][0]
    if not booktitle:
        booktitle = "Proceedings"
        
    # Construir entrada BibTeX
    temp_key = f"temp_{doi}"
    bib = f"@inproceedings{{{temp_key},\n"
    if author_str:
        bib += f"  author = {{{author_str}}},\n"
    if title:
        bib += f"  title = {{{title}}},\n"
    bib += f"  booktitle = {{{booktitle}}},\n"
    if year:
        bib += f"  year = {{{year}}},\n"
    if doi:
        bib += f"  doi = {{{doi}}},\n"
        bib += f"  url = {{https://doi.org/{doi}}},\n"
    bib = bib.rstrip(',\n') + "\n}"
    
    return year, title, bib

def main():
    seen_dois = set()
    entries = []
    
    print("Obteniendo datos de CrossRef para los ORCIDs especificados...")
    for orcid in ORCID_IDS:
        print(f"Procesando ORCID: {orcid}")
        items = fetch_crossref_data(orcid)
        for item in items:
            doi = item.get('DOI')
            if doi and doi in seen_dois:
                continue
            if doi:
                seen_dois.add(doi)
                
            res = item_to_bibtex(item)
            if res and res[0]:
                year, title, bib = res
                entries.append({
                    'year': year,
                    'title': title,
                    'bib': bib
                })

    # Ordenar cronológicamente en sentido inverso (más recientes primero)
    entries.sort(key=lambda x: x['year'], reverse=True)
    
    # Reasignar claves con contador secuencial pub_AÑO_palabra_N
    final_entries = []
    for count, entry in enumerate(entries, start=1):
        year = entry['year']
        title = entry['title']
        bib = entry['bib']
        
        words = re.findall(r'\w+', title.lower())
        title_slug = words[0] if words else "pub"
        
        new_key = f"pub_{year}_{title_slug}_{count}"
        updated_bib = re.sub(r'@inproceedings\{temp_[^,]+,', f'@inproceedings{{{new_key},', bib)
        final_entries.append(updated_bib)

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write("\n\n".join(final_entries) + "\n")

    print(f"\n¡Completado! Se han guardado {len(final_entries)} entradas en '{OUTPUT_FILE}'.")

if __name__ == "__main__":
    main()
