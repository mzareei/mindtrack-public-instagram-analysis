# Libro de códigos: contraste intrasujeto MindTrack

**Proyecto** S.807, Fundación Gonzalo Río Arronte. Folio CEIC P000850-Mindtrack-CEIC-CR002.
**Corpus** `corpus_anotacion.csv`, 212 publicaciones de 18 pacientes, ciego.
**Versión** 1.0, 7 sep 2026.

---

## 1. Qué se está midiendo, y por qué así

Cada paciente entró al estudio durante un episodio de riesgo. Sus publicaciones
de los 90 días alrededor de esa fecha se comparan con las suyas propias de un año
antes. La pregunta es si el **lenguaje** cambia, porque ya sabemos que el volumen
no cambia: la prueba de signos pareada sobre el ritmo de publicación dio p = 1.00
(sube en 10 pacientes, baja en 10). Si hay señal, está en lo que dicen, no en
cuánto publican.

Cada persona es su propio control. Eso elimina de golpe edad, sexo, ciudad,
escolaridad, estilo de escritura y tamaño de cuenta, que en un diseño entre
personas habría que emparejar a mano. También significa que **el efecto que
buscamos es pequeño**: no es la diferencia entre una persona en riesgo y otra que
no lo está, es la diferencia entre una persona y ella misma unos meses antes.

## 2. Usted está ciego, y eso es deliberado

El fichero no lleva fecha, ni ventana, ni identificador de paciente, y las filas
van barajadas. No intente deducir de qué periodo es una publicación, y si cree
haberlo deducido, anótelo en `notas` y siga codificando igual.

La razón es directa: si sabe que un post es del periodo de crisis, va a marcar
"desesperanza" con el pulgar en la balanza, y entonces el estudio mediría su
expectativa en lugar del texto. Un resultado así no sobrevive a revisión, y con
razón.

**Advertencia sobre las imágenes.** El corpus incluye la imagen de cada
publicación (columna `imagen`, carpeta `img/`). Hacía falta: la mediana de las
descripciones es de **5 palabras**, y 37 de las 212 no tienen texto ninguno.
Codificar esas sin ver la imagen sería inventar. Pero la imagen puede delatar la
estación del año o un contexto reconocible, así que el ciego es **parcial** y hay
que declararlo así en el artículo. No busque pistas temporales a propósito.

## 3. Unidad de análisis

Una fila = una publicación = **texto e imagen juntos**. Se codifica lo que la
publicación comunica en conjunto, no el texto por separado.

Si no hay texto, codifique la imagen. Si la imagen no carga, codifique el texto y
apúntelo en `notas`.

## 4. Los códigos

Todos son **presencia / ausencia**: `1` si está, `0` si no, vacío si no se puede
juzgar. No hay escalas de intensidad. Con descripciones de cinco palabras, una
escala de cinco puntos da una fiabilidad falsa: dos personas razonables no
distinguen un 3 de un 4 en "Hoy no", pero sí coinciden en si eso expresa
malestar o no.

| Columna | Qué marca | Marque 1 cuando |
|---|---|---|
| `expresion_simbolica` | Sentido indirecto: metáfora, letra de canción, imagen cargada, emoji que sustituye a la frase | El contenido dice algo que no está dicho literalmente, y un lector cercano lo entendería como referido al estado de ánimo de quien publica |
| `desesperanza` | Futuro cerrado o sin sentido | Se expresa que nada va a cambiar, que no vale la pena, que da igual lo que haga |
| `carga_percibida` | Sentirse un peso para otros | Se expresa que estorba, que sin él o ella los demás estarían mejor, que pide perdón por existir |
| `pertenencia` | Pertenencia frustrada, soledad, exclusión | Se expresa estar fuera, no encajar, que nadie está, que sobra en su grupo |
| `dolor_psiquico` | Sufrimiento psicológico nombrado | Se nombra el dolor, el cansancio de sentir, el vacío, el no poder más |
| `atrapamiento` | No hay salida | Se expresa estar encerrado en una situación, sin escapatoria, dando vueltas |
| `orientacion_temporal` | `pas`, `pre`, `fut` o vacío | Escriba la etiqueta, no un 1. Hacia dónde mira el contenido |
| `busqueda_de_apoyo` | Pedir ayuda o contacto | Se pide compañía, se agradece a quien está, se menciona ir a terapia, se dice "escríbanme" |
| `despedida` | Cierre, balance, despedida | Se agradece a la gente como quien se va, se hace recuento, se dice adiós sin motivo visible |
| `confianza_anotador` | `alta`, `media`, `baja` | Su seguridad en toda la fila. Marque `baja` sin culpa: sirve para el análisis de sensibilidad |
| `notas` | Texto libre | Cualquier duda, ambigüedad, o razón por la que dejó algo vacío |

