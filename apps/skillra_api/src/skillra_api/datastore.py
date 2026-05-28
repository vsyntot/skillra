"""Datastore abstraction for loading processed parquet datasets."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import pandas as pd

from .config import Settings
from .services.circuit_breaker import with_retry

logger = logging.getLogger(__name__)


@dataclass
class DataStoreLoadPaths:
    """Concrete artifact paths used for one DataStore reload."""

    features_path: str
    market_view_path: str
    dataset_meta_path: str
    market_snapshots_path: str


@dataclass
class DatasetStatus:
    """Represents the load status for a single dataset."""

    name: str
    path: str
    loaded: bool
    mtime: Optional[datetime]
    error: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation of the status."""

        return {
            "path": self.path,
            "loaded": self.loaded,
            "mtime": self.mtime.isoformat() if self.mtime else None,
            "error": self.error,
        }


@dataclass
class DataStoreSnapshot:
    """In-memory DataStore state used to roll back a failed publish attempt."""

    features_df: Optional[pd.DataFrame]
    market_view_df: Optional[pd.DataFrame]
    snapshot_history_df: Optional[pd.DataFrame]
    dataset_meta: Optional[dict[str, Any]]
    dataset_status: dict[str, DatasetStatus]


class DataUnavailableError(RuntimeError):
    """Raised when requested data is not loaded and cannot be served."""

    def __init__(self, dataset: str, status: Dict[str, Any]):
        self.dataset = dataset
        self.status = status
        message = f"Dataset '{dataset}' is not available."
        super().__init__(message)


