"""Valores fijos de una corrida (mvp-ingesta.md, seccion 3)."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_MICROSECOND = timedelta(microseconds=1)


@dataclass(frozen=True)
class RunContext:
    run_at: datetime      # UTC, tomado una sola vez al iniciar el proceso
    extraction_id: int    # run_at en microsegundos desde epoch UTC

    @classmethod
    def start(cls) -> "RunContext":
        run_at = datetime.now(timezone.utc)
        # Division exacta entre timedeltas: sin errores de float.
        return cls(run_at=run_at, extraction_id=(run_at - _EPOCH) // _MICROSECOND)

    @property
    def run_at_iso(self) -> str:
        """TIMESTAMP en formato aceptado por BigQuery (JSON de carga)."""
        return self.run_at.isoformat(timespec="microseconds")
