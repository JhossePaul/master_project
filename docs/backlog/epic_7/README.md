# EPIC-7 en detalle: features en orden de ejecución

> **Estado (2026-10-25): planificada.** El resumen de la épica, sus principios y el mapa del portal están en [`../epic_7.md`](../epic_7.md). Esta carpeta trae el detalle que necesita la sesión que la ejecute: un archivo por paso, en el orden en que se construye, con rutas, firmas, consultas, pantallas, pruebas y criterio de terminado.

## Orden

El orden de ejecución no es el de la numeración de las features: primero lo que usan todas (API, acceso, portal base), luego las secciones imprescindibles y después las importantes y deseables. **La tesis va al final con la prioridad más baja** (decisión del autor, 2026-10-25): los tokens se gastan primero en funcionalidad.

| Paso | Archivo | Feature | Nivel | Depende de |
| :-: | :--- | :--- | :--- | :--- |
| 0 | [`00_preparacion.md`](00_preparacion.md) | 7.0 Preparación y bloqueantes | Imprescindible | — |
| 1 | [`01_api_y_acceso.md`](01_api_y_acceso.md) | 7.1 API (base) y 7.2 Seguridad y acceso | Imprescindible | 0 |
| 2 | [`02_portal_base_y_landing.md`](02_portal_base_y_landing.md) | 7.3 Portal base, navegación y landing | Imprescindible | 1 y las preguntas de diseño marcadas "antes de 2" |
| 3 | [`03_cockpit.md`](03_cockpit.md) | 7.5 Cockpit diario (y pestaña por versión) | Imprescindible (pestaña: importante) | 2 |
| 4 | [`04_hitl_sentimiento.md`](04_hitl_sentimiento.md) | 7.7 HITL de sentimiento | Imprescindible | 2 |
| 5 | [`05_administracion.md`](05_administracion.md) | 7.10 Administración y configuración | Imprescindible | 2 |
| 6 | [`06_explorador.md`](06_explorador.md) | 7.6 Explorador, búsqueda semántica y explicación | Importante | 2 |
| 7 | [`07_alertas_deriva.md`](07_alertas_deriva.md) | 7.8 Alertas de deriva | Importante | 2 |
| 8 | [`08_mlops_aiops.md`](08_mlops_aiops.md) | 7.9 MLOps y AIOps | Importante | 2 y 5 |
| 9 | [`09_hitl_aspectos_topicos.md`](09_hitl_aspectos_topicos.md) | 7.7 HITL de aspectos y curaduría de tópicos | Deseable | 4 |
| 10 | [`10_gobernanza.md`](10_gobernanza.md) | 7.11 Data Card, Model Card y FMEA | Imprescindible (página del portal: deseable) | 1 a 8 |
| 11 | [`11_cierre_y_pruebas.md`](11_cierre_y_pruebas.md) | 7.12 Pruebas, *quality gates* y cierre del portal | Imprescindible | 1 a 10 |
| 12 | [`12_reporte_tesis.md`](12_reporte_tesis.md) | 7.4 Reporte de la tesis | **Prioridad mínima** | 11 |

Los pasos 3, 4 y 5 no dependen entre sí, ni el 6 y el 7; se pueden reordenar si conviene. Las pruebas de cada paso se escriben en el mismo paso: el 11 solo cierra.

**Si el tiempo no alcanza**, se recorta en este orden: el paso 12 (tesis), el 9, la pestaña por versión del paso 3 y luego las partes de los pasos 6 a 8 que el autor elija. Nunca se recorta lo imprescindible de los pasos 1 a 5, 10 y 11.

**Otros archivos de la carpeta:**

* [`design_questions.md`](design_questions.md): el cuestionario de diseño. Las preguntas marcadas "antes de 2" se responden antes de construir el portal base.
* [`anexo_b_no_vigente.md`](anexo_b_no_vigente.md): la especificación anterior a la reescritura del 2026-10-22. **No se implementa.**

**Documentos de referencia que se leen siempre:**

* [Guía visual](../../design/visual_guide.md): paleta, tipografía, componentes y formatos.
* [Stack y arquitectura](../../design/frontend_stack.md): despliegue, bibliotecas, estructura de carpetas y comandos.
* [Contrato v3](../../contracts/analytics_outputs_v3.md) y los modelos de `packages/voc-common/` (`hitl_v3.py`, `operations_v3.py`, `policies.py`, `predictions_v3.py`, `analytics_codes.py`): la fuente de las columnas.

## Protocolo para la sesión que ejecuta

1. **Al empezar un paso:** lee [`CLAUDE.md`](../../../CLAUDE.md), este archivo, el archivo del paso, la guía visual y el stack. Lee los modelos de `voc-common` que nombra el paso antes de escribir código. Cambia el "Estado" del archivo del paso a "En curso (fecha)".
2. **Durante el paso:**
   * sigue las rutas y firmas del archivo; si una firma no encaja con el código real, se ajusta la firma (con la razón en "Decisiones al implementar"), nunca el contrato de `voc-common` sin consultar;
   * **detente y pregunta al autor** antes de: cambiar un contrato de `voc-common` o una tabla, gastar dinero (Gemini, Kaggle, consultas de más de 5 GB), aplicar infraestructura (`pulumi up`), dar acceso a personas o enviar texto fuera de GCP;
   * si algo no está especificado y no es de esa lista, toma la opción recomendada del cuestionario o la más simple, y anótala en "Decisiones al implementar" del paso.
3. **Al terminar un paso:**
   * pasan las puertas de calidad (abajo);
   * el archivo del paso queda con "Estado: Terminado (fecha)", su "Avance" con lo que se validó (cifras, comandos) y sus casillas marcadas;
   * se proponen los commits del paso agrupados por tema, con el mensaje, y se commitea con la aprobación del autor (regla 6 de `CLAUDE.md`).
4. **Contexto:** EPIC-7 es implementación determinista, así que corre en **una sesión por épica** (`CLAUDE.md`, regla 5); se corta antes si el contexto se acerca al límite, dejando escrito en el paso dónde se quedó.
5. **Sesión paralela:** solo para trabajo que no comparte rutas con la principal. Los candidatos naturales son el paso 10 (solo `docs/governance/`) y la redacción del paso 12 (solo `docs/thesis/`).

## Puertas de calidad de cada paso

Desde la raíz del repo:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyrefly check
uv run bandit -c pyproject.toml -r .
uv run pytest services/api-backend --cov=api_backend --cov-fail-under=85
```

Y desde `web/portal/` (a partir del paso 2):

```bash
npm run check
npm test
npm run build
```

Si el paso tocó otro paquete (`voc-common`, `voc-nlp`, `ml-inference`, `infra`), también corre su `pytest` con el umbral de `ci.yaml`.

## Reglas que aplican a todos los pasos

* **Nada de texto de reseñas en git**, tampoco en fixtures ni en pruebas: los datos de prueba son sintéticos ("La app se cierra al pagar", escritos a mano).
* **Ninguna respuesta para el rol lector trae texto** (reseñas, comentarios, notas). Lo vigila una prueba con un texto centinela (paso 1).
* **Lenguaje común** en código, docstrings, nombres y textos del portal: sin códigos del backlog (`M4`, `P8-9`, `D12`, `F-15`).
* **Todo cambio de configuración crea una versión** con `set_by_hash` (o `actor_hash`) y `reason`; nada se edita ni se borra.
* **Cada número con su procedencia** (guía visual, sección 7).
* **Costo:** toda consulta lleva `maximum_bytes_billed`; las de reseñas filtran por fecha.
