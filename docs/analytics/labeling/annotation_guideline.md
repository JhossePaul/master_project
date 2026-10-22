# Guía de anotación de sentimiento (EPIC-5, feature 5.3)

> **Estado (2026-10-19): vigente,** `v2.2`. Las versiones anteriores solo se conservan en el registro de cambios (sección 6). Índice: [`README.md`](../README.md).

* **Versión:** `annotation_guideline_v2.2` (2026-10-19). Agrega a la regla 2 las quejas por decisiones del banco que no se explican, como el anotador ya las etiquetó en `gold_v1` ([reporte](gold_v1_report.md), sección 4). `v2.1` agregó el campo `nombre_persona`. `v2` sustituyó a `v1` (y esta a `v0`) tras la calibración y la validación de la primera ronda del oro ([reporte](gold_v0_report.md)); los cambios están en el registro al final. Cualquier cambio posterior crea una versión nueva, y cada etiqueta registra la versión con la que se hizo.
* **Aplica a:** el conjunto de oro (humano) y el de plata (Gemini Flash). El prompt de Gemini es una versión condensada de esta guía y se versiona junto con ella.
* **Esquema decidido (2026-10-17):**
  * tres clases de sentimiento (`NEG`, `NEU`, `POS`), compatibles con `SentimentLabel` de `voc-common`;
  * una marca aparte `NO_EVALUABLE`;
  * una marca `MENCIONA_FALLA` para los tópicos;
  * una marca de duda.

## 1. Qué se etiqueta

**El sentimiento que expresa el texto sobre la experiencia con la app o con el banco.** No se etiqueta la calificación.

* **Las estrellas no se muestran al anotador.** Son la etiqueta ruidosa que queremos contrastar; verlas ancla la decisión.
* **Se lee `texto_sanitizado`** (conserva mayúsculas y signos). Los tokens como `[PERSON_NAME]` o `[PHONE_NUMBER]` se ignoran: reemplazan datos personales y no aportan sentimiento.
* **Se etiqueta lo que dice el texto**, no lo que el anotador supone que le pasó al usuario.

## 2. Campos por reseña

| Campo | Valores | Obligatorio |
| :--- | :--- | :---: |
| `sentimiento` | `NEG`, `NEU`, `POS` (vacío si `no_evaluable`) | Sí, salvo `NO_EVALUABLE` |
| `no_evaluable` | sí / no | Sí |
| `menciona_falla` | sí / no: describe un problema concreto de funcionamiento o de servicio | Sí |
| `duda` | sí / no: la decisión fue difícil | Sí |
| `nombre_persona` | sí / no: el texto contiene el nombre propio de una persona (nombre o apellido, del autor o de otra persona). No cuentan los tokens de sanitización (`[PERSON_NAME]`) ni los nombres de bancos, apps o comercios | Sí, desde `v2.1` |

`nombre_persona` mide la tasa real de nombres que la regex de sanitización no detecta (acción 1 de F-01 en la [matriz FMEA ética](../../governance/ethical_fmea_matrix.md)). La tasa se estima solo con el bloque aleatorio; no cambia la etiqueta de sentimiento.

`menciona_falla` alimenta la evaluación de tópicos (5.5) y de detección de incidencias. Es independiente del sentimiento: una reseña puede ser `POS` y mencionar una falla resuelta.

## 3. Reglas de decisión

Se aplican en este orden:

1. **`NO_EVALUABLE`** si no se puede saber qué opina el usuario:
   * texto ininteligible o sin relación con la app o el banco (spam, otra app);
   * solo emojis o símbolos ambiguos;
   * en un idioma que el anotador no entiende.

   Los emojis con valencia clara (👍, ❤️, 😡) **sí** son evaluables. También las palabras sueltas con valencia ("excelente", "pésima", "complicado"): se etiquetan por esa valencia aunque falte contexto.
2. **Falla o queja concreta ⇒ `NEG`**, aunque haya elogios y **aunque la queja sea menor u ocasional**. El foco del proyecto son las incidencias: "buena app pero no puedo transferir" y "excelente, solo que a veces tarda" son `NEG`. Cuentan como queja concreta:
   * errores, cierres y bloqueos (incluidos códigos como `ref: 3702`);
   * cobros o comisiones indebidos, dinero que no aparece;
   * lentitud, aunque sea ocasional ("a veces tarda", "un poco lenta", "cada vez más pesada");
   * mala atención;
   * cambios de diseño que empeoran el uso;
   * falta de disponibilidad (por ejemplo, en un sistema operativo o dispositivo);
   * **decisiones del banco que no se explican y molestan al cliente** (desde `v2.2`): requisitos obligatorios como activar la ubicación, límites de monto, rechazos o bloqueos sin motivo, cambios de condiciones sin aviso. Cuentan aunque la medida venga de la regulación o sea por seguridad: la queja es la falta de claridad o de comunicación, que es una falla de servicio. Llevan `menciona_falla` = sí. Si el texto solo describe la medida sin molestia ("piden la ubicación para entrar"), aplica la regla 5.
