from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from infrastructure.storage.publish_evidence import (
    PolicyError,
    publish_evidence,
    verify_published,
)
from infrastructure.storage.storage_audit import audit_storage


class StorageAuditTests(unittest.TestCase):
    def test_audit_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = [root / name for name in ("home", "fact_data", "scratch")]
            for path in paths:
                path.mkdir()
                (path / "sentinel.txt").write_text(path.name, encoding="utf-8")
            before = {
                path: (path.stat().st_mtime_ns, (path / "sentinel.txt").read_bytes())
                for path in paths
            }

            report = audit_storage(
                *paths,
                user="test-user",
                include_mount=False,
                include_du=False,
                include_quota=False,
            )

            self.assertFalse(report["read_only_guarantee"]["write_probe_performed"])
            self.assertEqual(report["quota"]["status"], "SKIPPED")
            for path in paths:
                self.assertEqual(
                    before[path],
                    (path.stat().st_mtime_ns, (path / "sentinel.txt").read_bytes()),
                )


class EvidencePublisherTests(unittest.TestCase):
    def _source(self, root: Path) -> Path:
        source = root / "source"
        (source / "nested").mkdir(parents=True)
        (source / "a.log").write_bytes(b"alpha\n")
        (source / "nested" / "b.json").write_text(
            json.dumps({"value": 7}), encoding="utf-8"
        )
        return source

    def test_publish_and_reverify_preserves_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._source(root)
            source_bytes = (source / "a.log").read_bytes()
            fact_data = root / "fact_data"

            receipt = publish_evidence(
                source,
                fact_data,
                Path("runs/pilot/demo"),
                user="test-user",
                artifact_id="pilot-demo",
                enforce_cluster_root=False,
            )

            destination = fact_data / "runs" / "pilot" / "demo"
            observed = verify_published(destination)
            self.assertEqual(receipt["status"], "VERIFIED")
            self.assertEqual(observed["file_count"], 2)
            self.assertEqual((source / "a.log").read_bytes(), source_bytes)
            self.assertTrue(source.exists())
            self.assertTrue((destination / "_storage_manifest.json").is_file())
            self.assertTrue((destination / "_storage_publish_receipt.json").is_file())

    def test_existing_destination_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._source(root)
            destination = root / "fact_data" / "runs" / "pilot" / "demo"
            destination.mkdir(parents=True)
            sentinel = destination / "keep.txt"
            sentinel.write_text("do-not-overwrite", encoding="utf-8")

            with self.assertRaisesRegex(PolicyError, "overwrite is forbidden"):
                publish_evidence(
                    source,
                    root / "fact_data",
                    Path("runs/pilot/demo"),
                    user="test-user",
                    enforce_cluster_root=False,
                )
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "do-not-overwrite")

    def test_destination_traversal_and_data_source_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._source(root)
            with self.assertRaisesRegex(PolicyError, "traversal"):
                publish_evidence(
                    source,
                    root / "fact_data",
                    Path("../escape"),
                    user="test-user",
                    enforce_cluster_root=False,
                )
        with self.assertRaisesRegex(PolicyError, "forbidden /data"):
            publish_evidence(
                Path("/data/forbidden-run"),
                Path("/tmp/fact_data-test"),
                Path("runs/pilot/demo"),
                user="test-user",
                enforce_cluster_root=False,
            )

    def test_corruption_invalidates_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._source(root)
            fact_data = root / "fact_data"
            publish_evidence(
                source,
                fact_data,
                Path("runs/pilot/demo"),
                user="test-user",
                enforce_cluster_root=False,
            )
            destination = fact_data / "runs" / "pilot" / "demo"
            (destination / "a.log").write_bytes(b"corrupt")
            with self.assertRaisesRegex(PolicyError, "no longer match"):
                verify_published(destination)

    def test_preexisting_lock_is_not_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._source(root)
            fact_data = root / "fact_data"
            lock_root = fact_data / ".publish-locks"
            lock_root.mkdir(parents=True)
            import hashlib

            destination_key = hashlib.sha256(b"runs/pilot/demo").hexdigest()
            lock = lock_root / f"{destination_key}.lock"
            lock.write_text("owned-by-another-publisher", encoding="utf-8")

            with self.assertRaisesRegex(PolicyError, "another publisher"):
                publish_evidence(
                    source,
                    fact_data,
                    Path("runs/pilot/demo"),
                    user="test-user",
                    enforce_cluster_root=False,
                )
            self.assertEqual(
                lock.read_text(encoding="utf-8"), "owned-by-another-publisher"
            )


if __name__ == "__main__":
    unittest.main()
