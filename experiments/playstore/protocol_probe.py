"""Copiar completo en Colab. Solo biblioteca estándar; no depende del repo.

1. Ejecutar con RUN_NETWORK=False: pruebas offline, sin solicitudes.
2. Cambiar RUN_NETWORK=True y ejecutar: sondeo acotado y reporte JSON.
3. Más tarde ejecutar `probe.replay_checkpoint()` y `probe.export()`.
4. Tras reiniciar Colab: `Probe.restore("ruta/checkpoint.json")`.

El protocolo es una hipótesis basada en el cliente de referencia consultado
el 2026-10-14. No se prueba un máximo global ni exhaustividad del histórico.
"""

import gzip
import hashlib
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RUN_NETWORK = False
APP_ID = "com.bancomer.mbanking"
COUNTS = [20, 50, 199, 200, 500]
BASELINE_PAGES = 4
TEST_STARS = False  # True añade hasta diez solicitudes; no cambia de proxy.
SAVE_RAW = True
MAX_REQUESTS = 24  # Compartido por todas las fases y replays de esta sesión.
MIN_DELAY_SEC = 3.0
PROTOCOL_VERSION = "ocpfdb-reference-2026-10-14"


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def fingerprint(value: str | None) -> str | None:
    return hashlib.sha256(value.encode()).hexdigest()[:16] if value else None


def build_body(
    app_id: str, count: int, token: str | None = None, star: int | None = None
) -> bytes:
    if count < 1 or (star is not None and star not in range(1, 6)):
        raise ValueError("count >= 1; star debe ser None o 1..5")
    pagination = [count] if token is None else [count, None, token]
    filters = [None, star, None, None, None, None, None, None, None]
    inner = [None, [2, 2, pagination, None, filters], [app_id, 7]]
    outer = [
        [["oCPfdb", json.dumps(inner, separators=(",", ":")), None, "generic"]]
    ]
    return urllib.parse.urlencode({"f.req": json.dumps(outer)}).encode()


def dig(value: Any, *indexes: int) -> Any:
    try:
        for index in indexes:
            if not isinstance(value, list):
                return None
            value = value[index]
    except IndexError:
        return None
    return value


class ProtocolError(ValueError):
    pass


def _frames(value: Any) -> list[list[Any]]:
    if not isinstance(value, list):
        return []
    if len(value) >= 3 and value[0] == "wrb.fr" and value[1] == "oCPfdb":
        return [value]
    return [frame for child in value for frame in _frames(child)]


@dataclass
class Page:
    reviews: list[dict[str, Any]]
    next_token: str | None
    classification: str
    token_candidates: dict[str, str | None]


def parse_response(text: str) -> Page:
    # Los enteros de longitud y el prefijo XSSI no son el payload RPC.
    frames: list[list[Any]] = []
    for line in text.splitlines():
        if not line.lstrip().startswith("["):
            continue
        try:
            frames.extend(_frames(json.loads(line)))
        except json.JSONDecodeError:
            continue
    if len(frames) != 1 or not isinstance(frames[0][2], str):
        raise ProtocolError("Se esperaba exactamente un frame JSON oCPfdb")
    try:
        inner = json.loads(frames[0][2])
    except json.JSONDecodeError as exc:
        raise ProtocolError("JSON interno inválido") from exc
    if not isinstance(inner, list):
        raise ProtocolError("El payload RPC no es una lista")
    if not inner:
        return Page([], None, "EMPTY_AMBIGUOUS", {})
    rows = inner[0]
    if not isinstance(rows, list):
        raise ProtocolError("El slot de reseñas no es una lista")
    candidates = {
        "minus2_last": dig(inner, -2, -1),
        "minus1_last": dig(inner, -1, -1),
    }
    candidates = {
        key: value if isinstance(value, str) and value else None
        for key, value in candidates.items()
    }
    token = candidates["minus2_last"]
    if token is None and candidates["minus1_last"] is not None:
        raise ProtocolError(
            "Cursor en ruta alternativa: revisar respuesta cruda"
        )
    reviews = []
    for row in rows:
        review_id, score, timestamp = dig(row, 0), dig(row, 2), dig(row, 5, 0)
        if (
            not isinstance(review_id, str)
            or not review_id
            or type(score) is not int
            or score not in range(1, 6)
            or not isinstance(timestamp, int | float)
            or isinstance(timestamp, bool)
        ):
            raise ProtocolError(
                "Fila con ID/estrellas/fecha fuera del contrato"
            )
        try:
            date = datetime.fromtimestamp(timestamp, tz=UTC).isoformat()
        except (OverflowError, ValueError, OSError) as exc:
            raise ProtocolError("Timestamp inválido") from exc
        votes = dig(row, 6)
        if votes is not None and (type(votes) is not int or votes < 0):
            raise ProtocolError(
                "votos_utilidad en [6] no es entero no negativo"
            )
        reviews.append(
            {
                "id": review_id,
                "date": date,
                "timestamp": timestamp,
                "stars": score,
                "votes": votes or 0,
                "text": dig(row, 4),
                "user": dig(row, 1, 0),
                "app_version": dig(row, 10),
            }
        )
    classification = (
        "EMPTY_WITH_CURSOR"
        if not reviews and token
        else "EMPTY_AMBIGUOUS"
        if not reviews
        else "PAGE_WITH_CURSOR"
        if token
        else "END_CANDIDATE"
    )
    return Page(reviews, token, classification, candidates)


