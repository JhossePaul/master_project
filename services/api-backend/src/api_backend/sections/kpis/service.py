"""Arma las respuestas del cockpit desde el repositorio."""

from collections.abc import Sequence
from datetime import date
from statistics import median

from api_backend.sections.kpis.repository import (
    FAMILY_METRIC_PREFIX,
    MATRIX_CLASSES,
    UPDATE_METRIC,
    KpiRow,
    KpisRepository,
)
from api_backend.sections.kpis.schemas import (
    BankCard,
    CardValues,
    DailyTheme,
    DailyTopics,
    FamiliesResponse,
    FamilyMonth,
    MatrixCell,
    MonthlyKpi,
    TopicMonth,
    VersionRow,
    VersionsResponse,
)
from api_backend.sections.kpis.stats import wilson
from api_backend.sections.kpis.versions import OTHER, group_small, normalize
from api_backend.sections.landing.schemas import Estimate

CARD_METRICS = ("neg", "gap_estrellas", "estrellas_POS_texto_NEG")
MONTHLY_METRICS = ("neg", "gap_estrellas", "texto_peor", "texto_mejor")
MATRIX_METRICS = tuple(
    f"estrellas_{a}_texto_{b}" for a in MATRIX_CLASSES for b in MATRIX_CLASSES
)


def estimate(row: KpiRow) -> Estimate:
    return Estimate(
        estimate=row.estimate,
        ci_low=row.ci_low,
        ci_high=row.ci_high,
        method="ppi" if row.method == "ppi" else "raw",
        n_gold=row.n_gold,
        n_unlabeled=row.n_unlabeled,
    )


def _index(
    rows: Sequence[KpiRow], method: str
) -> dict[tuple[str, str, str], KpiRow]:
    return {
        (r.bank_id, r.period, r.metric): r for r in rows if r.method == method
    }


def year_before(period: str) -> str:
    year, month = period.split("-")
    return f"{int(year) - 1}-{month}"


def month_before(period: str) -> str:
    year, month = (int(x) for x in period.split("-"))
    return f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"


def _values(
    index: dict[tuple[str, str, str], KpiRow], bank: str, period: str
) -> CardValues:
    def get(metric: str) -> Estimate | None:
        row = index.get((bank, period, metric))
        return estimate(row) if row else None

    return CardValues(
        period=period,
        neg=get("neg"),
        gap_estrellas=get("gap_estrellas"),
        quejas_4_5=get("estrellas_POS_texto_NEG"),
    )


def cards(
    repo: KpisRepository, banks: Sequence[str], period: str | None
) -> list[BankCard]:
    """Por banco, el último mes con PPI hasta ``period`` (o el más reciente)."""
    rows = repo.kpi_rows(CARD_METRICS, banks)
    index = _index(rows, "ppi")
    neg_periods: dict[str, list[str]] = {}
    for bank, per, metric in index:
        if metric == "neg":
            neg_periods.setdefault(bank, []).append(per)
    target = period or max(
        (p for ps in neg_periods.values() for p in ps), default=None
    )
    alerts = repo.open_alerts()
    out: list[BankCard] = []
    for bank in banks:
        usable = [
            p for p in neg_periods.get(bank, []) if target and p <= target
        ]
        if not usable:
            out.append(
                BankCard(
                    bank_id=bank,
                    period=None,
                    neg=None,
                    gap_estrellas=None,
                    quejas_4_5=None,
                    previous_month=None,
                    previous_year=None,
                    model_version=None,
                    gold_version=None,
                    open_alerts=alerts.get(bank, 0),
                )
            )
            continue
        chosen = max(usable)
        current = _values(index, bank, chosen)
        previous = year_before(chosen)
        before = (
            _values(index, bank, previous)
            if (bank, previous, "neg") in index
            else None
        )
        last = month_before(chosen)
        month = (
            _values(index, bank, last) if (bank, last, "neg") in index else None
        )
        source = index[(bank, chosen, "neg")]
        out.append(
            BankCard(
                bank_id=bank,
                period=chosen,
                neg=current.neg,
                gap_estrellas=current.gap_estrellas,
                quejas_4_5=current.quejas_4_5,
                previous_month=month,
                previous_year=before,
                model_version=source.model_version,
                gold_version=source.gold_version,
                open_alerts=alerts.get(bank, 0),
            )
        )
    return out