3. **Sugerencia o deseo sin falla ⇒ se decide por el tono general.** "Excelente, ojalá agreguen pagos con QR" es `POS`. "No sirve para nada, deberían poner X" es `NEG` (la regla 2 ya lo cubre).
4. **`POS`** cuando hay valoración favorable sin queja concreta: "excelente", "muy fácil de usar", "me salvó la vida". Un aprobatorio breve como "bien" o "muy bien" también es `POS`.
5. **`NEU`** en los demás casos con contenido evaluable:
   * descripciones sin valoración ("la uso para pagar la luz");
   * preguntas;
   * acuses sin valoración clara ("ok");
   * valoraciones intermedias explícitas **sin queja concreta** ("regular", "más o menos"). Si la valoración intermedia viene con una queja concreta, aplica la regla 2.
6. **Sarcasmo e ironía:** se etiqueta el significado intencionado ("qué maravilla, otra vez sin servicio" es `NEG`).
7. **Queja sobre el banco y no sobre la app** (sucursal, ejecutivo, política de crédito): igual se etiqueta. El proyecto mide la voz del cliente sobre la experiencia completa.
8. **Si dudas entre dos clases**, elige la que mejor describe lo que leería un responsable de producto y marca `duda = sí`. No uses `NEU` como refugio cuando hay una valoración clara.

## 4. Ejemplos

Los ejemplos son **sintéticos** (redactados para la guía, no copiados del corpus), para no exponer texto de usuarios.

| Texto | sentimiento | no_evaluable | menciona_falla | Regla |
| :--- | :---: | :---: | :---: | :--- |
| excelente | POS | no | no | 4 |
| 👍 | POS | no | no | 1 y 4 |
| muy buena app pero desde la actualización no me deja entrar | NEG | no | sí | 2 |
| me bloquearon la cuenta ref: 3702 y nadie resuelve | NEG | no | sí | 2 |
| la uso para transferir a mi familia | NEU | no | no | 5 |
| regular, a veces se tarda | NEG | no | sí | 2 (queja concreta aunque sea ocasional; en `v0` era NEU) |
| excelente, solo que a veces se cierra | NEG | no | sí | 2 |
| más o menos | NEU | no | no | 5 |
| bien | POS | no | no | 4 (aprobatorio breve) |
| ok | NEU | no | no | 5 (acuse sin valoración clara) |
| complicado | NEG | no | no | 1 y 2 (palabra suelta con valencia) |
| qué maravilla, tercer día sin poder pagar | NEG | no | sí | 6 |
| ojalá pongan modo oscuro, por lo demás perfecta | POS | no | no | 3 |
| asdfgh | — | sí | no | 1 |
| el ejecutivo de la sucursal me trató pésimo | NEG | no | sí | 7 |
| me obligan a activar la ubicación y nunca dicen para qué | NEG | no | sí | 2 (decisión del banco sin explicar, `v2.2`) |
| no me dejan transferir más de cierto monto y no sé por qué | NEG | no | sí | 2 (`v2.2`) |
| ya corrigieron el error de las transferencias, ahora va bien | POS | no | sí | 4 (falla resuelta) |

## 5. Procedimiento

1. **Calibración:** 30 reseñas que el autor etiqueta y revisa contra esta guía. Las ambigüedades se resuelven ampliando las reglas antes del piloto.
2. **Bloque a ciegas (150–200 reseñas):** la herramienta oculta la propuesta de Gemini. Mide el acuerdo humano–Gemini sin anclaje.
3. **Bloque asistido (resto del oro):** la herramienta muestra la propuesta de Gemini, que se acepta o se corrige. El efecto de anclaje se estima comparando con el bloque a ciegas.
   * **Desde `v1`:** la primera ronda midió un anclaje fuerte (+7 puntos de acuerdo con la propuesta). Las rondas siguientes, incluido el bloque dirigido, se anotan a ciegas.
4. **Re-anotación:** 5 % de las reseñas, repetidas sin aviso días después, para medir la consistencia del propio anotador.
5. La herramienta registra por reseña el tiempo empleado, el modo (ciego o asistido), la versión de la guía y la fecha.

## 6. Registro de cambios

| Versión | Fecha | Cambio |
| :--- | :--- | :--- |
| `v0` | 2026-10-17 | Primera versión: tres clases, `NO_EVALUABLE`, `MENCIONA_FALLA`, `duda`; reglas 1–8 |
| `v1` | 2026-10-18 | Regla 2 amplia: cualquier queja concreta, incluida la lentitud ocasional o la falta de disponibilidad, es `NEG`. Las palabras sueltas con valencia son evaluables. "regular, a veces se tarda" pasa a `NEG`. Origen: en la calibración el anotador aplicó la lectura amplia en 9 de 10 casos fronterizos |
| `v2` | 2026-10-18 | "bien" (y "muy bien") es `POS`; "ok" es `NEU`, un acuse sin valoración clara. Origen: 3 de 11 desacuerdos a ciegas con `prompt_v2` eran aprobatorios breves |
| `v2.1` | 2026-10-19 | Campo `nombre_persona` (F-01). Las reglas de sentimiento no cambian |
| `v2.2` | 2026-10-19 | Regla 2: las decisiones del banco que no se explican y molestan al cliente (ubicación obligatoria, límites, rechazos o bloqueos sin motivo) son queja concreta y llevan `menciona_falla`, aunque vengan de la regulación. Origen: 11 notas del anotador en `gold_v1`, que ya las etiquetó así (10 `NEG` con falla); Gemini marcó falla solo en 5. No cambia ninguna etiqueta existente |