def describe(page: Page) -> dict[str, Any]:
    ids = [r["id"] for r in page.reviews]
    dates = [r["date"] for r in page.reviews]
    timestamps = [r["timestamp"] for r in page.reviews]
    return {
        "classification": page.classification,
        "returned": len(ids),
        "unique": len(set(ids)),
        "ids": ids,
        "newest": max(dates, default=None),
        "oldest": min(dates, default=None),
        "descending": all(
            a >= b for a, b in zip(timestamps, timestamps[1:], strict=False)
        ),
        "stars": sorted({r["stars"] for r in page.reviews}),
        "with_text": sum(
            bool(str(r["text"] or "").strip()) for r in page.reviews
        ),
        "next_token_fp": fingerprint(page.next_token),
        "token_candidates": {
            k: fingerprint(v) for k, v in page.token_candidates.items()
        },
    }


def compare_ids(before: list[str], after: list[str]) -> dict[str, Any]:
    left, right = set(before), set(after)
    return {
        "same_order": before == after,
        "same_set": left == right,
        "intersection": len(left & right),
        "lost_from_page": len(left - right),
        "new_in_page": len(right - left),
        "jaccard": len(left & right) / len(left | right)
        if left | right
        else None,
        "note": (
            "Cambio de página no demuestra pérdida global "
            "ni expiración de token."
        ),
    }


