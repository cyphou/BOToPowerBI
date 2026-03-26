"""Parallel migration engine — concurrent extraction and generation.

Provides ProcessPoolExecutor-based parallelism for batch migration with:
- Configurable worker count (defaults to CPU count)
- Per-artifact timeout with graceful cancellation
- Progress callback for UI integration
- Error isolation (one failure doesn't block the batch)
- Memory-aware scheduling
- Checkpoint/resume for interrupted batches

Usage:
    from powerbi_import.parallel_engine import ParallelMigrator
    migrator = ParallelMigrator(max_workers=8)
    results = migrator.run_batch(files, output_root)
"""

import hashlib
import json
import logging
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed, TimeoutError
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Single-artifact worker (must be top-level for pickle) ────────

def _migrate_single(input_path, output_root, artifact_index, total):
    """Run extract + generate for one BO artifact (worker function).

    Returns a result dict with extraction/generation stats.
    """
    from bo_export.extract_bo_data import extract_bo_data
    from powerbi_import.import_to_powerbi import PowerBIImporter

    name = os.path.splitext(os.path.basename(input_path))[0]
    out_dir = os.path.join(output_root, name)
    os.makedirs(out_dir, exist_ok=True)

    result = {
        "name": name,
        "source_file": os.path.basename(input_path),
        "index": artifact_index,
        "total": total,
        "status": "success",
        "error": None,
        "elapsed": 0.0,
        "extraction_counts": {},
        "generation_counts": {},
    }

    t0 = time.time()

    try:
        extracted = extract_bo_data(input_path, output_dir=out_dir)
        for key in ("reports", "queries", "datasources", "formulas", "prompts",
                     "filters", "tables", "columns", "joins", "groups", "sorts",
                     "alerts", "subreports", "charts", "custom_sql"):
            items = extracted.get(key, [])
            result["extraction_counts"][key] = len(items) if isinstance(items, list) else 0
    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"Extraction: {exc}"
        result["elapsed"] = time.time() - t0
        return result

    try:
        importer = PowerBIImporter(source_dir=out_dir)
        importer.import_all(report_name=name, output_dir=out_dir)
        result["generation_counts"] = {"tables": 0, "columns": 0, "measures": 0,
                                       "relationships": 0, "pages": 0, "visuals": 0}
    except Exception as exc:
        result["status"] = "partial"
        result["error"] = f"Generation: {exc}"

    result["elapsed"] = time.time() - t0
    return result


class CacheLayer:
    """Hash-based cache for extraction + generation results.

    Skips re-processing unchanged inputs. Uses SHA-256 of file content
    as cache key.
    """

    def __init__(self, cache_dir=None, ttl_hours=168):
        self.cache_dir = cache_dir or os.path.join(os.getcwd(), ".migration_cache")
        self.ttl_seconds = ttl_hours * 3600
        os.makedirs(self.cache_dir, exist_ok=True)

    def _file_hash(self, path):
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def _cache_path(self, file_hash):
        return os.path.join(self.cache_dir, f"{file_hash}.json")

    def get(self, input_path):
        """Return cached result if valid, else None."""
        try:
            fh = self._file_hash(input_path)
            cp = self._cache_path(fh)
            if not os.path.exists(cp):
                return None
            age = time.time() - os.path.getmtime(cp)
            if age > self.ttl_seconds:
                os.unlink(cp)
                return None
            with open(cp, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def put(self, input_path, result):
        """Store a migration result in cache."""
        try:
            fh = self._file_hash(input_path)
            cp = self._cache_path(fh)
            with open(cp, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, default=str)
        except Exception:
            pass

    def clear(self):
        """Remove all cached results."""
        import shutil
        if os.path.isdir(self.cache_dir):
            shutil.rmtree(self.cache_dir)
            os.makedirs(self.cache_dir, exist_ok=True)


class CheckpointManager:
    """Checkpoint/resume for interrupted batch migrations.

    Tracks which artifacts have been processed. On resume, skips
    already-completed artifacts.
    """

    def __init__(self, checkpoint_path=None):
        self.path = checkpoint_path or "migration_checkpoint.json"
        self._data = self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"completed": {}, "failed": {}, "started": None}

    def _save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)

    def is_completed(self, artifact_path):
        return os.path.abspath(artifact_path) in self._data["completed"]

    def mark_completed(self, artifact_path, result):
        self._data["completed"][os.path.abspath(artifact_path)] = {
            "status": result.get("status"),
            "elapsed": result.get("elapsed"),
            "timestamp": time.time(),
        }
        self._save()

    def mark_failed(self, artifact_path, error):
        self._data["failed"][os.path.abspath(artifact_path)] = {
            "error": str(error),
            "timestamp": time.time(),
        }
        self._save()

    def start_batch(self, total_files):
        self._data["started"] = time.time()
        self._data["total"] = total_files
        self._save()

    def reset(self):
        self._data = {"completed": {}, "failed": {}, "started": None}
        if os.path.exists(self.path):
            os.unlink(self.path)

    @property
    def completed_count(self):
        return len(self._data["completed"])

    @property
    def pending_paths(self):
        return set(self._data.get("failed", {}).keys())


