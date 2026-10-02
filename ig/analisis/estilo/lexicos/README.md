# Léxicos de la capa 1

Un fichero por lista. Una entrada por línea; `#` comenta; un asterisco final
marca prefijo (`cansad*` casa `cansado`, `cansada`, `cansadísima`); las entradas
con espacios se buscan como frase.

| fichero | qué mide | procedencia |
|---|---|---|
| `primera_persona_sing.txt` | yo/me/mi + verbos de estado en 1ª persona | hecho a mano, sigue a Pennebaker |
| `primera_persona_pl.txt` | nosotros/nos | hecho a mano |
| `otras_personas.txt` | tú/él/ellos | hecho a mano, sin artículos |
| `absolutistas.txt` | nunca/siempre/nada/todo | Al-Mosaiwi & Johnstone (2018), traducido |
| `negaciones.txt` | no/ni/tampoco/sin | hecho a mano |
| `hedges.txt` | quizás/creo/no sé | hecho a mano |
| `muerte_dolor.txt` | morir/dolor/cansad*/adiós | hecho a mano, corto |
| `emocion_negativa.txt` | v1 hecha a mano, español mexicano + inglés frecuente | **respaldo**: si existe `SEL_full.txt` se usa SEL |
| `emocion_positiva.txt` | ídem | ídem |
| `emoji_negativos.txt` / `emoji_positivos.txt` | valencia de emoji | hecho a mano para este grupo de edad |
| `ingles.txt` / `espanol.txt` | palabras funcionales para clasificar idioma | hecho a mano |

## SEL (Spanish Emotion Lexicon), opcional pero recomendado

Sidorov et al. (2012), CIC-IPN, 2,036 palabras con factor de probabilidad
afectiva (PFA) en seis categorías: Alegría, Enojo, Miedo, Repulsión, Sorpresa,
Tristeza. Hecho sobre español de México, que es justo lo que hace falta.

Descarga: <https://www.cic.ipn.mx/~sidorov/SEL_full.txt> (página del autor:
<https://www.cic.ipn.mx/~sidorov/>). Guárdalo **en esta carpeta** con ese
nombre. `rasgos.py` lo detecta solo:

- negativa = Enojo + Miedo + Repulsión + Tristeza con PFA ≥ 0.5
- positiva = Alegría con PFA ≥ 0.5
- Sorpresa no se usa (ambigua)

Si no está, se usan las listas v1 y el reporte lo dice.

Cita: Sidorov G. et al. "Empirical Study of Machine Learning Based Approach for
Opinion Mining in Tweets". MICAI 2012, LNAI 7629, pp. 1-14.
