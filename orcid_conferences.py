import os
import requests

TOKEN = os.getenv("ORCID_ACCESS_TOKEN")
print(f"1. Token detectado: {'SÍ' if TOKEN else 'NO (VACÍO)'}")

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.orcid+json",
}

# Prueba directa con un ORCID público
test_orcid = "0000-0002-1825-0097"  # Pon aquí un ORCID de tu researchers1.json si quieres
url = f"https://pub.orcid.org/v3.0/{test_orcid}/works"

print(f"2. Consultando ORCID: {test_orcid} ...")
res = requests.get(url, headers=HEADERS, timeout=15)

print(f"3. Código de respuesta HTTP: {res.status_code}")

if res.status_code == 200:
    data = res.json()
    group = data.get("group", [])
    print(f"4. ÉXITO: Se han encontrado {len(group)} grupos de publicaciones.")
else:
    print(f"4. ERROR: ORCID respondió con:")
    print(res.text[:500])