`expresion_simbolica` es la categoría central del proyecto y puede coexistir con
cualquier otra. Un post puede llevar varios códigos a la vez, o ninguno. La
mayoría no llevará ninguno, y eso es normal y esperado: la mayor parte de lo que
publica una persona de veinte años es vida corriente.

## 5. Lo que NO se codifica

- **No diagnostique.** No hay un código de "riesgo suicida" y no debe inferirlo.
- **No interprete la ausencia.** Un post sin texto no es retraimiento; es un post
  sin texto. Se codifica lo que hay.
- **No use el número de "me gusta"** ni los comentarios de otras personas. No
  están en el fichero por eso.
- **No codifique letras de canciones como si fueran del paciente**, salvo en
  `expresion_simbolica`, que es precisamente donde una cita ajena elegida a
  propósito sí cuenta.
- **No busque coherencia entre filas.** Cada fila se juzga sola. Las filas están
  barajadas justamente para que no pueda construir una historia por paciente.

## 6. Casos frontera

Los ejemplos siguientes están **inventados al estilo del corpus**, no copiados de
él, para que este documento pueda circular sin exponer material de pacientes.

| Ejemplo | Decisión |
|---|---|
| "No todos los días salen bien, y está bien 🖤" | `dolor_psiquico` 0, `expresion_simbolica` 1. Nombra un mal día pero lo enmarca como aceptable. No es sufrimiento nombrado. |
| "ya no puedo con esto" | `dolor_psiquico` 1, `atrapamiento` 1. Aunque sea sobre un examen: se codifica lo expresado, no la causa. |
| "gracias a todos por tanto ❤️" sobre una foto de grupo en una graduación | `despedida` 0. El contexto explica el cierre. |
| "gracias a todos por tanto ❤️" sin contexto visible | `despedida` 1, `confianza_anotador` baja. |
| Solo hashtags (`#reel #humor`) | Todo 0. No hay contenido que codificar. |
| Letra de canción triste, sin comentario | `expresion_simbolica` 1. Los demás según lo que diga la letra. |
| Foto de paisaje, sin texto | Normalmente todo 0, salvo que la imagen sea claramente expresiva. |

Cuando dude entre 0 y 1, marque **0** y baje `confianza_anotador`. El sesgo por
defecto debe ir hacia no ver señal donde no la hay, porque el error contrario
infla artificialmente el resultado que el estudio busca.

## 7. Fiabilidad entre anotadores

1. **Entrenamiento**: los dos anotadores codifican las mismas 20 filas (P0001 a
   P0020), comparan, y discuten cada desacuerdo antes de seguir. Esas 20 se
   vuelven a codificar al final y no se usan las versiones de entrenamiento.
2. **Doble codificación**: el 25% del corpus (53 filas) lo codifican los dos, de
   forma independiente. Sortee cuáles con semilla fija y déjela escrita.
3. **Métrica**: kappa de Cohen por categoría. Umbral de trabajo κ ≥ 0.60. Una
   categoría que no lo alcance no se tira: se reporta con su kappa y se excluye
   del contraste principal, o se fusiona con otra.
4. **Reconciliación**: los desacuerdos se resuelven hablando, no promediando. La
   decisión final se apunta con su motivo.
5. Con 212 filas y categorías poco frecuentes, algunos kappas van a salir bajos
   por **prevalencia baja**, no por desacuerdo. Reporte también el porcentaje de
   acuerdo bruto y la prevalencia de cada categoría, o el kappa parecerá peor de
   lo que es.

## 8. Al terminar

Devuelva `corpus_anotacion.csv` con las columnas llenas, sin cambiar la columna
`codigo` ni el orden de las filas. El análisis une por `codigo` con
`clave_anotacion.csv`, que es donde vive la ventana.

**`clave_anotacion.csv` no se entrega a quien anota.** Si lo ha visto, dígalo:
no es un problema si se sabe, es un problema si no se sabe.

## 9. Nota metodológica sobre el tamaño

El corpus son 2,857 palabras en 175 publicaciones con texto: mediana de 5
palabras, y solo 39 publicaciones pasan de 10 palabras. Es poco, y hay que
decirlo en el artículo antes de que lo diga un revisor.

Consecuencias prácticas:

- Con este volumen, un contraste **por publicación** tendrá poca potencia. El
  análisis principal debería agregar **por paciente y ventana** (36 unidades:
  18 pacientes × 2 ventanas) y usar una prueba pareada.
- La validación cruzada va **agrupada por paciente**, siempre. Los cuatro
  pacientes más activos aportan el 68% de las publicaciones del corpus completo;
  sin agrupar, se estaría midiendo a cuatro personas.
- Un resultado nulo aquí es informativo y publicable: diría que la señal
  lingüística en publicaciones públicas de Instagram, dentro de la misma
  persona, es demasiado tenue para este tamaño de muestra. Conviene decidir eso
  **antes** de ver los resultados, y dejarlo escrito.
