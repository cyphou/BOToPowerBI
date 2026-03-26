"""Tests for Phase 12: Enterprise Scale — parallel engine, cache, checkpoint.

Tests ParallelMigrator, CacheLayer, CheckpointManager, and the
run_parallel_migration convenience function.
"""
import pytest
import sys
import os
import json
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from powerbi_import.parallel_engine import (
    CacheLayer,
    CheckpointManager,
    ParallelMigrator,
)


# ═══════════════════════════════════════════════════════════════════
#  CacheLayer Tests
# ═══════════════════════════════════════════════════════════════════

class TestCacheLayer:
    def test_put_and_get(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = CacheLayer(cache_dir=tmp)
            # Create a test file to cache results for
            test_file = os.path.join(tmp, "test.wid")
            with open(test_file, "w") as f:
                f.write("test content")
            cache.put(test_file, {"status": "ok", "result": 42})
            result = cache.get(test_file)
            assert result is not None
            assert result["status"] == "ok"
            assert result["result"] == 42

    def test_cache_miss(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = CacheLayer(cache_dir=tmp)
            test_file = os.path.join(tmp, "nonexistent.wid")
            # File doesn't exist, so _file_hash will fail → returns None
            assert cache.get(test_file) is None

    def test_file_hash_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = CacheLayer(cache_dir=tmp)
            test_file = os.path.join(tmp, "test.wid")
            with open(test_file, "w") as f:
                f.write("test content")
            h1 = cache._file_hash(test_file)
            h2 = cache._file_hash(test_file)
            assert len(h1) == 64  # SHA-256 hex digest
            assert h1 == h2

    def test_clear_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = os.path.join(tmp, "cache")
            cache = CacheLayer(cache_dir=cache_dir)
            test_file = os.path.join(tmp, "test.wid")
            with open(test_file, "w") as f:
                f.write("content")
            cache.put(test_file, {"x": 1})
            cache.clear()
            assert cache.get(test_file) is None


# ═══════════════════════════════════════════════════════════════════
#  CheckpointManager Tests
# ═══════════════════════════════════════════════════════════════════

class TestCheckpointManager:
    def test_mark_and_query_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            ckpt_path = os.path.join(tmp, "ckpt.json")
            ckpt = CheckpointManager(checkpoint_path=ckpt_path)
            ckpt.start_batch(3)
            fake_path = os.path.join(tmp, "file1.wid")
            ckpt.mark_completed(fake_path, {"status": "success", "elapsed": 1.5})
            assert ckpt.is_completed(fake_path)
            assert ckpt.completed_count == 1

    def test_mark_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            ckpt_path = os.path.join(tmp, "ckpt.json")
            ckpt = CheckpointManager(checkpoint_path=ckpt_path)
            ckpt.start_batch(2)
            fake_path = os.path.join(tmp, "bad.wid")
            ckpt.mark_failed(fake_path, "parse error")
            assert not ckpt.is_completed(fake_path)
            assert os.path.abspath(fake_path) in ckpt.pending_paths

    def test_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            ckpt_path = os.path.join(tmp, "ckpt.json")
            ckpt = CheckpointManager(checkpoint_path=ckpt_path)
            ckpt.start_batch(1)
            fake_path = os.path.join(tmp, "file.wid")
            ckpt.mark_completed(fake_path, {"status": "success"})
            ckpt.reset()
            assert ckpt.completed_count == 0
            assert not os.path.exists(ckpt_path)


# ═══════════════════════════════════════════════════════════════════
#  ParallelMigrator Tests
# ═══════════════════════════════════════════════════════════════════

class TestParallelMigrator:
    def test_init_defaults(self):
        pm = ParallelMigrator()
        assert pm.max_workers >= 1
        assert pm.timeout > 0

    def test_init_custom(self):
        with tempfile.TemporaryDirectory() as tmp:
            ckpt_path = os.path.join(tmp, "ckpt.json")
            pm = ParallelMigrator(
                max_workers=4,
                timeout_per_artifact=120,
                use_cache=True,
                cache_dir=os.path.join(tmp, "cache"),
                checkpoint_path=ckpt_path,
            )
            assert pm.max_workers == 4
            assert pm.timeout == 120
            assert pm.cache is not None
            assert pm.checkpoint is not None

    def test_run_batch_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            pm = ParallelMigrator(max_workers=1)
            result = pm.run_batch([], output_root=tmp)
            assert result["aggregate"]["total_artifacts"] == 0
            assert result["aggregate"]["success"] == 0

    def test_run_batch_nonexistent_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            pm = ParallelMigrator(max_workers=1, timeout_per_artifact=10)
            result = pm.run_batch(
                ["nonexistent1.wid", "nonexistent2.wid"],
                output_root=tmp,
            )
            assert result["aggregate"]["total_artifacts"] == 2
            assert result["aggregate"]["errors"] == 2

    def test_cache_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            pm = ParallelMigrator(use_cache=True, cache_dir=os.path.join(tmp, "c"))
            assert pm.cache is not None
