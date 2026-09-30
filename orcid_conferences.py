import os
import sys
import re

def find_input_bib_file():
    """Busca automáticamente un archivo .bib en el directorio actual."""
    candidates = ["conferencias.bib", "publicaciones.bib", "orcid_conferences.bib", "input.bib"]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
            
    # Si no coincide con los nombres comunes, coge el primer .bib que encuentre
    bib_files = [f for f in os.listdir('.') if f.endswith('.bib') and not f.endswith('_clean.bib') and not f.endswith('_final.bib')]
    if bib_files:
        return bib_files[0]
        
    return None

def clean_author_name(author_str):
    """
    Normaliza cualquier cadena de autores al formato: 'Apellidos, I.'
    Convierte nombres completos (ej. 'Iván', 'Jenny', 'Jean Philippe') a iniciales.
    """
    if not author_str:
        return author_str
        
    authors = [a.strip() for a in author_str.split(' and ')]
    cleaned_authors = []
    
    for author in authors:
        if not author:
            continue
            
        if ',' in author:
            parts = author.split(',', 1)
            last_name = parts[0].strip()
            first_names = parts[1].strip()
        else:
            tokens = author.split()
            if len(tokens) == 1:
                cleaned_authors.append(tokens[0])
                continue
            last_name = tokens[-1]
            first_names = " ".join(tokens[:-1])
            
        tokens = first_names.split()
        initials = []
        for tok in tokens:
            if re.match(r'^[A-ZÀ-Ý]\.+$', tok, re.IGNORECASE):
                initials.append(tok)
            elif '.' in tok:
                sub_toks = [f"{t.strip('.').upper()}." for t in tok.split('.') if t]
                initials.extend(sub_toks)
            else:
                clean_tok = re.sub(r'[^a-zA-ZáéíóúÁÉÍÓÚñÑüÜàèìòùÀÈÌÒÙ]', '', tok)
                if clean_tok:
                    initials.append(f"{clean_tok[0].upper()}.")
                    
        formatted_initials = " ".join(initials)
        if formatted_initials:
            cleaned_authors.append(f"{last_name}, {formatted_initials}")
        else:
            cleaned_authors.append(last_name)
            
    return " and ".join(cleaned_authors)

def process_bibtex_file(input_filename, output_filename):
    print(f"Leyendo archivo de entrada: '{input_filename}'...")
    with open(input_filename, 'r', encoding='utf-8') as f:
        content = f.read()

    raw_entries = content.split('@')
    entries_data = []

    for raw in raw_entries:
        if not raw.strip():
            continue
            
        full_entry = '@' + raw.strip()
        
        match_header = re.match(r'@(\w+)\s*\{\s*([^,]+),', full_entry)
        if not match_header:
            continue
            
        entry_type = match_header.group(1).lower()
        
        match_year = re.search(r'year\s*=\s*\{?(\d{4})\}?', full_entry, re.IGNORECASE)
        year = int(match_year.group(1)) if match_year else 0
        
        # 1. Normalizar autores a Iniciales + Apellidos
        match_author = re.search(r'author\s*=\s*\{([^}]+)\}', full_entry, re.IGNORECASE)
        if match_author:
            original_authors = match_author.group(1)
            cleaned_a = clean_author_name(original_authors)
            full_entry = full_entry.replace(match_author.group(0), f'author = {{{cleaned_a}}}')
            
        # 2. Comprobar/añadir booktitle si falta en @inproceedings o @conference
        if entry_type in ['inproceedings', 'conference']:
            if not re.search(r'\bbooktitle\s*=', full_entry, re.IGNORECASE):
                last_brace_idx = full_entry.rfind('}')
                if last_brace_idx != -1:
                    full_entry = full_entry[:last_brace_idx].rstrip()
                    if not full_entry.endswith(','):
                        full_entry += ','
                    full_entry += '\n  booktitle = {Proceedings}\n}'

        entries_data.append({
            'year': year,
            'entry': full_entry
        })

    # Ordenar por año descendente (más recientes primero)
    entries_data.sort(key=lambda x: x['year'], reverse=True)

    # Reasignar las claves con pub_AÑO_palabra_N
    final_entries = []
    for count, item in enumerate(entries_data, start=1):
        entry_text = item['entry']
        match_header = re.match(r'@(\w+)\s*\{\s*([^,]+),', entry_text)
        if match_header:
            etype = match_header.group(1)
            old_key = match_header.group(2)
            
            match_title = re.search(r'title\s*=\s*\{([^}]+)\}', entry_text, re.IGNORECASE)
            title_slug = "pub"
            if match_title:
                words = re.findall(r'\w+', match_title.group(1).lower())
                if words:
                    title_slug = words[0]
                    
            new_key = f"pub_{item['year']}_{title_slug}_{count}"
            entry_text = entry_text.replace(f"@{etype}{{{old_key},", f"@{etype}{{{new_key},", 1)
            
        final_entries.append(entry_text)

    with open(output_filename, 'w', encoding='utf-8') as f:
        f.write("\n\n".join(final_entries) + "\n")

    print(f"Éxito: Procesadas {len(final_entries)} entradas y guardadas en '{output_filename}'.")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        infile = sys.argv[1]
        outfile = sys.argv[2] if len(sys.argv) > 2 else infile
    else:
        infile = find_input_bib_file()
        outfile = infile if infile else "orcid_conferences.bib"

    if not infile or not os.path.exists(infile):
        print("Error: No se encontró ningún archivo .bib en el directorio.")
        sys.exit(1)

    process_bibtex_file(infile, outfile)