class Probe:
    def __init__(
        self,
        app_id: str = APP_ID,
        output_dir: str | None = None,
        max_requests: int = MAX_REQUESTS,
        save_raw: bool = SAVE_RAW,
    ) -> None:
        self.app_id = app_id
        self.output_dir = Path(
            output_dir
            or (
                "playstore_probe_"
                + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            )
        )
        self.max_requests = max_requests
        self.save_raw = save_raw
        self.request_count = 0
        self.last_request_at = 0.0
        self.halted = False
        self.records: list[dict[str, Any]] = []
        self.comparisons: list[dict[str, Any]] = []
        self.checkpoint: dict[str, Any] | None = None

    def fetch(
        self,
        label: str,
        count: int = 199,
        token: str | None = None,
        star: int | None = None,
    ) -> Page | None:
        if self.halted or self.request_count >= self.max_requests:
            print("Sondeo detenido o presupuesto agotado")
            return None
        delay = MIN_DELAY_SEC + random.SystemRandom().uniform(0, 1)
        time.sleep(max(0, delay - (time.monotonic() - self.last_request_at)))
        self.request_count += 1
        self.last_request_at = time.monotonic()
        record: dict[str, Any] = {
            "label": label,
            "at": utc_now(),
            "requested": count,
            "star": star,
            "input_token_fp": fingerprint(token),
            "request_number": self.request_count,
        }
        self.records.append(record)
        request = urllib.request.Request(
            "https://play.google.com/_/PlayStoreUi/data/batchexecute?hl=es&gl=mx",
            data=build_body(self.app_id, count, token, star),
            method="POST",
            headers={
                "Content-Type": (
                    "application/x-www-form-urlencoded;charset=UTF-8"
                ),
                "User-Agent": "Mozilla/5.0 (compatible; VoCProtocolProbe/0.1)",
                "Accept-Language": "es-MX,es;q=0.9",
                "Accept-Encoding": "identity",
            },
        )
        started = time.monotonic()
        try:
            # La URL es HTTPS constante; no procede de entradas del usuario.
            with urllib.request.urlopen(  # noqa: S310  # nosec B310
                request, timeout=30
            ) as response:
                raw = response.read(5_000_001)
                record["http_status"] = response.status
            if len(raw) > 5_000_000:
                raise ProtocolError(
                    "Respuesta >5 MB; revisar tamaño solicitado"
                )
            record["response_bytes"] = len(raw)
            if self.save_raw:
                self.output_dir.mkdir(parents=True, exist_ok=True)
                path = (
                    self.output_dir
                    / f"response_{self.request_count:03d}.txt.gz"
                )
                path.write_bytes(gzip.compress(raw))
                record["raw_file"] = path.name
            page = parse_response(raw.decode("utf-8"))
            record.update(describe(page))
            if star is not None:
                record["star_filter_valid"] = all(
                    r["stars"] == star for r in page.reviews
                )
            if page.classification in {"EMPTY_AMBIGUOUS", "EMPTY_WITH_CURSOR"}:
                # Conservar vacío para inspección; no declarar EOF.
                self.halted = True
            return page
        except urllib.error.HTTPError as exc:
            record.update(
                {
                    "http_status": exc.code,
                    "retry_after": (
                        exc.headers.get("Retry-After") if exc.headers else None
                    ),
                }
            )
            self.halted = True  # No se busca provocar ni sortear el bloqueo.
        except (
            urllib.error.URLError,
            TimeoutError,
            ProtocolError,
            UnicodeError,
        ) as exc:
            record["error"] = type(exc).__name__ + ": " + str(exc)
            self.halted = True
        finally:
            record["elapsed_sec"] = round(time.monotonic() - started, 3)
            print(
                json.dumps(
                    {k: v for k, v in record.items() if k != "ids"},
                    ensure_ascii=False,
                )
            )
        return None

    def initial(
        self, counts: list[int] | None = None, test_stars: bool = False
    ) -> None:
        try:
            token = None
            seen_tokens: set[str] = set()
            seen_ids: set[str] = set()
            for index in range(BASELINE_PAGES):
                input_token = token
                page = self.fetch(f"baseline_{index + 1}", token=token)
                if page is None or self.halted:
                    return
                ids = [r["id"] for r in page.reviews]
                self.records[-1]["overlap_prior_pages"] = len(
                    set(ids) & seen_ids
                )
                seen_ids.update(ids)
                if index == 1 and input_token is not None:
                    self.checkpoint = {
                        "app_id": self.app_id,
                        "lang": "es",
                        "country": "mx",
                        "sort_order": 2,
                        "star": None,
                        "count": 199,
                        "protocol_version": PROTOCOL_VERSION,
                        "saved_at": utc_now(),
                        "token": input_token,
                        "reference_ids": ids,
                        "reference_oldest": describe(page)["oldest"],
                    }
                token = page.next_token
                if token is None:
                    break
                if token in seen_tokens:
                    self.records[-1]["error"] = "CURSOR_LOOP"
                    self.halted = True
                    return
                seen_tokens.add(token)
            if self.checkpoint:
                self.replay_checkpoint()
            for count in COUNTS if counts is None else counts:
                if (
                    self.fetch(f"size_{count}", count=count) is None
                    or self.halted
                ):
                    return
            if test_stars:
                for star in range(1, 6):
                    page = self.fetch(f"star_{star}_first", star=star)
                    if page is None or self.halted:
                        return
                    if page.next_token:
                        self.fetch(
                            f"star_{star}_second",
                            star=star,
                            token=page.next_token,
                        )
        finally:
            self.export()

    def replay_checkpoint(self) -> None:
        """Repetir tras horas/días manteniendo el contexto original."""
        if not self.checkpoint:
            print("No hay checkpoint de la página 2")
            return
        if self.checkpoint["protocol_version"] != PROTOCOL_VERSION:
            raise ValueError(
                "Versión de protocolo distinta; no reutilizar el cursor"
            )
        page = self.fetch("replay_saved_cursor", token=self.checkpoint["token"])
        if page is None:
            self.export()
            return
        comparison = compare_ids(
            self.checkpoint["reference_ids"], [r["id"] for r in page.reviews]
        )
        comparison.update(
            {"at": utc_now(), "saved_at": self.checkpoint["saved_at"]}
        )
        self.comparisons.append(comparison)
        print("Comparación:", json.dumps(comparison, ensure_ascii=False))
        # Leer una página reciente no crea una snapshot; sirve como referencia.
        self.fetch("head_at_replay_time")
        self.export()

    def export(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        report = {
            "app_id": self.app_id,
            "protocol_version": PROTOCOL_VERSION,
            "request_count": self.request_count,
            "max_requests": self.max_requests,
            "halted": self.halted,
            "records": self.records,
            "comparisons": self.comparisons,
            "conclusion": (
                "Observaciones acotadas; no prueba límite global, "
                "TTL ni exhaustividad."
            ),
        }
        (self.output_dir / "report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        if self.checkpoint:
            (self.output_dir / "checkpoint.json").write_text(
                json.dumps(self.checkpoint, indent=2), encoding="utf-8"
            )
        print("Resultados:", self.output_dir / "report.json")

    @classmethod
    def restore(cls, checkpoint_path: str) -> "Probe":
        checkpoint = json.loads(
            Path(checkpoint_path).read_text(encoding="utf-8")
        )
        expected = {
            "lang": "es",
            "country": "mx",
            "sort_order": 2,
            "star": None,
            "count": 199,
        }
        if any(checkpoint.get(key) != value for key, value in expected.items()):
            raise ValueError(
                "El contexto del cursor no coincide con este experimento"
            )
        probe = cls(app_id=checkpoint["app_id"])
        probe.checkpoint = checkpoint
        return probe


def offline_checks() -> None:
    """Fixtures artificiales: validan el código, nunca el protocolo real."""
    sample_cursor = 'token+con/escape="x"'
    form = urllib.parse.parse_qs(
        build_body(APP_ID, 199, sample_cursor).decode()
    )
    outer = json.loads(form["f.req"][0])
    inner = json.loads(outer[0][0][1])
    if inner != [
        None,
        [2, 2, [199, None, sample_cursor], None, [None] * 9],
        [APP_ID, 7],
    ]:
        raise AssertionError("Serialización incorrecta")
    entry = [
        "r1",
        ["Ana"],
        1,
        999,
        "No funciona",
        [1700000000],
        7,
        None,
        None,
        None,
        "1.0",
    ]
    response = ")]}'\n\n123\n" + json.dumps(
        [["wrb.fr", "oCPfdb", json.dumps([[entry], [None, "NEXT"], None])]]
    )
    page = parse_response(response)
    expected_cursor = "NEXT"
    if page.next_token != expected_cursor or page.reviews[0]["votes"] != 7:
        raise AssertionError("El parser no respeta cursor o votos [6]")
    try:
        parse_response("<html>consentimiento</html>")
    except ProtocolError:
        pass
    else:
        raise AssertionError("HTML no puede interpretarse como fin de datos")
    print("Pruebas offline OK; aún no se consultó Google Play.")


def simulate_initial_load() -> dict[str, Any]:
    """Modelo artificial por offset, no protocolo de Google.

    520 reseñas, una por día, en orden NEWEST. Annual cruza el día 365
    en su página 4 y conserva las 100 filas completas (días 300..399).
    Compara continuar ciegamente vs. revalidar ancla y reconciliar.
    """
    original = [f"day-{day:03d}" for day in range(520)]
    confirmed = set(original[:400])
    anchor = set(original[300:400])
    output: dict[str, Any] = {
        "hypothesis": "cursor posicional artificial, no protocolo real",
        "annual_requests": 4,
        "annual_cutoff_day": 365,
        "committed_oldest_day": 399,
        "extension": "mismo plan y upper anchor; objetivo inferior pasa a None",
    }
    for scenario, current in (
        ("20_new_reviews", [f"new-{i}" for i in range(20)] + original),
        ("120_old_reviews_removed", original[120:]),
    ):
        # Anti-patrón: confiar en el cursor de salida viejo, sin replay.
        blind = confirmed | set(current[400:])
        replay = current[300:400]
        overlap = len(anchor & set(replay))
        recovered = set(confirmed)
        replay_requests = 1
        if overlap:
            recovered.update(replay)
            position = 400
            strategy = "replay + continuación observada (no prueba universal)"
        else:
            position = 0
            strategy = "sin ancla: recorrer cabeza y consultar ledger"
        while position < len(current):
            recovered.update(current[position : position + 100])
            position += 100
            replay_requests += 1
        missing = set(original) - recovered
        if missing:
            raise AssertionError("La simulación de recuperación perdió IDs")
        output[scenario] = {
            "blind_missing_original_ids": len(set(original) - blind),
            "anchor_overlap": overlap,
            "recovery_strategy": strategy,
            "recovery_requests": replay_requests,
            "missing_after_recovery": len(missing),
            "note": (
                "Los IDs confirmados representan destino duradero, "
                "no solo un contador."
            ),
        }
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return output


if __name__ == "__main__":
    offline_checks()
    simulate_initial_load()
    if RUN_NETWORK:
        probe = Probe()
        probe.initial(test_stars=TEST_STARS)
    else:
        print("Para consultar Play: cambia RUN_NETWORK=True o ejecuta:")
        print("probe = Probe(); probe.initial(test_stars=False)")
