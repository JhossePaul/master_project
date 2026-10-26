# Paso 2. Feature 7.3: Portal base, navegación y landing

* **Estado (2026-10-25):** Pendiente.
* **Nivel:** imprescindible.
* **Depende de:** paso 1 y las preguntas del [cuestionario](design_questions.md) marcadas **"antes de 2"**.
* **Objetivo:** el proyecto `web/hitl-portal/` con la guía visual hecha código (tokens, tipografías, componentes base, primitivas de gráficas), la estructura de la aplicación (encabezado, navegación por rol, filtros globales en la URL) y la primera pantalla real: la landing.

## 1. Proyecto

`web/hitl-portal/` tiene 6 archivos vacíos (`package.json`, `vite.config.ts`, `Dockerfile`, `public/index.html`, `src/App.tsx`, `src/main.tsx`). Se borran y se crea el proyecto con la estructura de [`frontend_stack.md`](../../design/frontend_stack.md#31-estructura-de-webhitl-portal).

1. `npm create vite@latest` con la plantilla `react-ts` dentro de `web/hitl-portal/` (o a mano con el mismo resultado). `index.html` queda en la raíz del proyecto.
2. Dependencias de ejecución: `react`, `react-dom`, `react-router`, `@tanstack/react-query`, `@tanstack/react-table`, `@tanstack/react-virtual`, `openapi-fetch`, `react-hook-form`, `zod`, `@hookform/resolvers`, `d3-scale`, `d3-shape`, `d3-array`, `d3-time`, `d3-time-format`, `d3-brush`, `d3-selection`, `dygraphs`, `date-fns`, `lucide-react`, `clsx`, `tailwind-merge`, `@fontsource-variable/source-serif-4`, `@fontsource-variable/source-sans-3`, `@fontsource/source-code-pro`. Mermaid, MathJax y MDX entran en los pasos que los usan.
3. Desarrollo: `typescript`, `vite`, `@vitejs/plugin-react`, `tailwindcss`, `@tailwindcss/vite`, `@biomejs/biome`, `vitest`, `jsdom`, `@testing-library/react`, `@testing-library/user-event`, `@testing-library/jest-dom`, `msw`, `vitest-axe`, `openapi-typescript`, `@types/d3-*`.
4. shadcn/ui: `npx shadcn@latest init` (Tailwind 4, sin estilo base de color: los colores salen de `tokens.css`), y los componentes `button`, `card`, `dialog`, `dropdown-menu`, `popover`, `select`, `tabs`, `tooltip`, `badge`, `checkbox`, `radio-group`, `textarea`, `input`, `label`, `separator`, `skeleton`, `sonner` (avisos) y `table`.
5. `tsconfig.json` con `strict: true`, `noUncheckedIndexedAccess: true` y el alias `@/` → `src/`.
6. `vite.config.ts`: `react()`, `tailwindcss()`, el alias `@`, `server.proxy` de `/api` a `http://localhost:8080` y `build.sourcemap: false`.
7. `package.json`: los *scripts* de la sección 3.3 del stack, `"engines": {"node": ">=24"}` y `.nvmrc` con `24`.
8. `biome.json`: formato de 2 espacios y comillas dobles; reglas recomendadas, más `noExplicitAny` como error.

## 2. La guía visual en código

* **`src/styles/tokens.css`:** cada token de la [guía visual](../../design/visual_guide.md) (secciones 3 a 5) como variable CSS dentro de `@theme` de Tailwind 4, con los mismos nombres: `--color-green-600: #00685E;`, `--color-brand: var(--color-green-600);`, `--font-serif: "Source Serif 4 Variable", Georgia, serif;`, la escala de texto, etc. Los colores de datos también (`--color-bank-bbva`, `--color-sent-neg`…), para que D3 los lea con `getComputedStyle` y no se escriban dos veces.
* **`src/styles/index.css`:** importa Tailwind, los tokens y las tipografías; fija `body` (fondo `--color-bg`, texto `--color-text`, `font-sans`) y el anillo de foco.
* **`src/config/banks.ts`:**

```ts
export type BankId = "BBVA" | "AZTECA" | "SANTANDER" | "NUBANK" | "BANORTE";
export interface BankStyle { id: BankId; label: string; colorVar: string; dash: number[] }
export const BANKS: Record<BankId, BankStyle>;   // label = seudónimo
export const ALL_BANKS_STYLE: BankStyle;          // "Los cinco bancos"
export function bankLabel(id: string): string;    // id desconocido -> el id tal cual
```

  Mientras el autor no fije los seudónimos (pregunta `D-03`), `label` usa "Banco A" a "Banco E" en el orden de la tabla 4.1 de la guía. **Ningún componente escribe el nombre real de un banco:** la API devuelve `bank_id` y el portal muestra `bankLabel(id)`.
* **`src/lib/format.ts`:** `formatInt`, `formatPct(x, digits=1)` (`12.3 %`), `formatCi(est, lo, hi)` (`12.3 % [11.0, 13.6]`), `formatStars` (`+0.21 ★`), `formatKappa` (3 decimales), `formatDate` (`25 oct 2026`), `formatMonth` (`oct 2026`), `formatDateTime` (`25 oct 2026, 09:30 CDMX`) y `formatBytes`. Todas con `Intl` en `es-MX` y probadas.
* **`src/config/glossary.ts`:** `GLOSSARY: Record<TermId, { term: string; short: string; long?: string; link?: string }>`. Términos iniciales: PPI, proporción cruda, *gap* en estrellas, cobertura, umbral de confianza, κ (kappa), deriva, z robusto, PSI, HITL, modo ciego, modo asistido, muestra de monitoreo, familia de aspectos, marca de actualización (`u`), marca de seguridad (`s`), tópico, tópico útil, oclusión, temperatura, ECE, AURC, plata, oro, *re-scoring*, promoción, *rollback*. Cada definición en una o dos frases, en lenguaje común, con enlace al reporte de `docs/analytics/` que la respalda cuando existe.

## 3. Estructura de la aplicación

* **`src/main.tsx`:** `QueryClientProvider` (reintentos: 1; `staleTime` de 5 minutos para agregados) y `RouterProvider`.
* **`src/router.tsx`:** una ruta por sección, cada una con `lazy()`:

| Ruta | Sección | Rol mínimo | Paso |
| :--- | :--- | :--- | :-: |
| `/` | Inicio (landing) | lector | 2 |
| `/reporte/*` | Reporte de la tesis | lector | 12 |
| `/cockpit` | Cockpit (`?tab=diario` o `?tab=version`) | lector | 3 |
| `/explorador` | Explorador | analista | 6 |
| `/alertas` y `/alertas/:alertId` | Alertas de deriva | analista | 7 |
| `/hitl`, `/hitl/sentimiento`, `/hitl/aspectos`, `/hitl/topicos` | HITL | revisor | 4 y 9 |
| `/mlops` (`?tab=modelo`, `deriva`, `registro`, `pipeline`) | MLOps y AIOps | analista | 8 |
| `/admin` (`?tab=riesgo`, `deriva`, `historial`, `oro`, `muestras`) | Administración | administrador | 5 |
| `/gobernanza` | Gobernanza | lector | 10 |
| `*` | No encontrada | — | 2 |

  Las secciones de pasos futuros muestran un `EmptyState` de "En construcción" hasta su paso.
* **`src/auth/`:** `useMe()` (`GET /api/v1/me` con TanStack Query), `<RequireRole role="analista">` (muestra "No tienes acceso a esta sección" si falta el rol) y `hasRole(me, role)` con las mismas reglas de la API (un rol incluye al lector; el administrador incluye al analista). Con 403 en `/me`, una pantalla completa: "Tu cuenta no tiene acceso al portal".
* **`src/components/AppShell.tsx`:** encabezado, navegación lateral y área de contenido según la sección 8.1 de la guía. La navegación se arma desde `src/config/nav.ts` (grupo, ruta, ícono de lucide, rol mínimo) y muestra solo lo que permite el rol. Plegable, con el estado guardado en `localStorage` (no es dato sensible).
* **`src/filters/useGlobalFilters.ts`:**

```ts
interface GlobalFilters { banks: BankId[]; from: string; to: string }   // fechas ISO
function useGlobalFilters(): [GlobalFilters, (patch: Partial<GlobalFilters>) => void];
```

  Lee y escribe `?bancos=…&desde=…&hasta=…` con `useSearchParams`, valida con Zod y cae en los valores por defecto (todos los bancos y el periodo de la pregunta `L-02`; recomendado, los últimos 90 días). `<FilterBar />` lo usa: selector múltiple de bancos con su color, atajos de periodo (30 días, 90 días, 12 meses, todo) y rango personalizado. Al navegar por el menú se conservan los parámetros.

## 4. Componentes base

Los de la tabla 9 de la guía visual, en `src/components/`. Este paso construye: `KpiCard`, `ChartFrame`, `Provenance`, `MethodBadge`, `VersionChip`, `StatusPill`, `Callout`, `GlossaryTerm`, `EmptyState`, `ErrorState`, `Skeleton` (de shadcn), `ConfirmWithReason` y `Tahali`. `DataTable` y `KeyboardHint` llegan con su primera sección (pasos 4 y 6).

* `ChartFrame` recibe `{ kicker, title, subtitle?, howToRead?: ReactNode, provenance: ProvenanceProps, method?: "ppi" | "raw", data?: TableData, actions?: ReactNode, children }`. "Ver datos" abre la tabla con los mismos números.
* `ConfirmWithReason` recibe `{ title, description, confirmLabel, requireWord?: string, onConfirm(reason: string) }` y exige al menos 10 caracteres de motivo.
* `ErrorState` muestra el `request_id` del error de la API.

## 5. Primitivas de gráficas (`src/charts/`)

* `useChartSize(ref)`: ancho y alto del contenedor con `ResizeObserver`.
* `color.ts`: `cssVar(name)` para leer los tokens.
* `Axis` (abajo o a la izquierda, con `scale.ticks()` y `formatX`), `GridLines`, `Line`, `Band` (intervalo), `Points` con barras de error, `ReferenceLine` (umbral o vigente), `VersionMarkers` (líneas verticales con su etiqueta) y `Legend` con etiquetas directas.
* `TimeSeries.tsx`: envoltorio de dygraphs para series diarias largas. Props: `{ series: { id, label, colorVar, dash?, points: [Date, number | null][] }[], bands?, markers?, valueFormatter, height, onSelectDate?(d: Date), onRangeChange?(from, to) }`. Usa `drawCallback` para avisar del rango, `underlayCallback` para el día elegido y las bandas, y `annotations` para los cambios de versión. Se destruye en el *cleanup* del efecto.
* Toda gráfica de D3 dibuja SVG con JSX: D3 calcula y React pinta. `d3-selection` solo para el *brush*.

## 6. Cliente de la API

* `services/api-backend/openapi.json` se regenera con `uv run --package api-backend python -m api_backend.openapi > services/api-backend/openapi.json`.
* `npm run api:types` → `openapi-typescript ../../services/api-backend/openapi.json -o src/api/schema.d.ts`.
* `src/api/client.ts`: `createClient<paths>({ baseUrl: "" })` de `openapi-fetch`, con un *middleware* que convierte los errores en `ApiError { status, code, message, requestId }`.
* Un archivo de *hooks* por sección (`src/api/landing.ts`…) con TanStack Query; las claves de consulta incluyen los filtros globales.
* `src/test/handlers.ts`: manejadores de MSW con datos sintéticos para cada ruta, generados con los tipos de `schema.d.ts`.

## 7. Landing

### 7.1 API

`services/api-backend/src/api_backend/sections/landing/`:

| Método y ruta | Rol | Respuesta |
| :--- | :--- | :--- |
| `GET /api/v1/landing` | lector | `LandingResponse` |

```python
class Freshness(BaseModel):
    last_ingestion_at: datetime | None      # último COMPLETED en ingestion_runs_log_v2
    last_delta: RunSummary | None           # última corrida delta en inference_runs_current
    last_monitor_at: datetime | None        # MAX(computed_at) de kpi_estimates
    data_until: date | None                 # MAX(fecha) de review_predictions en los últimos 31 días

class BankHeadline(BaseModel):
    bank_id: str
    period: str                             # último mes cerrado con PPI, "YYYY-MM"
    neg: Estimate                           # kpi_estimates metric="neg", method="ppi"
    gap_estrellas: Estimate                 # metric="gap_estrellas", method="ppi"
    model_version: str
    gold_version: str | None

class Estimate(BaseModel):
    estimate: float
    ci_low: float | None
    ci_high: float | None
    method: Literal["ppi", "raw"]
    n_gold: int | None
    n_unlabeled: int | None

class LandingResponse(BaseModel):
    freshness: Freshness
    open_alerts: dict[str, int]             # bank_id -> alertas abiertas (drift_alerts_current)
    banks: list[BankHeadline]
    hitl_pending: int | None                # solo si el principal es revisor; si no, None
```

* `kpi_estimates` guarda una fila por corrida: siempre la de `computed_at` más reciente por (`metric`, `bank_id`, `period`, `method`).
* `data_until` filtra `fecha >= DATE_SUB(CURRENT_DATE(), INTERVAL 31 DAY)` sobre la tabla (no la vista), para leer una o dos particiones.
* Todo con `cache=True`.

### 7.2 Pantalla (`src/sections/landing/`)

1. ***Hero*** (`green-900`, tahalí en `gold-400`): el nombre del portal (pregunta `B-02`), una línea de qué es y la fecha de los datos ("Datos al 24 oct 2026").
2. **Frescura:** última ingesta, último delta (con su estado) y último monitor, cada uno con `StatusPill` (`ok` si ocurrió en las últimas 36 horas, o 8 días para el monitor; `aviso` si no).
3. **Una tarjeta por banco** (`KpiCard`, con el color del banco en el filete superior): proporción de `NEG` con PPI e intervalo, *gap* en estrellas con PPI e intervalo, mes y procedencia. Al pulsarla abre el cockpit filtrado por ese banco.
4. **Alertas de deriva abiertas**, por banco; para analistas, enlace a `/alertas`.
5. **Casos HITL pendientes** (solo revisores), con enlace a su cola.
6. **Accesos** a las secciones que permite el rol, con una línea de para qué sirve cada una.
7. **Pie:** enlace a gobernanza, versión del portal (`commit`), Universidad Panamericana, programa de posgrado y autor (pregunta `B-04`).

## 8. Pruebas

* **API:** `test_landing.py`, con repositorios en memoria: la última corrida gana; un banco sin PPI en el último mes cae al mes anterior; `hitl_pending` solo para revisores; la ruta entra en `SAMPLE_PARAMS` de la prueba del centinela.
* **Portal (Vitest):**
  * `format.test.ts`: cada formato con casos de borde (nulos, 0, 1, negativos);
  * `useGlobalFilters.test.tsx`: la URL va y vuelve; un banco desconocido se descarta; valores por defecto;
  * `nav.test.tsx`: cada rol ve exactamente sus secciones;
  * `banks.test.ts`: cinco bancos, cada `colorVar` existe en `tokens.css`, ningún `label` es un nombre real;
  * `landing.test.tsx`: con MSW, se ven las cinco tarjetas con su intervalo, la frescura y las alertas; un error muestra `ErrorState` con el `request_id`;
  * `a11y.test.tsx`: `axe` sin violaciones en la landing y en el *shell*.

## Terminado cuando

* [ ] `npm run check`, `npm test` y `npm run build` pasan; `dist/` pesa menos de 400 KB comprimido sin las secciones perezosas.
* [ ] La imagen de la API incluye el portal y en dev se ve la landing con datos reales detrás de IAP.
* [ ] Los filtros se conservan al navegar y se pueden compartir por URL.
* [ ] Ningún hex, nombre real de banco ni tipo de respuesta está escrito a mano fuera de `tokens.css`, `banks.ts` y `schema.d.ts` (lo revisa `grep` en la prueba de `banks`).

## Decisiones al implementar

_(Se llena al ejecutar.)_

## Avance

_(Se llena al ejecutar.)_