class DataStore:
    """Load and provide access to processed datasets required by the API."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.Lock()

        self._features_df: Optional[pd.DataFrame] = None
        self._market_view_df: Optional[pd.DataFrame] = None
        self._snapshot_history_df: Optional[pd.DataFrame] = None
        self._dataset_meta: Optional[dict[str, Any]] = None
        self._dataset_status: dict[str, DatasetStatus] = {
            "features": DatasetStatus("features", settings.features_path, False, None, "not loaded"),
            "market_view": DatasetStatus("market_view", settings.market_view_path, False, None, "not loaded"),
            "snapshot_history": DatasetStatus(
                "snapshot_history",
                settings.market_snapshots_path,
                False,
                None,
                "not loaded",
            ),
        }
        # In-process cache for computed meta values (roles, grades, skills, etc.).
        # Cleared on every reload() so callers always see fresh data after reload-data.
        # See GAP-N03 / SPRINT-003.
        self._meta_cache: dict[str, Any] = {}
        self._cache_generation = 0

    @property
    def is_ready(self) -> bool:
        """Return True when all datasets are loaded without errors."""

        with self._lock:
            return all(status.loaded for status in self._dataset_status.values())

    def reload(self) -> None:
        """Reload all configured datasets from disk (synchronous).

        Thread-safe. Updates internal status for each dataset without raising
        exceptions so API endpoints can decide on the fallback behaviour.
        Clears :attr:`_meta_cache` so meta endpoints recompute on next request.
        Use :meth:`areload` from async contexts to avoid blocking the event loop.
        """

        self.reload_from_paths(self._configured_paths())

    def reload_from_paths(self, paths: DataStoreLoadPaths) -> None:
        """Reload datasets from explicit artifact paths.

        This keeps the default ``latest`` paths as compatibility/cache paths
        while allowing admin reload to serve the active Dataset Registry run.
        """

        with self._lock:
            self._features_df, self._dataset_status["features"] = self._load_dataset("features", paths.features_path)
            self._market_view_df, self._dataset_status["market_view"] = self._load_dataset(
                "market_view", paths.market_view_path
            )
            self._snapshot_history_df, self._dataset_status["snapshot_history"] = self._load_snapshot_history(
                paths.market_snapshots_path
            )
            self._dataset_meta = self._load_dataset_meta(paths.dataset_meta_path)
            self._meta_cache.clear()
            self._cache_generation += 1

        # Log record counts for observability (GAP-N06 / SPRINT-003).
        features_rows = len(self._features_df) if self._features_df is not None else 0
        market_rows = len(self._market_view_df) if self._market_view_df is not None else 0
        snapshot_rows = len(self._snapshot_history_df) if self._snapshot_history_df is not None else 0
        logger.info(
            "DataStore reloaded features_rows=%d market_view_rows=%d snapshot_history_rows=%d",
            features_rows,
            market_rows,
            snapshot_rows,
        )

        # Update Prometheus gauges.
        try:
            from skillra_api.metrics import DATASTORE_ROWS  # noqa: PLC0415 — lazy import to avoid circular

            DATASTORE_ROWS.labels(dataset="features").set(features_rows)
            DATASTORE_ROWS.labels(dataset="market_view").set(market_rows)
        except Exception:  # pragma: no cover — metrics are optional
            pass

    async def areload(self) -> None:
        """Async wrapper around :meth:`reload` that offloads disk I/O to a thread pool.

        Preferred over :meth:`reload` when called from async FastAPI handlers so that
        the event loop is not blocked while parquet files are read from disk.
        """

        await self.areload_from_paths(self._configured_paths())

    async def areload_from_paths(self, paths: DataStoreLoadPaths) -> None:
        """Async wrapper around :meth:`reload_from_paths`."""

        await self._areload_with_retry(paths)

    def snapshot_state(self) -> DataStoreSnapshot:
        """Return the currently served in-memory state for publish rollback."""

        with self._lock:
            return DataStoreSnapshot(
                features_df=self._features_df,
                market_view_df=self._market_view_df,
                snapshot_history_df=self._snapshot_history_df,
                dataset_meta=dict(self._dataset_meta) if self._dataset_meta is not None else None,
                dataset_status=dict(self._dataset_status),
            )

    def restore_state(self, snapshot: DataStoreSnapshot) -> None:
        """Restore a previously served state after a candidate publish failure."""

        with self._lock:
            self._features_df = snapshot.features_df
            self._market_view_df = snapshot.market_view_df
            self._snapshot_history_df = snapshot.snapshot_history_df
            self._dataset_meta = dict(snapshot.dataset_meta) if snapshot.dataset_meta is not None else None
            self._dataset_status = dict(snapshot.dataset_status)
            self._meta_cache.clear()
            self._cache_generation += 1

    @with_retry(OSError, RuntimeError, max_attempts=3, wait_min=0.1, wait_max=1.0)
    async def _areload_with_retry(self, paths: DataStoreLoadPaths) -> None:
        await asyncio.to_thread(self.reload_from_paths, paths)

    @property
    def cache_generation(self) -> int:
        """Incrementing version used by external caches to ignore stale meta keys."""

        with self._lock:
            return self._cache_generation

    async def watch_reload(self, check_interval: float = 30.0) -> None:
        """Background task that reloads data when parquet file mtime changes (Sprint-007 TASK-09).

        Runs as an asyncio.Task in the lifespan. Polls file mtimes every
        *check_interval* seconds and calls :meth:`areload` when a change is detected.
        """

        def _get_mtimes() -> dict[str, float]:
            mtimes: dict[str, float] = {}
            for path_str in (self._settings.features_path, self._settings.market_view_path):
                p = self._resolve_path(Path(path_str))
                if p.exists():
                    mtimes[str(p)] = p.stat().st_mtime
            return mtimes

        known_mtimes = await asyncio.to_thread(_get_mtimes)
        while True:
            try:
                await asyncio.sleep(check_interval)
                current = await asyncio.to_thread(_get_mtimes)
                if current != known_mtimes:
                    logger.info("DataStore: file change detected, reloading")
                    await self.areload()
                    known_mtimes = current
            except asyncio.CancelledError:
                break
            except Exception as exc:  # pragma: no cover — defensive guard
                logger.warning("DataStore watch_reload error: %s", exc)

    def status(self) -> Dict[str, Any]:
        """Return a summary of dataset statuses."""

        with self._lock:
            datasets = {name: status.as_dict() for name, status in self._dataset_status.items()}
            ready = all(status.loaded for status in self._dataset_status.values())
            return {"ready": ready, "datasets": datasets, "dataset_meta": self._dataset_meta}

    def get_cached_meta(self, key: str, compute_fn: Callable[..., Any], *args: Any) -> Any:
        """Return a cached meta value, computing it on first access.

        Thread-safe. The cache is invalidated on every :meth:`reload` call so
        callers always see data consistent with the currently loaded datasets.
        On a cache miss, *compute_fn* is called **outside** the lock to avoid
        holding it during CPU-bound pandas operations.

        Args:
            key: Cache key identifying the computed value.
            compute_fn: Callable that computes the value from ``*args``.
            *args: Arguments forwarded to *compute_fn* on a cache miss.
        """

        with self._lock:
            if key in self._meta_cache:
                return self._meta_cache[key]
        # Compute outside the lock — deterministic result, allow concurrent computation.
        result = compute_fn(*args)
        with self._lock:
            # setdefault: first writer wins; subsequent concurrent results are discarded.
            return self._meta_cache.setdefault(key, result)

    def get_features_df(self) -> pd.DataFrame:
        """Return the features dataframe or raise if unavailable."""

        with self._lock:
            if not self._dataset_status["features"].loaded or self._features_df is None:
                raise DataUnavailableError("features", self.status())
            return self._features_df

    def get_market_view_df(self) -> pd.DataFrame:
        """Return the market view dataframe or raise if unavailable."""

        with self._lock:
            if not self._dataset_status["market_view"].loaded or self._market_view_df is None:
                raise DataUnavailableError("market_view", self.status())
            return self._market_view_df

    def get_dataset_meta(self) -> Optional[dict[str, Any]]:
        """Return dataset metadata if available."""

        with self._lock:
            if self._dataset_meta is None:
                return None
            return dict(self._dataset_meta)

    def get_snapshot_history_df(self) -> pd.DataFrame:
        """Return market snapshot history or an empty dataframe if unavailable."""

        with self._lock:
            if self._snapshot_history_df is None:
                return pd.DataFrame()
            return self._snapshot_history_df

    def _load_dataset(self, name: str, path_str: str) -> tuple[Optional[pd.DataFrame], DatasetStatus]:
        path = self._resolve_path(Path(path_str))

        if not path.exists():
            return None, DatasetStatus(name, str(path), False, None, f"File not found: {path}")

        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        try:
            df = pd.read_parquet(path)
            return df, DatasetStatus(name, str(path), True, mtime, None)
        except Exception as exc:  # pragma: no cover - defensive guard
            return None, DatasetStatus(name, str(path), False, mtime, str(exc))

    def _load_dataset_meta(self, path_str: str) -> Optional[dict[str, Any]]:
        path = self._resolve_path(Path(path_str))

        if not path.exists():
            return None

        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # pragma: no cover - defensive guard
            return None

    def _load_snapshot_history(self, path_str: str) -> tuple[pd.DataFrame, DatasetStatus]:
        path = self._resolve_path(Path(path_str))
        mtime = datetime.fromtimestamp(path.stat().st_mtime) if path.exists() else None
        try:
            from skillra_pda.timeseries import load_snapshot_history  # noqa: PLC0415

            df = load_snapshot_history(path)
            return df, DatasetStatus("snapshot_history", str(path), True, mtime, None)
        except Exception as exc:  # pragma: no cover - optional artefact should not block API readiness
            logger.warning("Failed to load snapshot history path=%s error=%s", path, exc)
            return pd.DataFrame(), DatasetStatus("snapshot_history", str(path), True, mtime, str(exc))

    @staticmethod
    def _resolve_path(path: Path) -> Path:
        if path.exists():
            return path

        if "latest" not in path.parts:
            return path

        parts = list(path.parts)
        latest_index = parts.index("latest")
        fallback = Path(*parts[:latest_index], *parts[latest_index + 1 :])
        return fallback if fallback.exists() else path

    def _configured_paths(self) -> DataStoreLoadPaths:
        return DataStoreLoadPaths(
            features_path=self._settings.features_path,
            market_view_path=self._settings.market_view_path,
            dataset_meta_path=self._settings.dataset_meta_path,
            market_snapshots_path=self._settings.market_snapshots_path,
        )
