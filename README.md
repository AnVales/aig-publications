Generación automática de publicaciones en formato BibTeX

Este repositorio contiene un sistema automatizado para recopilar las publicaciones científicas de un grupo de investigadores y generar un archivo publications.bib, que puede utilizarse en páginas web académicas, repositorios institucionales o documentos LaTeX.

¿Cómo funciona?

El sistema utiliza los identificadores ORCID de los investigadores para localizar sus publicaciones en OpenAlex.

El proceso es el siguiente:

researchers.json
       │
       ▼
Identificadores ORCID
       │
       ▼
Consulta a OpenAlex
       │
       ▼
Recopilación de metadatos bibliográficos
       │
       ▼
Generación de publications.bib
Fuentes de información

ORCID: proporciona el identificador único de cada investigador. Este identificador permite distinguir a investigadores con nombres similares.

OpenAlex: proporciona los datos bibliográficos de las publicaciones, como el título, los autores, el año de publicación, la revista, el volumen, las páginas y el DOI, cuando están disponibles.

GitHub Actions: ejecuta automáticamente el script y actualiza el archivo publications.bib.

Nota: Google Scholar no se utiliza en este sistema. Además, OpenAlex puede no incluir todas las publicaciones de un investigador, por lo que el archivo generado podría no ser completamente exhaustivo.

Estructura del repositorio
aig-publications/
├── researchers.json
├── generate_bibtex.py
├── publications.bib
└── .github/
    └── workflows/
        └── publications.yml
researchers.json

Este archivo contiene la lista de investigadores y sus identificadores ORCID.

Ejemplo:

{
  "researchers": [
    {
      "name": "Nombre del investigador",
      "orcid": "0000-0000-0000-0000"
    }
  ]
}
generate_bibtex.py

Es el script de Python encargado de:

Leer la lista de investigadores.

Consultar OpenAlex mediante los identificadores ORCID.

Recuperar los metadatos de las publicaciones.

Eliminar posibles duplicados.

Generar las entradas bibliográficas en formato BibTeX.

Guardar el resultado en publications.bib.

publications.bib

Es el archivo de salida que contiene las referencias bibliográficas en formato BibTeX. Puede importarse en gestores bibliográficos y utilizarse, por ejemplo, en documentos escritos con LaTeX.

publications.yml

El workflow de GitHub Actions ejecuta el script automáticamente según la configuración establecida.

Ejecución automática

El workflow puede ejecutarse de tres formas:

Manualmente, desde la pestaña Actions de GitHub.

Cuando se modifica researchers.json o generate_bibtex.py.

De forma programada, mediante una tarea semanal.

El workflow instala las dependencias necesarias, ejecuta el script y guarda los cambios en publications.bib.

Requisitos

Un repositorio de GitHub.

Python 3.12 o una versión compatible.

Un archivo researchers.json con los identificadores ORCID.

La dependencia de Python requests.

La dependencia se instala automáticamente mediante GitHub Actions:

python -m pip install requests
Limitaciones

La información depende de los registros disponibles en OpenAlex. Por este motivo:

Algunas publicaciones pueden no aparecer.

Puede haber metadatos incompletos.

Los datos pueden contener errores o duplicados que requieran revisión.

Las publicaciones más recientes pueden tardar en estar disponibles.

Se recomienda revisar periódicamente el archivo publications.bib y corregir manualmente las referencias que lo necesiten.
