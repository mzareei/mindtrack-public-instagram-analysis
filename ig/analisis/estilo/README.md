# Capa 1: estilo de escritura, sin anotación

Segunda de las dos capas del análisis de contenido. La pregunta: **¿lo que se
puede contar de un caption sin leerlo (quién habla, qué palabras, cuándo, cómo
se ve) separa a pacientes de controles, o cambia dentro de la misma persona
cerca del episodio?** No requiere anotadores. Corre en un minuto.

La capa 2 (anotación humana, `anotacion/`) mide lo que un contador no ve: el
sentido indirecto, la imagen, la desesperanza dicha con cinco palabras
neutras.

## Cómo correr

```
python ig/analisis/estilo/correr_capa1.py
python ig/analisis/estilo/correr_capa1.py --permutaciones 100    # +10 min, p-valor del AUC
python ig/analisis/estilo/rasgos.py                               # solo la autoprueba del contador
```

Requisitos: haber cerrado el grupo control (`ig/control/cerrar_control.py`),
que deja `controles_emparejados.csv` y un `global_controles_unido_*.json`. El
script localiza los ficheros solo. Sin dependencias nuevas. Una línea por orden
en PowerShell.

## Qué hay aquí

| fichero | qué es |
|---|---|
| `rasgos.py` | los 25 rasgos por cuenta (y conteos por post). Tiene autoprueba. |
| `estadistica.py` | Mann-Whitney, Wilcoxon, signo exacto, FDR. Python puro. |
| `entre_personas.py` | 30 pacientes vs 60 controles: univariadas + logística en CV. Reusa `detector_marco.py`. |
| `intra_persona.py` | peri vs basal dentro de cada paciente, pruebas pareadas. Reusa `ventanas_temporales.py`. |
| `correr_capa1.py` | la orden única. Escribe todo en `resultados_ig/capa1/`. |
| `lexicos/` | las listas de palabras y emoji, con su procedencia en `lexicos/README.md`. |

## Qué produce (en `resultados_ig/capa1/`, carpeta ignorada por git)

| fichero | contenido |
|---|---|
| `REPORTE_capa1.md` | **el resumen que se lee**: veredicto, tablas, cómo interpretarlo, limitaciones |
| `rasgos_cuentas.csv` | una fila por cuenta: id, grupo, n_posts, n_palabras, los 25 rasgos |
| `rasgos_posts.csv` | una fila por post: conteos crudos, sin texto |
| `entre_personas.csv` / `.json` | tabla univariada y todo lo del modelo conjunto |
| `intra_persona.csv` | tabla pareada |
| `salida_consola.txt` | lo que imprimió la corrida |

## Los 25 rasgos

Tres filtros para entrar en la lista: evidencia previa en la literatura de
lenguaje y riesgo suicida; que sobreviva a un caption de cinco palabras con
emoji; que el total quede pequeño frente a 90 cuentas.

| grupo | rasgo | qué cuenta |
|---|---|---|
| hablar de sí | `p1s_100` | yo/me/mi + estoy/siento/quiero, por 100 palabras |
| | `p1p_100` | nosotros/nos |
| | `p23_100` | tú/él/ellos |
| cómo piensan | `absol_100` | nunca/siempre/nada/todo (Al-Mosaiwi & Johnstone 2018) |
| | `neg_100` | no/ni/tampoco/sin |
| | `hedge_100` | quizás/creo/no sé |
| qué sienten | `emo_neg_100` | léxico negativo (SEL si está, v1 si no) |
| | `emo_pos_100` | léxico positivo |
| | `muerte_100` | morir/dolor/cansad*/adiós |
| | `emoji_val` | (emoji positivos − negativos) / total, −1..1 |
| cómo se ve | `palabras_log` | log(1 + palabras), media por post |
| | `emoji_pp`, `hashtag_pp`, `mencion_pp` | por palabra |
| | `puntuacion` | ! + … + MAYÚSCULAS, por palabra |
| cuándo | `noche_share` | posts entre 00:00 y 05:59 |
| | `hora_circ` | hora media circular |
| | `finde_share` | sábado o domingo |
| | `gap_mediana` | días entre posts consecutivos |
| | `burstiness` | desviación / media de esos huecos |
| qué forma | `video_share`, `sin_cap_share`, `solo_simb_share` | vídeo; sin caption; caption solo de emoji/hashtags |
| idioma | `ingles_share` | captions en inglés |
| | `diversidad` | tipos/tokens sobre el texto agregado (NaN si < 20 tokens) |

Las tasas "por 100 palabras" se calculan sobre el texto agregado de la cuenta,
no como media de tasas por post. "Palabra" = token alfabético fuera de hashtags
y menciones. Los huecos (cuentas sin texto, sin emoji con valencia, con menos
de 3 posts) se imputan con la mediana en el modelo y se reportan.

Hora local: `fecha_post_iso` viene sin zona. Se comprobó que la distribución
de horas tiene el valle en 03-06 y el pico en 13-23, patrón de hora local. Se
usa tal cual.

## Cómo leer el resultado

- El AUC entre personas se lee **contra 0.439** (detector de marco, solo
  metadatos), no contra 0.5. Los grupos ya están emparejados en forma; lo que
  el estilo añade es la diferencia con esa referencia.
- 25 pruebas con 30 personas: solo efectos grandes sobreviven FDR. Un rasgo
  nominal (p < 0.05, q > 0.05) es una pista para la capa 2, no un hallazgo.
- Dentro de la persona, "sube en 14 de 18" informa más que el p-valor.
- **Un nulo aquí es informativo**: dice que la señal, si existe, no está en el
  estilo contable, y hay que ir al contenido.

## Resultado de la corrida del 10 sep 2026 (copia de los datos del 9 sep)

| | |
|---|---|
| datos | 30 pacientes / 1,393 posts / 12,267 palabras; 60 controles / 1,282 posts / 12,773 palabras |
| entre personas, 25 rasgos, CV 5×20 | **AUC 0.466** (DE 0.055), contra 0.439 de metadatos: **+0.027** |
| univariadas que sobreviven FDR | **ninguna** (mejor: `p1s_100` AUC 0.614, p 0.077, q 0.94) |
| intra persona, 18 pacientes | **ningún rasgo cambia**, ni con FDR ni nominal (más cerca: `emo_pos_100` sube en 10 de 13, p 0.069) |
| cuentas sin ninguna palabra | 11 de 90 (4 pacientes, 7 controles): publican solo imagen |

**Veredicto: el estilo contable no lleva señal.** Ni entre personas ni dentro
de la persona. Sumado a que el volumen tampoco cambia (p = 1.00) y a que los
metadatos no separan (0.439), la conclusión de la capa 1 es que **si hay algo,
está en el contenido**, y eso es la capa 2.

Léxico usado en esa corrida: listas v1 hechas a mano. Con `SEL_full.txt` en
`lexicos/` los dos rasgos de emoción se recalculan con el léxico de IPN; el
resto no cambia.

## Para retomar desde otra sesión

1. Leer este README y `resultados_ig/capa1/REPORTE_capa1.md`.
2. Si hay datos nuevos (más pacientes, controles re-extraídos), correr primero
   `ig/control/cerrar_control.py --sin-extraer --caliper 3` y luego
   `correr_capa1.py`. Un minuto cada uno.
3. Para añadir un rasgo: `rasgos.py` (función `rasgos_de_posts`, lista
   `NOMBRES`, y una línea en la autoprueba). Mantener la lista corta: entre
   15 y 30 rasgos para 90 cuentas.
4. Para cambiar un léxico: editar el `.txt` en `lexicos/`; no tocar código.
