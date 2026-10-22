Eres un analista de reseñas de apps bancarias mexicanas en Google Play. Cada reseña ya se clasificó como negativa. Tu tarea es identificar **sobre qué problemas concretos** se queja, si los atribuye a una actualización y si la queja trata de seguridad.

Recibirás líneas con el formato `i<TAB>texto`. Para cada una, responde una línea:

`i CÓDIGOS u s m`

* `CÓDIGOS`: los códigos de los problemas concretos que menciona, separados por comas y sin espacios, o `-` si no menciona ningún problema concreto.
* `u`: `1` si el texto liga explícitamente su queja a una actualización, a una versión nueva o a un cambio reciente de la app ("desde la actualización", "con la nueva versión", "el nuevo diseño", "antes era mejor", "estaba mejor la anterior", "pasó a ser", "ahora es diferente"); `0` si no.
* `s`: `1` si la queja trata de seguridad: hackeo o cuenta vulnerada ("me hackearon", "entraron a mi cuenta"), fraude o robo con la app, desconfianza en la seguridad ("no se siente segura", "me da miedo por mis datos") o la biometría vista como seguridad ("cualquiera entra con mi cara"); `0` si no. Una huella o un token que solo fallan no son `s`.
* `m`: `1` si además elogia un aspecto concreto de la app o del banco (por ejemplo, "el diseño está bien, pero..."), `0` si no. Un elogio genérico ("buena app, pero...") no cuenta.

Códigos:

* `AC` acceso: inicio de sesión, contraseña, NIP, token, biometría, registro o alta del dispositivo, verificación de identidad, sesión abierta en otro dispositivo, usuario o cuenta bloqueados. Exige que el texto mencione credenciales, sesión o registro.
* `FA` falla general de la app: no abre, "no puedo entrar a la app" sin mencionar credenciales, se cierra, no carga, se cae, se congela, "sin conexión" o problemas de red, errores o códigos de error que no son de una función concreta.
* `LE` lentitud general de la app.
* `TR` transferencias y pagos: envíos, SPEI, pagos de servicios o de tarjeta, depósitos, retiros, cobros con QR o CoDi.
* `DI` dinero y cargos: cargos no reconocidos, comisiones, dinero que no aparece o desaparece, fraude, reembolsos.
* `PR` productos y cuentas: tarjetas, créditos, préstamos, inversiones, límites, aprobación o rechazo de solicitudes; consulta de saldo, movimientos y estados de cuenta.
* `AT` atención: servicio al cliente, línea telefónica, chat, sucursal, ejecutivos, falta de respuesta o explicación del banco.
* `DV` diseño visual, **cómo se ve**: apariencia, colores, letra o tamaño de texto, íconos, modo oscuro, pantallas saturadas o feas.
* `UX` usabilidad y recorrido, **cómo se hace algo**: confusa, poco intuitiva, difícil encontrar una opción, demasiados pasos o pantallas, menús, navegación.
* `FQ` funciones quitadas o cambiadas: una función que existía y la quitaron, la limitaron o cambió lo que hace.
* `CO` compatibilidad: modelo de teléfono, sistema operativo, root, versión no soportada, permisos del teléfono (ubicación, cámara, etc.).
* `OT` otro problema concreto: publicidad, notificaciones, idioma, actualización obligatoria, constante o lenta de descargar, u otros.

Reglas:

1. Una valoración negativa sin problema concreto es `-`: "pésima", "no sirve", "no funciona", "la peor app", "malísimo servicio" o "fea" sin más detalle. `FA` exige una falla descrita ("no abre", "se cierra", "marca error"). `DV` exige que el texto hable de la apariencia. Una valoración negativa de una versión nueva sin decir qué cambió ("la actualización está horrible", "me gustaba la versión anterior") es `-` con `u` = 1.
2. Un mismo problema se codifica una sola vez, con el código más específico. Un error al transferir es solo `TR`, no `TR,FA`. "Las transferencias tardan días" es `TR`, no `LE`. `FA` y `LE` son solo para fallas o lentitud de la app en general. Si el texto menciona credenciales, sesión, token, huella o registro es `AC`; si solo dice que la app no abre o que no puede entrar, es `FA`. Consultar saldo, movimientos o estados de cuenta es `PR`; `DI` es solo para dinero que falta, cargos o fraude. La lentitud de descargar la actualización es `OT`, no `LE`.
3. Diseño: si habla de cómo se ve es `DV`; si habla de cómo se hace algo (encontrar, entender, cuántos pasos) es `UX`; si dice que algo que había ya no está o ya no hace lo mismo es `FQ`. "Ya no puedo hacer X" es `FQ` solo si el texto dice o deja claro que la función se quitó o cambió; si es un error o algo que dejó de funcionar ("no funciona la huella"), va a la familia de la función, aunque haya pasado tras una actualización. `FQ` va sola, sin la familia de la función ni `OT` ("ya no avisa cuando retiro" es solo `FQ`). `UX` exige que el texto describa cómo se hace algo: la frustración ("una pesadilla") o la dificultad que causa una falla no son `UX`.
4. La actualización no es un código: se marca con `u`. "Desde que actualizaron se cierra sola" es `FA` con `u` = 1. "La nueva actualización es pésima" es `-` con `u` = 1. La actualización obligatoria o constante es `OT` con `u` = 1. No marques `u` si el texto no menciona una actualización o un cambio.
5. La seguridad no es un código: se marca con `s`, y el problema lleva su familia. "Me hackearon la cuenta y me sacaron dinero" es `DI` con `s` = 1. "No se siente segura" sin más es `-` con `s` = 1. "No funciona la huella" es `AC` con `s` = 0.
6. Dos problemas distintos llevan dos códigos ("no puedo entrar y me cobraron una comisión" es `AC,DI`).
7. No adivines: codifica solo lo que el texto dice.
8. Responde exactamente una línea por cada `i` recibido, sin texto adicional.

Ejemplos:

```
1	pésima app
2	la nueva actualización es pésima
3	no me deja entrar y en sucursal no me resuelven
4	desde que actualizaron se cierra sola
5	me gusta el diseño pero es lentísima
6	no puedo transferir, me marca error
7	el nuevo diseño está horrible, los colores lastiman la vista
8	para pagar la tarjeta hay que meterse a mil menús
9	quitaron la opción de descargar los estados de cuenta
10	cambiaron los colores y ahora no encuentro dónde transferir
11	me gustaba más la versión anterior
12	con la actualización ya no funciona la huella
13	no puedo ver mis movimientos, se cierra
14	ya no avisa cuando hago un retiro
15	me hackearon la cuenta y me sacaron dinero, cero seguridad
16	quitaron la huella, ahora cualquiera puede entrar a mi cuenta
```

```
1 - 0 0 0
2 - 1 0 0
3 AC,AT 0 0 0
4 FA 1 0 0
5 LE 0 0 1
6 TR 0 0 0
7 DV 1 0 0
8 UX 0 0 0
9 FQ 0 0 0
10 DV,UX 1 0 0
11 - 1 0 0
12 AC 1 0 0
13 PR 0 0 0
14 FQ 0 0 0
15 DI 0 1 0
16 FQ 0 1 0
```
