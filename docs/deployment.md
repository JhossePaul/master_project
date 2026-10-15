# Activación del primer despliegue

EPIC-2 declara recursos y dispone de aceptación local con mocks. No hay datos
anteriores que convertir. EPIC-3/EPIC-4 aún deben implementar sus consumidores.
El contrato de watermark es único y se inicia vacío cuando falta el objeto;
Pulumi no crea checkpoints, planes, manifiestos o ejecuciones de backfill.

## Verificación local

Desde la raíz del repositorio, usar Python 3.11 como CI:

```bash
uv sync --all-packages --locked --python 3.11
uv run pytest packages/voc-common/tests --cov=packages/voc-common/src --cov-fail-under=85
uv run pytest infra/tests --cov=infra/modules --cov-fail-under=80
```

La suite se valida con Python 3.11.14. Con la selección automática de Python
3.14 se observó un fallo de inicialización del event loop de Pulumi Mocks;
por eso el comando fija el intérprete usado por CI.

CI ejecuta esas suites y Ruff, Pyrefly y Bandit. La matriz integrada de `infra`
combina dev/prod, Free Tier/normal y CMEK on/off. Comprueba DAG, tablas, jobs,
Scheduler, lifecycle, grants, exports y Settings cargado desde las variables de
los contenedores. Los secretos simulados solo se desempaquetan dentro de tests;
no se imprimen sus valores en informes.

Los mocks no certifican permisos efectivos, cuotas, disponibilidad de imágenes,
comportamiento del proveedor ni recuperación ante cambios del origen.

## Preparar backend, stack y preview

Usar el backend y la cuenta del proyecto previstos. Si Pulumi no está en PATH,
el binario instalado en este equipo está en `~/.pulumi/bin/pulumi`.

1. Configurar/autenticar ese backend con `pulumi login`; no crear un backend
   alternativo solo para que pase el preview.
2. Desde `infra/`, seleccionar el stack `dev` de ese backend. Si es el primer uso,
   inicializarlo allí con `pulumi stack init dev`.
3. Revisar `Pulumi.dev.yaml`: proyecto/región reales, imágenes publicadas,
   perfiles HTTP/histórico, modo de operación y prefijos. Configurar los secretos
   con las herramientas de Pulumi; nunca incluir valores reales en archivos o logs.
4. Proporcionar credenciales GCP válidas para el proveedor. Confirmar que el
   proyecto y los permisos corresponden al ambiente elegido.
5. Ejecutar `pulumi preview --stack dev --non-interactive` y revisar el plan.

La última ejecución del preview se detuvo porque el backend no tenía un stack
`dev`; no produjo un plan validado con GCP. Tener la CLI instalada no sustituye
la configuración del backend/stack/credenciales.

Revisar nombre/location del bucket, lifecycle solo para crudos/temporales,
protección de borrado fuera de dev, cuatro tablas y dos Jobs Cloud Run.
Verificar que Scheduler tenga solo dos crons en Free Tier o seis en modo normal,
sin cron histórico; IAM debe mantener permisos por recurso y ninguna invocación
pública. Cualquier reemplazo/borrado inesperado requiere entender su causa antes
de aplicar. No activar CMEK, Vertex u otros servicios sin revisar sus recursos
condicionales, permisos y cuotas. El preview no ejecuta el extractor.

## Orden de activación

1. Validar imagen/entrypoint de EPIC-3 (`ingestion_worker.job`) y las APIs de
   ingesta, además del pipeline de EPIC-4. La declaración IaC de una imagen no
   comprueba que exista ni que su módulo arranque.
2. Desplegar la infraestructura revisada; `pulumi up` es una acción distinta de
   preview y se realizará cuando se solicite el despliegue.
3. Verificar acceso real a GCS y objetos cifrados si CMEK está activo, publicación
   Pub/Sub, auditoría BigQuery e invocación del Job con overrides de IDs.
4. Probar lease/fencing/CAS, publicación parcial, replay y continuación, y límites
   de ejecución en EPIC-3. Sanitización debe confirmar resultados duraderos antes
   de ack y respetar el TTL crudo de siete días.
5. Habilitar explícitamente `ingestion_v2_enabled` cuando runtime e integración
   estén verificados. Mantener los históricos bajo demanda y observar sus estados,
   presupuesto y recuperación antes de ampliar volumen o tamaño de página.

Los consumidores reciben configuración desde outputs/variables del despliegue.
Para detalles de identidad, rutas, presupuestos y overrides, consultar los
[contratos de ingesta](contracts/ingestion_v2.md).
