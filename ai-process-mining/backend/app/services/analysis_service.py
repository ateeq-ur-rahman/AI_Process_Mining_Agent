"""Get engine results for a dataset: from memory if we have them, otherwise recompute
from the stored events (after a restart, or for a different config)."""
from __future__ import annotations

import logging
import threading
from collections import OrderedDict

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.logging import log_event
from app.repositories.datasets import DatasetRepository
from app.services.config import AnalysisConfig
from app.services.engine import ENGINE_VERSION, EngineResult, run_engine

logger = logging.getLogger(__name__)


class EngineCache:
    """The last few engine results, keyed by (dataset_id, config hash).

    Hand-rolled rather than functools.lru_cache because deleting a dataset has to
    evict its entries. It lives in the process, which is why the backend runs a
    single uvicorn worker; a second worker would just recompute on its own.
    """

    def __init__(self, max_items: int = 4):
        self.max_items = max_items
        self._items: OrderedDict[tuple[str, str], EngineResult] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                return self._items[key]
        return None

    def put(self, key, value: EngineResult) -> None:
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            while len(self._items) > self.max_items:
                self._items.popitem(last=False)

    def drop_dataset(self, dataset_id: str) -> None:
        with self._lock:
            for k in [k for k in self._items if k[0] == dataset_id]:
                del self._items[k]


cache = EngineCache()


def compute_and_store(session: Session, dataset_id: str, events, cfg: AnalysisConfig | None = None) -> EngineResult:
    cfg = cfg or AnalysisConfig()
    result = run_engine(events, cfg)
    DatasetRepository(session).save_analysis(dataset_id, cfg.hash(), ENGINE_VERSION, result.results,
                                             result.processing_ms)
    cache.put((dataset_id, cfg.hash()), result)
    log_event(logger, "engine.run", dataset_id=dataset_id, rows_processed=int(len(events)),
              processing_ms=result.processing_ms, config_hash=cfg.hash())
    return result


def get_analysis(session: Session, dataset_id: str, cfg: AnalysisConfig | None = None) -> EngineResult:
    cfg = cfg or AnalysisConfig()
    key = (dataset_id, cfg.hash())
    hit = cache.get(key)
    if hit is not None:
        return hit
    repo = DatasetRepository(session)
    ds = repo.get(dataset_id)
    if ds.status != "ready":
        raise AppError(f"Dataset is not ready (status: {ds.status}).", status_code=409)
    events = repo.load_events(dataset_id)
    return compute_and_store(session, dataset_id, events, cfg)
