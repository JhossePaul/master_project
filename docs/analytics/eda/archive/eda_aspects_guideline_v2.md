# Guía de codificación de aspectos de las reseñas negativas (EPIC-5, 5.2)

> **Estado (2026-10-20): vigente y congelada, `aspects_guideline_v2`.** Se reabrió 5.2 a pedido de 5.5 ([plan de tópicos](../../topics/topics_design.md), sección 6). Se calibró en tres rondas (sección 7) y no cambia mientras se codifica la muestra. Solo cambia por la regla de decisión (sección 6). La siguen el prompt [`aspects_v2`](../../../../experiments/analytics/src/voc_analytics/eda/prompts/aspects_v2.md) y la app [`aspects_v2_app.py`](../../../../experiments/analytics/src/voc_analytics/eda/aspects_v2_app.py). La versión anterior está congelada en [`eda_aspects_guideline_v1.md`](eda_aspects_guideline_v1.md). Índice: [`README.md`](../../README.md).
> * **Cambios contra `v1`:**
>   * `DS` (κ 0.39) se parte en `DV` (diseño visual), `UX` (usabilidad y recorrido) y `FQ` (funciones quitadas o cambiadas);
>   * la regla 3 de `v1` (un problema atribuido a una actualización suma `DS`) se sustituye por la marca ortogonal `u`, que no es familia y no cuenta para el multi-aspecto.
> * **Ronda 1 de calibración** (30 textos; acuerdo exacto autor–Gemini del 33 %):
>   * `AC` solo con credenciales o sesión;
>   * `PR` incluye las consultas de cuenta;
>   * los permisos van a `CO`;
>   * `UX` no es frustración;
>   * `FQ` va sola y no cubre fallas;
>   * una versión nueva valorada sin decir qué cambió lleva solo `u`;
>   * se amplían las expresiones de `u`;
>   * se agrega la marca de seguridad `s`, pedida por el autor.
> * **Ronda 2** (20 textos; acuerdo exacto del 40 %; κ de `u` 0.70 y de `s` 0.61):
>   * una función que falta o tiene restricciones va a su dominio;
>   * `FQ` exige lenguaje explícito de que se quitó;
>   * la palabra "diseño" no implica `DV`;
>   * los trámites de la cuenta van a `PR`;
>   * `s` es solo para quejas.
> * **Ronda 3** (30 textos; acuerdo exacto del 46.7 %; κ de `u` 0.83, de `s` 0.78 y de `FQ` 1.0):
>   * `UX` no incluye la fricción de una operación del dominio (decisión del autor);
>   * al iniciar sesión, si la app se congela es `FA` y si rechaza o no manda el código es `AC`;
>   * las consecuencias no se codifican;
>   * no poder descargar o instalar la app va a `CO`;
>   * `s` incluye la objeción de privacidad (decisión del autor).
> * **`OT` deja de ser caja de sastre** (decisión del autor, 2026-10-20). Publicidad, notificaciones, idioma, actualización forzosa, recursos del teléfono, cajeros y puntos pasan a su familia (`UX`, `CO`, `TR`, `PR`). `OT` queda como "sin familia": solo se usa tras descartar todas las demás, y su prevalencia es la alarma de un tema nuevo (sección 5).
> * Si la regla de decisión (sección 6) no separa `DV` de `UX`, o `FQ` de las demás, se fusionan y la guía queda en `v2` con el código fusionado.

## 1. Qué se codifica

Cada reseña ya es negativa (`NEG` en la plata). La pregunta es **sobre qué problemas concretos se queja**. La respuesta tiene cuatro partes:

* un conjunto de familias, que puede estar vacío;
* la marca de actualización `u`;
* la marca de seguridad `s`;
* la marca de elogio.

**Problema concreto:** el texto dice qué falla, qué no puede hacer o qué le molesta ("no me deja entrar", "me cobraron una comisión", "tarda mucho en cargar").

**Sin problema concreto:** el texto solo valora mal, sin decir qué falla. Se codifica **sin familias**. Es una respuesta válida y frecuente en las reseñas cortas.

## 2. Familias

