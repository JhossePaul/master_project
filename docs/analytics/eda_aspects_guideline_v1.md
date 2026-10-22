# Guía de codificación de aspectos de las reseñas negativas (EPIC-5, 5.2)

> **Estado (2026-10-20): congelada, `aspects_guideline_v1`; la sustituye la [guía `v2`](eda_aspects_guideline.md).** Se conserva porque la siguen el prompt [`aspects_v1`](../../experiments/analytics/src/voc_analytics/eda/prompts/aspects_v1.md), la app [`aspects_app.py`](../../experiments/analytics/src/voc_analytics/eda/aspects_app.py) y las cifras de la sección 5.2 del [reporte del EDA](eda_report.md). Índice: [`README.md`](README.md).
> * **Cambios contra `v0`** (el prompt `aspects_v0`, sin guía escrita): la opción "sin problema concreto" es explícita y tiene ejemplos (en `v0` el autor no sabía que existía y codificó esos casos como `FA`), y un problema atribuido a una actualización suma `DS` (regla 3).

## 1. Qué se codifica

Cada reseña ya es negativa (`NEG` en la plata). La pregunta es **sobre qué problemas concretos se queja**. La respuesta es un conjunto de familias (puede estar vacío) y una marca de elogio.

* **Problema concreto:** el texto dice qué falla, qué no puede hacer o qué le molesta ("no me deja entrar", "me cobraron una comisión", "tarda mucho en cargar").
* **Sin problema concreto:** el texto solo valora mal, sin decir qué falla. Se codifica **sin familias**. Es una respuesta válida y frecuente en las reseñas cortas.

## 2. Familias

| Código | Familia | Incluye |
| :---: | :--- | :--- |
| `AC` | Acceso | Inicio de sesión, contraseña, NIP, token, biometría, registro o alta, verificación de identidad, usuario o cuenta bloqueados |
| `FA` | Falla general de la app | No abre, se cierra, no carga, se cae, se congela, errores o códigos de error que no son de una función concreta |
| `LE` | Lentitud general | La app es lenta o pesada en general |
| `TR` | Transferencias y pagos | Envíos, SPEI, pagos de servicios o de tarjeta, depósitos, retiros, QR, CoDi |
| `DI` | Dinero y cargos | Cargos no reconocidos, comisiones, dinero que no aparece o desaparece, fraude, reembolsos |
| `PR` | Productos | Tarjetas, créditos, préstamos, inversiones, límites, aprobación o rechazo de solicitudes |
| `AT` | Atención | Servicio al cliente, línea telefónica, chat, sucursal, ejecutivos, falta de respuesta o explicación del banco |
| `DS` | Diseño y actualizaciones | Cambios de interfaz, usabilidad, funciones quitadas, actualizaciones obligatorias o que empeoran la app |
| `CO` | Compatibilidad | Modelo de teléfono, sistema operativo, root, versión no soportada, permisos |
| `OT` | Otro problema concreto | Publicidad, notificaciones, idioma u otros |

## 3. Reglas

1. **Sin problema concreto → sin familias.** "Pésima", "no sirve", "no funciona", "la peor app", "malísimo servicio" sin más detalle no llevan códigos. `FA` exige una falla descrita: "no abre", "se cierra", "marca error".
2. **Un problema, una familia, la más específica.** Un error al transferir es solo `TR`, no `TR` + `FA`. "Las transferencias tardan días" es `TR`, no `LE`. `FA` y `LE` son solo para fallas o lentitud de la app en general.
3. **Problema atribuido a una actualización o a un cambio → además `DS`.** "Desde la actualización ya no abre" es `FA` + `DS`; "con la nueva versión no puedo entrar" es `AC` + `DS`. La mención debe ser explícita; no se supone.
4. **Problemas distintos → una familia por cada uno.** "No puedo entrar y me cobraron una comisión" es `AC` + `DI`.
5. **Solo lo que el texto dice.** No se infiere la causa ni el problema.
6. **Elogio concreto:** se marca si la queja además elogia un aspecto concreto ("el diseño está bien, pero se cierra"). "Buena app, pero..." no cuenta.

## 4. Ejemplos sintéticos

| Texto | Códigos | Elogio |
| :--- | :--- | :---: |
| "pésima app" | (ninguno) | 0 |
| "no sirve para nada, quiten esta app" | (ninguno) | 0 |
| "no abre, se queda en la pantalla de inicio" | `FA` | 0 |
| "desde que actualizaron se cierra sola" | `FA`, `DS` | 0 |
| "no puedo transferir, me marca error" | `TR` | 0 |
| "no me deja entrar y en sucursal no me resuelven" | `AC`, `AT` | 0 |
| "me gusta el diseño pero es lentísima" | `LE` | 1 |
| "la nueva versión es muy confusa, antes era mejor" | `DS` | 0 |

## 5. Medida derivada

Una reseña es **multi-aspecto** si tiene dos o más familias. La proporción se reporta sobre las filas `NEG` elegibles y por largo, porque depende mucho del número de palabras.
