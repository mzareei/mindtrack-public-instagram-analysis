# Capa 2 con dos modelos de lenguaje

Las categorías del libro de códigos (`anotacion/CODEBOOK.md`), aplicadas a las
212 publicaciones del kit ciego por **dos modelos de lenguaje distintos**, cada
uno por su lado. Donde coinciden, la etiqueta se acepta; donde no, decide una
persona. Después, el mismo contraste intrasujeto que en la capa 1, sobre las
categorías.

## Antes de correr sobre el corpus completo: gobernanza

Esto envía captions e imágenes de pacientes a las APIs de Anthropic y OpenAI.
Van anonimizados (sin handles, sin IDs, nombre de fichero opaco, un post por
llamada sin contexto) y ninguna de las dos empresas entrena con lo que recibe
por API. Aun así es **tratamiento por un tercero fuera de México**. La
aprobación del CEIC cubre el raspado del grupo control; si cubre esto es una
pregunta para la investigadora responsable. Resolverla antes de pasar de
`--prueba 3` al corpus entero.

## Cómo correr

```
python ig/analisis/anotacion_llm/anotar_llm.py --prueba 3      # 3 posts por modelo, para ver que funciona
python ig/analisis/anotacion_llm/anotar_llm.py                 # los 212, los dos modelos, reanudable (~30-40 min)
python ig/analisis/anotacion_llm/correr_capa2.py               # acuerdo + contraste + reporte, segundos
```

Credenciales en `C:\Github\Mindtrack\.env`:

```
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
ANTHROPIC_MODEL=claude-sonnet-4-5     # opcional, por defecto
OPENAI_MODEL=gpt-4o                   # opcional, por defecto
```

Los nombres de modelo cambian; si uno da error 404/400, poner el vigente en
`.env`. Hace falta un modelo **con visión**: 37 de los 212 posts no tienen
texto.

Sin SDKs ni paquetes nuevos: `urllib` de la biblioteca estándar. Temperatura 0.
Cada modelo escribe `etiquetas_<proveedor>.jsonl` línea a línea, así que si se
corta a medias se relanza y sigue donde iba. Coste aproximado: 212 posts × 2
modelos con imagen en baja resolución, del orden de unos pocos dólares.

`--simular` genera etiquetas falsas sin llamar a nada, para probar
`correr_capa2.py`. El reporte lo dice en mayúsculas cuando son simuladas.

## Qué hay aquí

| fichero | qué es |
|---|---|
| `prompt_codebook.md` | el libro de códigos convertido en instrucción, en español, con casos frontera y formato JSON estricto. **Única fuente de verdad**: cambiar aquí, no en el código. |
| `anotar_llm.py` | llama a los dos modelos, un post por llamada, ciego. Reanudable. Modos `--prueba N`, `--solo <proveedor>`, `--simular`. |
| `acuerdo.py` | κ de Cohen y PABAK por categoría; cola de adjudicación; muestra de validez; etiquetas de consenso. |
| `contraste_capa2.py` | peri vs basal sobre las categorías, tres versiones (consenso, modelo A, modelo B). |
| `correr_capa2.py` | acuerdo + contraste + `REPORTE_capa2.md` en una orden. |

## Qué produce (`resultados_ig/capa2/`, ignorada por git)

| fichero | contenido | quién lo usa |
|---|---|---|
| `etiquetas_anthropic.csv`, `etiquetas_openai.csv` (+ `.jsonl`) | una fila por post por modelo: 8 categorías, orientación temporal, confianza, justificación de una frase | el resto del pipeline |
| `acuerdo.csv` | prevalencia, acuerdo bruto, κ, PABAK, lectura, usable | el artículo |
| **`desacuerdos.csv`** | **la cola humana**: un post por fila, las categorías en desacuerdo, texto, imagen, las dos justificaciones, y columnas `decision_humana_<cat>` vacías | una persona del equipo clínico |
| **`muestra_validez.csv`** | 20% al azar de los posts donde los modelos coinciden, con columnas `humano_<cat>` vacías | la misma persona |
| `etiquetas_consenso.csv` | donde coinciden, la etiqueta; donde no, vacío hasta adjudicar | el contraste |
| `contraste_capa2.csv` | el contraste, tres versiones | el artículo |
| `REPORTE_capa2.md` | el resumen legible | todos |

## El diseño, en corto

**Ciego.** Cada llamada lleva un solo post: código opaco, texto, imagen. Sin
fecha, sin paciente, sin ventana, sin los demás posts. El modelo no puede
construir una historia por persona porque no sabe quién es nadie.

**Dos modelos, no uno.** El acuerdo es la única evidencia de que las etiquetas
miden algo. Con uno solo no hay forma de saberlo.

**Acuerdo no es validez.** Dos modelos pueden coincidir en el mismo error, y
los modelos de lenguaje sobredetectan malestar en texto ambiguo. Por eso una
persona revisa el 20% de las coincidencias (`muestra_validez.csv`) y de ahí
sale un κ humano-vs-modelos que también va al artículo.

**Adjudicación, no re-anotación.** La persona decide solo las celdas en
desacuerdo. En una corrida simulada al 80% de acuerdo salen unas 260 decisiones
sobre 212 posts; con modelos reales y el mismo prompt el acuerdo suele ser
mayor y la cola más corta.

**Tres versiones del contraste.** Consenso (principal), y cada modelo por
separado. Si la conclusión cambia según el modelo, no es una conclusión.

## Umbrales

- κ ≥ 0.60 usable. Por debajo, la categoría se reporta con su κ y se excluye
  del contraste principal o se fusiona con una vecina.
- Con categorías raras, PABAK es la cifra justa; κ de Cohen castiga la
  prevalencia baja aunque el acuerdo sea del 95%.
- FDR sobre 8 pruebas. "Sube en 13 de 18" informa más que el p.

## Para retomar desde otra sesión

1. Leer este README y, si existe, `resultados_ig/capa2/REPORTE_capa2.md`.
2. Si hay `desacuerdos.csv` con decisiones humanas rellenas, `correr_capa2.py`
   las incorpora solo; volver a correrlo.
3. Para cambiar una categoría o un caso frontera: `prompt_codebook.md` y el
   `CODEBOOK.md` humano a la vez, y volver a etiquetar (borrar los `.jsonl`).
4. Para añadir un tercer modelo: una entrada más en `PROVEEDORES` de
   `anotar_llm.py` y su formato de llamada; `acuerdo.py` compara los dos
   primeros de la tupla `proveedores`.