| Código | Familia | Incluye | No incluye (va a) |
| :---: | :--- | :--- | :--- |
| `AC` | Acceso | Inicio de sesión, contraseña, NIP, token, biometría, registro o alta del dispositivo, verificación de identidad, sesión abierta en otro dispositivo, usuario o cuenta bloqueados. Exige que el texto mencione credenciales, sesión o registro, y que el problema sea con ellos: rechaza, bloquea, no manda el código, pide verificar | "No abre" o "no puedo entrar a la app" sin credenciales; la app que se congela o no carga al iniciar sesión (`FA`) |
| `FA` | Falla general de la app | No abre, "no puedo entrar a la app" sin mencionar credenciales, se cierra, no carga, se cae, se congela, "sin conexión" o problemas de red, errores que no son de una función concreta | El error de una función concreta (la familia de la función) |
| `LE` | Lentitud general | La app es lenta o pesada en general | La lentitud de una operación ("las transferencias tardan": `TR`) |
| `TR` | Transferencias y pagos | Envíos, SPEI, pagos de servicios o de tarjeta, depósitos, retiros, cajeros, QR, CoDi, contactos y cuentas guardadas, comprobantes, horarios y restricciones de las operaciones | El dinero que no llega o desaparece (`DI`) |
| `DI` | Dinero y cargos | Cargos no reconocidos, comisiones, dinero que no aparece o desaparece, fraude, reembolsos | La consulta de saldo o movimientos que no carga (`PR`) |
| `PR` | Productos y cuentas | Tarjetas, créditos, préstamos, inversiones, apartados o metas, puntos y recompensas, límites, solicitudes; consulta de saldo, movimientos y estados de cuenta; trámites de la cuenta (actualizar datos) | |
| `AT` | Atención | Servicio al cliente, línea telefónica, chat, sucursal, ejecutivos, falta de respuesta o explicación del banco | |
| `DV` | Diseño visual | **Cómo se ve:** apariencia, colores, letra o tamaño de texto, íconos, modo oscuro, pantallas saturadas o feas | "Diseño poco amigable" o "poco intuitivo" (`UX`); "fea" sin más (sin familias) |
| `UX` | Usabilidad y recorrido | **Cómo se hace algo y lo que interrumpe el uso:** confusa, poco intuitiva, difícil encontrar una opción, demasiados pasos, menús, navegación, idioma, publicidad o promociones dentro de la app, notificaciones excesivas, actualización forzosa o constante, obligar a usar otra app | La frustración ("una pesadilla"); la dificultad causada por una falla; una función que no existe; la fricción o molestia de una operación del dominio, como no poder guardar tarjetas o que los movimientos tarden en reflejarse (su dominio) |
| `FQ` | Funciones quitadas o cambiadas | Una función que **existía** y el texto dice explícitamente que la quitaron, eliminaron o cambió ("quitaron los estados de cuenta", "ya no está la opción de...") | "Ya no me permite..." sin decir que la quitaron (su dominio); algo que dejó de funcionar (su dominio) |
| `CO` | Compatibilidad y recursos del teléfono | Modelo de teléfono, sistema operativo, root, versión no soportada, permisos (ubicación, cámara), espacio, batería, consumo de datos, no poder descargar o instalar la app | |
| `OT` | Sin familia | Un problema concreto que no cabe en **ninguna** familia, después de descartarlas todas | Cualquier tema que ya tenga familia |

## 3. Reglas

1. **Sin problema concreto → sin familias.**
   * "Pésima", "no sirve", "no funciona", "la peor app", "malísimo servicio" o "fea" sin más detalle no llevan códigos.
   * `FA` exige una falla descrita: "no abre", "se cierra", "marca error".
   * `DV` exige que el texto hable de la apariencia: "se ve fea", "los colores", "la letra".
   * Una valoración negativa de una versión nueva sin decir qué cambió ("la actualización está horrible", "me gustaba la versión anterior") no lleva familias; solo `u` = 1 (regla 4).
2. **Un problema, una familia, la más específica.**
   * Un error al transferir es solo `TR`, no `TR` + `FA`.
   * "Las transferencias tardan días" es `TR`, no `LE`.
   * El saldo movido que no aparece es solo `DI`, no `DI` + `PR` + `TR`.
   * `FA` y `LE` son solo para fallas o lentitud de la app en general.
   * **`AC` o `FA`:** si el problema es con credenciales, sesión, token, huella o registro (rechaza, bloquea, no manda el código, pide verificar), es `AC`; si solo dice que la app no abre o que no puede entrar, o si se congela o no carga al iniciar sesión, es `FA`.
   * **Las consecuencias no se codifican:** "no puedo descargar la app, así que no puedo activar mi tarjeta" es solo `CO`, no `CO` + `PR`.
   * Consultar saldo, movimientos o estados de cuenta es `PR`. `DI` es solo para dinero que falta, cargos o fraude.
   * **Una función que no existe o tiene restricciones** ("no se pueden guardar CLABEs", "no deja transferir en días inhábiles", "no puedo eliminar contactos") va a la familia de su dominio (`TR`, `PR`), no a `UX`.
