# Generación automática de publicaciones en formato BibTeX

Este repositorio contiene un sistema automatizado para recopilar las publicaciones científicas de un grupo de investigadores y generar un archivo `publications.bib`.

El archivo generado puede utilizarse en páginas web académicas, repositorios institucionales y documentos escritos con LaTeX.

## ¿Cómo funciona?

El sistema utiliza los identificadores **ORCID** de los investigadores para localizar sus publicaciones en **OpenAlex**.

El proceso es el siguiente:

```text
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
```

## Fuentes de información

* **ORCID:** proporciona el identificador único de cada investigador y permite distinguir entre investigadores con nombres similares.
* **OpenAlex:** proporciona los datos bibliográficos de las publicaciones, como el título, los autores, el año de publicación, la revista, el volumen, las páginas y el DOI, cuando están disponibles.
* **GitHub Actions:** ejecuta automáticamente el script y actualiza el archivo `publications.bib`.

> **Nota:** Google Scholar no se utiliza en este sistema. Además, OpenAlex puede no incluir todas las publicaciones de un investigador, por lo que el archivo generado podría no ser completamente exhaustivo.

## Estructura del repositorio

```text
aig-publications/
├── researchers.json
├── generate_bibtex.py
├── publications.bib
└── .github/
    └── workflows/
        └── publications.yml
```

## Archivos principales

### `researchers.json`

Este archivo contiene la lista de investigadores y sus identificadores ORCID.

Ejemplo:

```json
{
  "researchers": [
    {
      "name": "Nombre del investigador",
      "orcid": "0000-0000-0000-0000"
    }
  ]
}
```

### `generate_bibtex.py`

Es el script de Python encargado de:

1. Leer la lista de investigadores.
2. Consultar OpenAlex mediante los identificadores ORCID.
3. Recuperar los metadatos de las publicaciones.
4. Eliminar posibles duplicados.
5. Generar las entradas bibliográficas en formato BibTeX.
6. Guardar el resultado en `publications.bib`.

### `publications.bib`

Es el archivo de salida que contiene las referencias bibliográficas en formato BibTeX.

Puede importarse en gestores bibliográficos y utilizarse, por ejemplo, en documentos escritos con LaTeX.

### `.github/workflows/publications.yml`

Este archivo define el proceso automatizado de **GitHub Actions**.

Se encarga de instalar las dependencias necesarias, ejecutar el script y guardar los cambios en `publications.bib`.

## Ejecución automática

El workflow puede ejecutarse de tres formas:

* **Manualmente**, desde la pestaña [Actions](../../actions) de GitHub.
* **Automáticamente**, cuando se modifica `researchers.json`, `generate_bibtex.py` o el propio workflow.
* **De forma programada**, una vez por semana, cada lunes a las 06:00 UTC.

El resultado de la ejecución es la actualización del archivo:

```text
publications.bib
```

## Requisitos

Para utilizar este sistema se necesita:

* Un repositorio de GitHub.
* Python 3.12 o una versión compatible.
* Un archivo `researchers.json` con los identificadores ORCID.
* La dependencia de Python `requests`.

La dependencia se instala automáticamente mediante GitHub Actions:

```bash
python -m pip install requests
```

## Limitaciones

La información depende de los registros disponibles en OpenAlex. Por este motivo:

* Algunas publicaciones pueden no aparecer.
* Los metadatos pueden estar incompletos.
* Puede haber errores o duplicados que requieran revisión.
* Las publicaciones más recientes pueden tardar en estar disponibles.

Se recomienda revisar periódicamente el archivo `publications.bib` y corregir manualmente las referencias que lo necesiten.

## Licencia

Añade aquí la licencia de tu proyecto si corresponde.
