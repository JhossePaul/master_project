# Guía de Ejecución del Backlog (Instrucciones para Desarrolladores y Agentes IA)

Este directorio contiene la especificación técnica detallada para implementar el
**App Store Label Noise & Incident Analyzer** de principio a fin.

El propósito de esta documentación es servir como fuente única de verdad
(*Single Source of Truth*) para que tanto ingenieros de software como agentes de
Inteligencia Artificial (LLMs) puedan construir cada módulo de forma
determinista, incremental y sin romper contratos entre componentes.

## 📂 Estructura de Archivos

* `README.md`: Este documento. Reglas de arquitectura, convenciones de código y
  flujo de ejecución para agentes.
* `epics.md`: Mapa general del proyecto dividido en 6 Épicas secuenciales,
  alineadas con el cronograma de 8 semanas y el marco *Data-Driven Scrum (DDS)*
  * *Eval-Driven Development (EDD)*.
* `epic_1.md` a `epic_6.md`: Desglose granular de las *Features* e Historias
  Técnicas de cada épica, incluyendo rutas exactas de archivos, firmas de
  funciones/clases, esquemas de datos y criterios de aceptación verificables.

---

## 🤖 Protocolo de Ejecución para Agentes de Código (LLMs)

Si eres un agente de IA encargado de implementar una *Feature* de este backlog,
**DEBES** seguir estrictamente este flujo de trabajo en cada iteración:

1. **Lectura de Contexto:**
   * Lee primero `packages/voc-common/src/voc_common/schemas.py` y `constants.py` antes de escribir código en cualquier servicio. **Nunca inventes diccionarios sueltos (`dict[str, Any]`)** para transferir datos entre capas; importa y utiliza siempre los modelos de `Pydantic` de `voc-common`.
2. **Aislamiento de Dependencias (`uv`):**
   * Este monorepo utiliza `uv workspaces`.
   * Si necesitas añadir una librería a un servicio específico, edita el `pyproject.toml` de ese paquete/servicio (ej. `services/ingestion-worker/pyproject.toml`) o ejecuta `uv add --package <nombre-paquete> <libreria>`.
   * Nunca instales paquetes manualmente con `pip install`.
3. **Estándares de Código Obligatorios:**
   * **Versión de Python:** 3.11+.
   * **Tipado Estricto:** Todas las funciones, métodos y atributos deben tener *type hints* explícitos (compatibles con `Pyrefly`).
   * **Seguridad:** Prohibido hardcodear credenciales, IDs de proyectos de GCP o llaves privadas.Todo parámetro de entorno debe leerse mediante `pydantic-settings` o variables de entorno.
4. **Definición de Hecho (Definition of Done - DoD):**
   Ninguna *Feature* o tarea se considera terminada hasta que los siguientes 4 comandos pasen sin errores desde la raíz del monorepo:

   ```bash
   # 1. Formateo y Linting
   uv run ruff check .
   uv run ruff format --check .

   # 2. Verificación de Tipos
   uv run pyrefly check

   # 3. Análisis Estático de Seguridad (SAST)
   uv run bandit -c pyproject.toml -r .

   # 4. Pruebas Unitarias y Cobertura Mínima (>= 80%)
   uv run pytest --cov-fail-under=80
   ```

---

## 🔄 Orden de Implementación Recomendado

Las épicas tienen dependencias técnicas estrictas. **No inicies una épica sin haber completado los contratos de datos de las épicas predecesoras:**

1. `epic_1.md` (Contratos de Datos en `voc-common` y CI/CD) $\rightarrow$ **Base obligatoria.**
2. `epic_2.md` (Infraestructura como Código en GCP con Pulumi).
3. `epic_3.md` (Workers de Ingesta Paralela y Publicación en Pub/Sub).
4. `epic_4.md` (Pipeline de Sanitización PII en Dataflow + Cloud DLP y Persistencia en BigQuery).
5. `epic_5.md` (Modelado NLP: Baseline RoBERTa, Arquitectura Dual LoRA / Delora, Cálculo de TNSS y ABSA en Vertex AI).
6. `epic_6.md` (API Backend en FastAPI, Búsqueda Vectorial, Explicabilidad SHAP/LIME, Portal React HITL y Gobernanza).