3. **Diseño: la frontera entre `DV`, `UX` y `FQ`.**
   * **¿Habla de cómo se ve?** → `DV`.
   * **¿Habla de cómo se hace algo** (encontrar, entender, cuántos pasos) **o de algo que interrumpe el uso** (publicidad, notificaciones, actualización forzosa)? → `UX`.
   * **¿Dice explícitamente que algo que había lo quitaron, eliminaron o cambió?** → `FQ`.
   * Si una queja tiene dos de estos problemas, lleva las dos familias ("cambiaron los colores y ahora no encuentro dónde transferir" es `DV` + `UX`).
   * La palabra "diseño" no basta para `DV`: "el diseño no es amigable" es `UX`.
   * `FQ` exige lenguaje explícito ("quitaron", "eliminaron", "ya no está la opción"). "Ya no me permite hacer transferencias rápidas" sin eso va a `TR`. Algo que dejó de funcionar ("no funciona la huella") va a su familia, aunque haya pasado tras una actualización. "Ahora es difícil ver el saldo" es `UX` con `u`.
   * `FQ` va sola: no se le suma la familia de la función. "Quitaron el aviso cuando retiro" es solo `FQ`.
   * `UX` exige que el texto describa cómo se hace algo o qué interrumpe el uso. La frustración ("una pesadilla", "un dolor de cabeza") o la dificultad que causa una falla no son `UX`.
   * **La fricción de una operación no es `UX`:** "no me deja guardar tarjetas", "los movimientos tardan en reflejarse" o "no me llega el código" van solo a su dominio (`TR`, `PR`, `AC`), sin sumar `UX`.
4. **Marca `u`: problema atribuido a una actualización o a un cambio de versión.**
   * Se marca `u` = 1 si el texto liga explícitamente su queja a una actualización, a una versión nueva o a un cambio reciente de la app ("desde la actualización", "con la nueva versión", "el nuevo diseño", "antes era mejor", "estaba mejor la anterior", "era buena, pero ahora", "pasó a ser", "ahora es diferente").
   * `u` no es familia: "desde que actualizaron se cierra sola" es `FA` con `u` = 1, **un solo aspecto**.
   * `u` también puede ir sin familias: "la nueva actualización es pésima" no dice qué falla, así que no lleva familias pero sí `u` = 1.
   * No se supone: "se cierra sola" sin mención de una actualización es `u` = 0.
   * La actualización **forzosa o constante** ("me obliga a actualizar cada semana") es `UX` con `u` = 1.
5. **Marca `s`: la queja trata de seguridad.**
   * Se marca `s` = 1 si el texto **se queja** de:
     * hackeo o cuenta vulnerada ("me hackearon", "entraron a mi cuenta");
     * fraude o robo con la app;
     * desconfianza en la seguridad ("no se siente segura", "me da miedo por mis datos");
     * la biometría vista como seguridad ("cualquiera entra con mi cara");
     * privacidad: objeta que le exijan biometría o datos personales ("me obligan a dar reconocimiento facial, ¿qué ley lo exige?").
   * `s` no es familia: el problema lleva la suya. "Me hackearon la cuenta y me sacaron dinero" es `DI` con `s` = 1. "Quitaron la huella, ahora cualquiera puede entrar" es `FQ` con `s` = 1.
   * Puede ir sin familias: "no se siente segura" es solo `s` = 1.
   * Una huella, un token o un reconocimiento facial que solo fallan no son `s`: "no funciona la huella" es `AC` con `s` = 0.
   * Un elogio a la seguridad ("segura, aunque lenta") no es `s`; si es concreto, es elogio.