def monthly(
    repo: KpisRepository,
    banks: Sequence[str],
    metrics: Sequence[str],
    date_from: date | None,
    date_to: date | None,
) -> list[MonthlyKpi]:
    lo = date_from.strftime("%Y-%m") if date_from else ""
    hi = date_to.strftime("%Y-%m") if date_to else "9999-99"
    rows = [r for r in repo.kpi_rows(metrics, banks) if lo <= r.period <= hi]
    ppi, raw = _index(rows, "ppi"), _index(rows, "raw")
    out = []
    for key in sorted(set(ppi) | set(raw)):
        main = ppi.get(key) or raw[key]
        out.append(
            MonthlyKpi(
                bank_id=key[0],
                period=key[1],
                metric=key[2],
                ppi=estimate(ppi[key]) if key in ppi else None,
                raw=estimate(raw[key]) if key in raw else None,
                model_version=main.model_version,
            )
        )
    return out


def matrix(
    repo: KpisRepository, banks: Sequence[str], period: str | None
) -> list[MatrixCell]:
    rows = repo.kpi_rows(MATRIX_METRICS, banks)
    target = period or max(
        (r.period for r in rows if r.method == "ppi"), default=None
    )
    if target is None:
        return []
    ppi, raw = _index(rows, "ppi"), _index(rows, "raw")
    out = []
    for bank in banks:
        for stars in MATRIX_CLASSES:
            for text in MATRIX_CLASSES:
                key = (bank, target, f"estrellas_{stars}_texto_{text}")
                if key not in ppi and key not in raw:
                    continue
                out.append(
                    MatrixCell(
                        bank_id=bank,
                        period=target,
                        stars_class=stars,  # type: ignore[arg-type]
                        text_class=text,  # type: ignore[arg-type]
                        ppi=estimate(ppi[key]) if key in ppi else None,
                        raw=estimate(raw[key]) if key in raw else None,
                    )
                )
    return out


def daily_topics(repo: KpisRepository, bank: str, day: date) -> DailyTopics:
    rows = repo.daily_themes(bank, day)
    familias = [
        DailyTheme(
            codigo=r.codigo,
            nombre=r.nombre,
            filas=r.filas,
            participacion=r.participacion,
            habitual=r.habitual,
        )
        for r in sorted(rows, key=lambda r: r.rango)
        if r.tipo == "familia"
    ]
    topicos = [
        DailyTheme(
            codigo=r.codigo,
            nombre=r.nombre,
            filas=r.filas,
            participacion=r.participacion,
            habitual=r.habitual,
        )
        for r in sorted(rows, key=lambda r: r.rango)
        if r.tipo == "topico"
    ]
    return DailyTopics(
        bank_id=bank,
        dia=day,
        n_neg=max((r.n_neg for r in rows), default=0),
        familias=familias[:5],
        topicos=topicos[:5],
        aspects_prompt_version=next(
            (
                r.aspects_prompt_version
                for r in rows
                if r.aspects_prompt_version
            ),
            None,
        ),
        topic_model_version=next(
            (r.topic_model_version for r in rows if r.topic_model_version),
            None,
        ),
    )


def families(repo: KpisRepository, banks: Sequence[str]) -> FamiliesResponse:
    drift: dict[
        tuple[str, str, str], tuple[float | None, float | None, bool | None]
    ] = {}
    for d in repo.family_drift(banks):
        if d.metric == UPDATE_METRIC:
            code = "u"
        elif d.metric.startswith(FAMILY_METRIC_PREFIX):
            code = d.metric.removeprefix(FAMILY_METRIC_PREFIX)
        else:
            continue
        drift[(d.bank_id, d.period[:7], code)] = (d.z, d.threshold, d.alert)
    series = []
    for level in sorted(
        repo.family_levels(banks), key=lambda r: (r.bank_id, r.period, r.family)
    ):
        z, threshold, alert = drift.get(
            (level.bank_id, level.period, level.family), (None, None, None)
        )
        series.append(
            FamilyMonth(
                bank_id=level.bank_id,
                period=level.period,
                family=level.family,
                neg_count=level.neg_count,
                share=level.neg_count / level.base if level.base else 0.0,
                z=z,
                threshold=threshold,
                alert=alert,
            )
        )
    return FamiliesResponse(series=series, prompt_changes=repo.prompt_changes())


