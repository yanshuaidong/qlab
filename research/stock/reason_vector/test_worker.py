import io
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from worker import DIMENSIONS, Engine, LocalModel, QdrantStore, VectorError, label_id, serve


def vector(a=1, b=0):
    return [a, b] + [0] * (DIMENSIONS - 2)


class FakeModel:
    def __init__(self):
        self.calls = []
        self.fail = False

    def encode(self, texts):
        self.calls.append(list(texts))
        if self.fail:
            raise RuntimeError("inference failed")
        return [vector() for _ in texts]


class FakeStore:
    def __init__(self):
        self.collections = {}
        self.fail_put = False
        self.fail_delete = False
        self.hits = None

    def create(self, name):
        self.collections[name] = {}

    def vectors(self, name, labels):
        return {x: self.collections[name][x] for x in labels if x in self.collections[name]}

    def put(self, name, vectors):
        if self.fail_put:
            raise RuntimeError("write failed")
        self.collections[name].update(vectors)

    def query(self, name, query, limit):
        if self.hits is not None:
            return self.hits[:limit]
        def cosine(v):
            return sum(a * b for a, b in zip(v, query)) / math.sqrt(
                sum(a * a for a in v) * sum(b * b for b in query))
        return sorted([(k, cosine(v)) for k, v in self.collections[name].items()],
                      key=lambda pair: -pair[1])[:limit]

    def delete(self, name):
        if self.fail_delete:
            raise RuntimeError("cleanup failed")
        self.collections.pop(name, None)

    def close(self):
        pass


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model_path = self.root / "model"
        self.model_path.mkdir()
        self.model = FakeModel()
        self.store = FakeStore()
        self.engine = self.make_engine()

    def make_engine(self, version="verified-test-commit", path=None):
        return Engine(model_path=path or self.model_path, model_version=version,
                      index_path=self.root / "index", model_factory=lambda _: self.model,
                      store_factory=lambda _: self.store)

    def test_deduplicate_and_stable_ids(self):
        result = self.engine.refresh(["芯片", " AI ", "芯片", "", "  "])
        self.assertEqual(result["indexedCount"], 2)
        self.assertEqual(self.model.calls, [["AI", "芯片"]])
        self.assertEqual(label_id("芯片"), label_id("芯片"))
        self.assertNotEqual(label_id("芯片"), label_id("AI"))
        self.assertEqual(self.engine.read_manifest()["labels"], ["AI", "芯片"])

    def test_unchanged_labels_reuse_entire_index(self):
        first = self.engine.refresh(["A", "B"])
        name = self.engine.read_manifest()["collection"]
        self.assertEqual(self.engine.refresh(["B", "A", "A"]), first)
        self.assertEqual(len(self.model.calls), 1)
        self.assertEqual(list(self.store.collections), [name])

    def test_incremental_add_remove(self):
        self.engine.refresh(["A", "B"])
        self.engine.refresh(["B", "C"])
        self.assertEqual(self.model.calls, [["A", "B"], ["C"]])
        self.assertEqual(len(self.store.collections), 1)
        self.assertEqual(set(next(iter(self.store.collections.values()))), {"B", "C"})

    def test_filter_before_limit_sort_and_threshold(self):
        self.engine.refresh(["deleted", "A", "B", "C"])
        self.store.hits = [("deleted", 1.0), ("B", 0.7), ("C", 0.8), ("A", 0.8)]
        result = self.engine.search("query", 2, None, ["A", "B", "C", "new"])
        self.assertEqual(result["items"], [{"label": "A", "score": 0.8}, {"label": "C", "score": 0.8}])
        self.assertEqual(self.engine.search("query", 10, 0.9, ["A", "B"])["items"], [])

    def test_cosine_scores(self):
        self.engine.refresh(["A", "B"])
        collection = self.engine.read_manifest()["collection"]
        self.store.collections[collection]["B"] = vector(0, 1)
        self.assertEqual(self.engine.search("A", 2, None, ["A", "B"])["items"],
                         [{"label": "A", "score": 1.0}, {"label": "B", "score": 0.0}])

    def test_version_change_requires_rebuild_no_reuse(self):
        self.engine.refresh(["A"])
        other = self.make_engine(version="another-fixed-commit")
        with self.assertRaisesRegex(VectorError, "重建"):
            other.search("A", 1, None, ["A"])
        other.refresh(["A"])
        self.assertEqual(self.model.calls, [["A"], ["A"]])
        self.assertEqual(other.read_manifest()["modelVersion"], "another-fixed-commit")

    def test_path_and_dimension_mismatch(self):
        self.engine.refresh(["A"])
        other_path = self.root / "other-model"
        other_path.mkdir()
        with self.assertRaisesRegex(VectorError, "重建"):
            self.make_engine(path=other_path).search("A", 1, None, ["A"])
        manifest = self.engine.read_manifest()
        manifest["dimensions"] = 3
        self.engine.write_manifest(manifest)
        with self.assertRaisesRegex(VectorError, "重建"):
            self.engine.search("A", 1, None, ["A"])

    def assert_refresh_failure_safe(self, fail):
        self.engine.refresh(["A"])
        before = self.engine.manifest_path.read_bytes()
        fail()
        with self.assertRaises(Exception):
            self.engine.refresh(["A", "B"])
        self.assertEqual(self.engine.manifest_path.read_bytes(), before)
        self.assertEqual(list(self.store.collections), [self.engine.read_manifest()["collection"]])

    def test_inference_failure_preserves_old_index(self):
        self.assert_refresh_failure_safe(lambda: setattr(self.model, "fail", True))
        self.model.fail = False
        self.assertEqual(len(self.engine.search("A", 1, None, ["A"])["items"]), 1)

    def test_storage_failure_preserves_old_index(self):
        self.assert_refresh_failure_safe(lambda: setattr(self.store, "fail_put", True))

    def test_atomic_publish_failure_preserves_old_index(self):
        self.engine.refresh(["A"])
        before = self.engine.manifest_path.read_bytes()
        with patch("worker.os.replace", side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                self.engine.refresh(["B"])
        self.assertEqual(self.engine.manifest_path.read_bytes(), before)
        self.assertEqual(len(self.store.collections), 1)
        self.assertEqual(list(self.engine.index_path.glob("*.tmp")), [])

    def test_cleanup_failure_keeps_new_manifest(self):
        self.engine.refresh(["A"])
        self.store.fail_delete = True
        with patch("sys.stderr", new=io.StringIO()):
            self.engine.refresh(["B"])
        self.assertEqual(self.engine.read_manifest()["labels"], ["B"])
        self.assertIn(self.engine.read_manifest()["collection"], self.store.collections)

    def test_empty_initialization_no_model_inference(self):
        self.assertEqual(self.engine.refresh([])["indexedCount"], 0)
        self.assertEqual(self.engine.search("query", 5, None, [])["items"], [])
        self.assertEqual(self.model.calls, [])
        self.assertIsNone(self.engine._model)

    def test_missing_configuration_and_uninitialized(self):
        with self.assertRaisesRegex(VectorError, "MODEL_VERSION"):
            self.make_engine(version="")
        with self.assertRaisesRegex(VectorError, "目录不存在"):
            self.make_engine(path=self.root / "missing")
        with self.assertRaisesRegex(VectorError, "尚未初始化"):
            self.engine.search("A", 1, None, ["A"])

    def test_invalid_inputs(self):
        for labels in [None, "A", [1]]:
            with self.assertRaises(VectorError):
                self.engine.refresh(labels)
        for limit in [0, -1, True, 1.5]:
            with self.assertRaises(VectorError):
                self.engine.search("A", limit, None, [])
        for score in [True, "0.1", float("nan"), float("inf"), 1.1]:
            with self.assertRaises(VectorError):
                self.engine.search("A", 1, score, [])

    def test_invalid_model_vector_cannot_publish(self):
        self.model.encode = lambda texts: [[1, 2]] * len(texts)
        with self.assertRaisesRegex(VectorError, "维度"):
            self.engine.refresh(["A"])
        self.assertFalse(self.engine.manifest_path.exists())
        self.assertEqual(self.store.collections, {})

    def test_jsonl_multiple_requests_and_error_recovery(self):
        source = io.StringIO('not json\n{"id":1,"action":"refresh","labels":[]}\n'
                             '{"id":2,"action":"bad"}\n'
                             '{"id":3,"action":"search","text":"A","limit":1,"minScore":null,"labels":[]}\n')
        output = io.StringIO()
        serve(source, output, engine_factory=lambda: self.engine)
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(rows), 4)
        self.assertIn("error", rows[0])
        self.assertEqual(rows[1]["result"]["indexedCount"], 0)
        self.assertEqual(rows[2]["id"], 2)
        self.assertIn("error", rows[2])
        self.assertEqual(rows[3], {"id": 3, "result": {"items": []}})

    def test_manifest_protocol_fields(self):
        self.engine.refresh([])
        manifest = self.engine.read_manifest()
        self.assertEqual(set(manifest), {"schemaVersion", "modelId", "modelVersion", "modelPath",
                                         "dimensions", "collection", "labels", "updatedAt"})
        self.assertEqual(manifest["modelId"], "BAAI/bge-m3")
        self.assertEqual(manifest["schemaVersion"], 1)
        self.assertEqual(manifest["dimensions"], 1024)
        self.assertTrue(Path(manifest["modelPath"]).is_absolute())

    def test_local_model_loader_offline_arguments(self):
        dependency = MagicMock()
        dependency.SentenceTransformer.return_value.get_sentence_embedding_dimension.return_value = DIMENSIONS
        with patch.dict("sys.modules", {"sentence_transformers": dependency}), patch.dict("os.environ", {}):
            LocalModel(self.model_path)
        dependency.SentenceTransformer.assert_called_once_with(
            str(self.model_path), device="cpu", local_files_only=True, trust_remote_code=False)

    def test_missing_dependencies_are_explicit(self):
        with patch.dict("sys.modules", {"sentence_transformers": None}):
            with self.assertRaisesRegex(VectorError, "缺少 sentence-transformers"):
                LocalModel(self.model_path)
        with patch.dict("sys.modules", {"qdrant_client": None}):
            with self.assertRaisesRegex(VectorError, "缺少 qdrant-client"):
                QdrantStore(self.root / "qdrant")

    def test_model_load_failure_is_offline_error(self):
        dependency = MagicMock()
        dependency.SentenceTransformer.side_effect = OSError("missing weights")
        with patch.dict("sys.modules", {"sentence_transformers": dependency}), patch.dict("os.environ", {}):
            with self.assertRaisesRegex(VectorError, "不会联网下载"):
                LocalModel(self.model_path)

    def test_jsonl_nonstandard_numbers_do_not_kill_worker(self):
        source = io.StringIO('{"id":NaN,"action":"refresh","labels":[]}\n'
                             '{"id":1,"action":"refresh","labels":[]}\n')
        output = io.StringIO()
        serve(source, output, engine_factory=lambda: self.engine)
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(rows), 2)
        self.assertIn("error", rows[0])
        self.assertEqual(rows[1]["result"]["indexedCount"], 0)

    def test_dependency_stdout_goes_to_stderr(self):
        def factory():
            print("dependency debug")
            return self.engine
        output = io.StringIO()
        errors = io.StringIO()
        with patch("sys.stderr", errors):
            serve(io.StringIO('{"id":1,"action":"refresh","labels":[]}\n'), output, factory)
        self.assertEqual(json.loads(output.getvalue())["id"], 1)
        self.assertIn("dependency debug", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