6. **`OT` es el último recurso.** Solo se usa si el problema concreto no cabe en ninguna familia, después de revisarlas todas. No se usa para lo que es difícil de decidir.
7. **Problemas distintos → una familia por cada uno.** "No puedo entrar y me cobraron una comisión" es `AC` + `DI`.
8. **Solo lo que el texto dice.** No se infiere la causa ni el problema.
9. **Elogio concreto:** se marca si la queja además elogia un aspecto concreto ("el diseño está bien, pero se cierra"). "Buena app, pero..." no cuenta.

## 4. Ejemplos sintéticos

| Texto | Familias | `u` | `s` | Elogio |
| :--- | :--- | :---: | :---: | :---: |
| "pésima app" | (ninguna) | 0 | 0 | 0 |
| "la nueva actualización es pésima" | (ninguna) | 1 | 0 | 0 |
| "me gustaba más la versión anterior" | (ninguna) | 1 | 0 | 0 |
| "no abre, se queda en la pantalla de inicio" | `FA` | 0 | 0 | 0 |
| "no me deja abrir la app" | `FA` | 0 | 0 | 0 |
| "desde que actualizaron se cierra sola" | `FA` | 1 | 0 | 0 |
| "con la nueva versión no puedo entrar con mi contraseña" | `AC` | 1 | 0 | 0 |
| "con la actualización ya no funciona la huella" | `AC` | 1 | 0 | 0 |
| "ya no puedo transferir, me marca error" | `TR` | 0 | 0 | 0 |
| "no se pueden guardar cuentas para transferir" | `TR` | 0 | 0 | 0 |
| "el cajero no me dio el dinero y sí me lo descontaron" | `DI` | 0 | 0 | 0 |
| "no puedo ver mis movimientos, se cierra" | `PR` | 0 | 0 | 0 |
| "no me deja canjear mis puntos" | `PR` | 0 | 0 | 0 |
| "el nuevo diseño está horrible, los colores lastiman la vista" | `DV` | 1 | 0 | 0 |
| "la letra es muy chiquita y no se lee" | `DV` | 0 | 0 | 0 |
| "la nueva versión es muy confusa, antes era mejor" | `UX` | 1 | 0 | 0 |
| "para pagar la tarjeta hay que meterse a mil menús" | `UX` | 0 | 0 | 0 |
| "cada que abro me salen promociones que no puedo quitar" | `UX` | 0 | 0 | 0 |
| "me obliga a actualizar cada semana" | `UX` | 1 | 0 | 0 |
| "quitaron la opción de descargar los estados de cuenta" | `FQ` | 0 | 0 | 0 |
| "actualizaron y eliminaron el retiro sin tarjeta" | `FQ` | 1 | 0 | 0 |
| "quitaron el aviso cuando hago un retiro" | `FQ` | 0 | 0 | 0 |
| "pide permiso de ubicación y sin eso no deja operar" | `CO` | 0 | 0 | 0 |
| "ocupa demasiado espacio en el teléfono" | `CO` | 0 | 0 | 0 |
| "no me deja descargar la app y no puedo activar mi tarjeta" | `CO` | 0 | 0 | 0 |
| "no me deja guardar las cuentas a las que transfiero" | `TR` | 0 | 0 | 0 |
| "al iniciar sesión se queda en la pantalla de carga" | `FA` | 0 | 0 | 0 |
| "me obligan a registrar mi cara, ¿con qué derecho?" | `AC` | 0 | 1 | 0 |
| "me hackearon la cuenta y me sacaron dinero" | `DI` | 0 | 1 | 0 |
| "quitaron la huella, ahora cualquiera puede entrar" | `FQ` | 0 | 1 | 0 |
| "no se siente segura" | (ninguna) | 0 | 1 | 0 |
| "me gusta el diseño pero es lentísima" | `LE` | 0 | 0 | 1 |
| "cambiaron los colores y ahora no encuentro dónde transferir" | `DV`, `UX` | 1 | 0 | 0 |

## 5. Medidas derivadas

* **Multi-aspecto:** una reseña lo es si tiene dos o más **familias**; `u` y `s` no cuentan. La proporción se reporta sobre las filas `NEG` elegibles y por largo, porque depende mucho del número de palabras. En `v1` la regla 3 sumaba `DS` a cualquier problema atribuido a una actualización, así que el 32–44 % de `v1` puede estar inflado; `v2` lo recalcula.
* **Atribución a actualizaciones:** proporción con `u` = 1, por banco y periodo. Es la señal que 5.5 cruza con las versiones.
* **Seguridad:** proporción con `s` = 1, por banco y periodo.
* **Alarma de tema nuevo:** proporción con `OT`, por banco y periodo. Con esta guía debe ser baja (en `v1`, con un `OT` más amplio, era del 3 %). Si crece, o aparece un tema recurrente dentro de `OT`, se agrega una familia en una versión nueva de la guía.