def topics(repo: KpisRepository, banks: Sequence[str]) -> list[TopicMonth]:
    return [
        TopicMonth(
            bank_id=r.bank_id,
            period=r.period,
            topic_id=r.topic_id,
            nombre=r.nombre,
            audience=r.audience,
            families=r.families,
            filas=r.filas,
            share=r.filas / r.base if r.base else 0.0,
            topic_model_version=r.topic_model_version,
        )
        for r in sorted(
            repo.topic_months(banks),
            key=lambda r: (r.bank_id, r.period, r.topic_id),
        )
    ]


def versions(repo: KpisRepository, bank: str) -> VersionsResponse:
    """Por ``release``; las de menos de 50 reseñas van en ``OTRAS``."""
    totals = repo.version_totals(bank)
    rec = {t.version_app: normalize(bank, t.version_app) for t in totals}
    all_filas = sum(t.filas for t in totals)
    known_filas = sum(t.filas for t in totals if rec[t.version_app])

    rows_by_release: dict[str, int] = {}
    for t in totals:
        release = rec[t.version_app]
        if release:
            rows_by_release[release] = rows_by_release.get(release, 0) + t.filas
    label = group_small(rows_by_release)

    def final(version_app: str | None) -> str | None:
        release = rec.get(version_app)
        return label[release] if release else None

    agg: dict[str, dict[str, object]] = {}
    for t in totals:
        name = final(t.version_app)
        if name is None:
            continue
        a = agg.setdefault(
            name,
            {
                "filas": 0,
                "neg": 0,
                "lab": 0,
                "u": 0,
                "first": t.first_seen,
                "last": t.last_seen,
            },
        )
        a["filas"] += t.filas  # type: ignore[operator]
        a["neg"] += t.neg  # type: ignore[operator]
        a["lab"] += t.neg_labeled  # type: ignore[operator]
        a["u"] += t.neg_u  # type: ignore[operator]
        a["first"] = min(a["first"], t.first_seen)  # type: ignore[type-var]
        a["last"] = max(a["last"], t.last_seen)  # type: ignore[type-var]
    fam: dict[str, dict[str, int]] = {}
    for f in repo.version_families(bank):
        name = final(f.version_app)
        if name is not None:
            bucket = fam.setdefault(name, {})
            bucket[f.family] = bucket.get(f.family, 0) + f.n

    rows = []
    for name, a in agg.items():
        filas, neg = int(a["filas"]), int(a["neg"])  # type: ignore[call-overload]
        lab, u = int(a["lab"]), int(a["u"])  # type: ignore[call-overload]
        low, high = wilson(neg, filas)
        rows.append(
            VersionRow(
                release=name,
                first_seen=a["first"],  # type: ignore[arg-type]
                last_seen=a["last"],  # type: ignore[arg-type]
                filas=filas,
                neg=neg,
                neg_share=neg / filas if filas else 0.0,
                neg_ci_low=low,
                neg_ci_high=high,
                u_share=u / lab if lab else 0.0,
                families={
                    code: n / lab
                    for code, n in sorted(
                        fam.get(name, {}).items(), key=lambda kv: -kv[1]
                    )
                }
                if lab
                else {},
            )
        )
    rows.sort(key=lambda r: (r.release == "OTRAS", r.first_seen))
    named = [r for r in rows if r.release != OTHER]
    return VersionsResponse(
        bank_id=bank,
        rows=rows,
        coverage=known_filas / all_filas if all_filas else 0.0,
        median_neg_share=median(r.neg_share for r in named) if named else None,
        median_u_share=median(r.u_share for r in named) if named else None,
    )