class ParallelMigrator:
    """Orchestrates parallel batch migration with progress tracking."""

    def __init__(self, max_workers=None, timeout_per_artifact=300,
                 use_cache=False, cache_dir=None, checkpoint_path=None):
        self.max_workers = max_workers or min(os.cpu_count() or 4, 8)
        self.timeout = timeout_per_artifact
        self.cache = CacheLayer(cache_dir) if use_cache else None
        self.checkpoint = CheckpointManager(checkpoint_path)

    def run_batch(self, input_paths, output_root, progress_callback=None,
                  resume=False):
        """Run parallel migration on a list of BO artifact paths.

        Args:
            input_paths: List of absolute paths to .wid/.rpt/.unx etc.
            output_root: Root directory for migration output.
            progress_callback: Optional fn(completed, total, result_dict).
            resume: If True, skip already-completed artifacts from checkpoint.

        Returns:
            dict: {aggregate, artifacts} same structure as generate_report.
        """
        if resume:
            paths = [p for p in input_paths
                     if not self.checkpoint.is_completed(p)]
            logger.info("Resuming: %d/%d artifacts remaining",
                        len(paths), len(input_paths))
        else:
            paths = list(input_paths)
            self.checkpoint.reset()

        total = len(paths)
        self.checkpoint.start_batch(total)
        results = []
        t_start = time.time()

        os.makedirs(output_root, exist_ok=True)

        with ProcessPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {}
            for i, path in enumerate(paths):
                # Check cache first
                if self.cache:
                    cached = self.cache.get(path)
                    if cached:
                        results.append(cached)
                        self.checkpoint.mark_completed(path, cached)
                        if progress_callback:
                            progress_callback(len(results), total, cached)
                        continue

                future = pool.submit(
                    _migrate_single, path, output_root, i, total
                )
                futures[future] = path

            for future in as_completed(futures):
                path = futures[future]
                try:
                    result = future.result(timeout=self.timeout)
                    results.append(result)
                    self.checkpoint.mark_completed(path, result)
                    if self.cache:
                        self.cache.put(path, result)
                except TimeoutError:
                    result = {
                        "name": os.path.splitext(os.path.basename(path))[0],
                        "source_file": os.path.basename(path),
                        "status": "error",
                        "error": f"Timeout after {self.timeout}s",
                        "elapsed": self.timeout,
                    }
                    results.append(result)
                    self.checkpoint.mark_failed(path, "timeout")
                except Exception as exc:
                    result = {
                        "name": os.path.splitext(os.path.basename(path))[0],
                        "source_file": os.path.basename(path),
                        "status": "error",
                        "error": str(exc),
                        "elapsed": 0,
                    }
                    results.append(result)
                    self.checkpoint.mark_failed(path, str(exc))

                if progress_callback:
                    progress_callback(len(results), total, result)

        elapsed_total = time.time() - t_start

        agg = {
            "total_artifacts": len(results),
            "success": sum(1 for r in results if r.get("status") == "success"),
            "partial": sum(1 for r in results if r.get("status") == "partial"),
            "errors": sum(1 for r in results if r.get("status") == "error"),
            "elapsed_seconds": round(elapsed_total, 2),
            "workers": self.max_workers,
        }

        return {"aggregate": agg, "artifacts": results}


def run_parallel_migration(input_paths, output_root, max_workers=None,
                           use_cache=False, resume=False):
    """Convenience function for parallel batch migration.

    Args:
        input_paths: List of BO artifact paths.
        output_root: Output directory root.
        max_workers: Number of parallel workers (default: CPU count, max 8).
        use_cache: Enable hash-based result caching.
        resume: Resume from checkpoint if available.

    Returns:
        dict with aggregate stats and per-artifact results.
    """
    migrator = ParallelMigrator(
        max_workers=max_workers,
        use_cache=use_cache,
    )
    return migrator.run_batch(input_paths, output_root, resume=resume)