## 6. Regla de decisión, fijada antes de codificar

**`DV` y `UX` quedan separados si se cumplen las cuatro condiciones, en cada uno de los dos:**

| Condición | Umbral | Dónde se mide |
| :--- | :---: | :--- |
| κ intra-autor (recodificación a ciegas tras una semana o más) | ≥ 0.70 | 50 textos de la muestra |
| κ autor–Gemini por código | ≥ 0.60 | Muestra de unos 300 textos |
| Confusión `DV`↔`UX` | < 20 % de sus desacuerdos | Muestra de unos 300 textos |
| Prevalencia | ≥ 2 % de las negativas | Gemini sobre las 1 500 extracciones representativas |

**Desviación aprobada por el autor (2026-10-20):** la recodificación intra-autor se hace con al menos **24 horas** de distancia, no una semana, por el plazo del proyecto. El κ intra-autor resultante es optimista, porque el autor recuerda parte de sus respuestas. Se reporta con los días reales entre codificaciones y el umbral de 0.70 no cambia.

**Desacuerdos de un código** son los textos en que el autor y Gemini difieren en ese código. **Confusión `DV`↔`UX`** es la parte de esos desacuerdos en que uno puso `DV` sin `UX` y el otro `UX` sin `DV`.

**Si falla alguna condición, `DV` y `UX` se fusionan en `DU`** y se vuelve a medir el κ autor–Gemini del código fusionado, que debe ser ≥ 0.60. El reporte dice si la fusión fue por prevalencia o por falta de distinción (κ o confusión).

**El mismo criterio vale para `FQ`.** Su confusión se mide contra `UX` y `FA`, que son las familias con las que se parece. Si falla, `FQ` se fusiona con `UX`.

**`u` y `s` no entran en la regla.** Su κ se reporta, y 5.5 solo usa cada marca como señal si su κ autor–Gemini es ≥ 0.60.

## 7. Proceso

1. **Calibración.**
   * **Ronda 1, hecha (2026-10-20):** 30 textos de diseño; acuerdo exacto del 33 %.
   * **Ronda 2, hecha (2026-10-20):** 20 textos (14 de diseño y 6 de seguridad); acuerdo exacto del 40 %.
   * **Ronda 3, hecha (2026-10-20):** 30 textos (16 de diseño, 8 de lo que antes caía en `OT` y 6 de seguridad); acuerdo exacto del 46.7 %. Gemini no usó `OT` en ninguno.
   * Con eso la guía y el prompt quedaron en `v2`. El acuerdo exacto subió en cada ronda (33 %, 40 %, 46.7 %). El desacuerdo que quedaba en `UX` era de definición, y el autor lo resolvió.
   * Los ajustes de cada ronda están en el estado, al inicio. Los prompts que vio Gemini en cada ronda están congelados en `aspects_v2_r1`, `aspects_v2_r2` y `aspects_v2_r3`.
2. **Muestra de unos 300 textos.**
   * Unos 150 enriquecidos con casos de diseño: textos con `DS` en `aspects_v1` según Gemini o el autor, o con palabras clave de diseño.
   * Unos 150 aleatorios entre las negativas, tomados de las extracciones representativas en su orden.
   * El autor los codifica a ciegas y Gemini con `aspects_v2`.
3. **Recodificación intra-autor** de 50 textos de la muestra, mitad enriquecidos y mitad aleatorios, a ciegas, al menos 24 horas después (`recode --min-dias 1`). La regla original pedía una semana; ver la desviación en la sección 6.
4. **Gemini sobre las 1 500 extracciones representativas** de `v1`: prevalencias, multi-aspecto recalculado y proporción con `u`, `s` y `OT`.
5. **Regla de decisión** (sección 6) y publicación de `aspects_v2_metrics.json`.

Los κ de la muestra se reportan sobre los 300 y aparte sobre la mitad aleatoria, porque la parte enriquecida sobrerrepresenta los casos de diseño. Las prevalencias salen solo de las extracciones representativas.
