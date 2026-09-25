"""Offline JSONL worker for BAAI/bge-m3 dense label vectors."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import sys
import tempfile
from datetime import datetime, timezone
import uuid

MODEL_ID = "BAAI/bge-m3"
DIMENSIONS = 1024
SCHEMA_VERSION = 1
REPO_ROOT = Path(__file__).resolve().parents[3]
LABEL_NAMESPACE = uuid.UUID("96b0845a-b81a-53cd-9e8d-4788876e6ba2")


class VectorError(Exception):
    pass


def label_id(label):
    return str(uuid.uuid5(LABEL_NAMESPACE, label))


def normalize_labels(labels):
    if not isinstance(labels, list) or any(not isinstance(x, str) for x in labels):
        raise VectorError("labels 必须是标签字符串数组")
    return sorted({x.strip() for x in labels if x.strip()})


class LocalModel:
    def __init__(self, path):
        # These flags also guard any transitive Hugging Face calls against networking.
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise VectorError("缺少 sentence-transformers 依赖，请按 README 离线部署说明安装") from exc
        try:
            self.model = SentenceTransformer(
                str(path), device="cpu", local_files_only=True, trust_remote_code=False
            )
            if self.model.get_sentence_embedding_dimension() != DIMENSIONS:
                raise VectorError("本地模型输出维度不是 1024，请使用 BAAI/bge-m3 完整快照")
        except VectorError:
            raise
        except Exception as exc:
            raise VectorError("本地 BAAI/bge-m3 模型加载失败，请检查快照完整性；不会联网下载") from exc

    def encode(self, texts):
        return self.model.encode(
            texts, normalize_embeddings=True, show_progress_bar=False,
            convert_to_numpy=True,
        ).tolist()


class QdrantStore:
    def __init__(self, path):
        try:
            from qdrant_client import QdrantClient, models
        except ImportError as exc:
            raise VectorError("缺少 qdrant-client 依赖，请按 README 安装") from exc
        self.models = models
        try:
            self.client = QdrantClient(path=str(path), force_disable_check_same_thread=True)
        except Exception as exc:
            raise VectorError("本地向量存储打开失败，请检查目录权限及是否有其他 worker 占用") from exc

    def create(self, name):
        self.client.create_collection(
            collection_name=name,
            vectors_config=self.models.VectorParams(size=DIMENSIONS, distance=self.models.Distance.COSINE),
        )

    def vectors(self, name, labels):
        result = {}
        for offset in range(0, len(labels), 256):
            records = self.client.retrieve(
                collection_name=name, ids=[label_id(x) for x in labels[offset:offset + 256]],
                with_vectors=True, with_payload=True,
            )
            for record in records:
                label = (record.payload or {}).get("label")
                if label is not None and str(record.id) == label_id(label):
                    result[label] = record.vector
        return result

    def put(self, name, vectors):
        pairs = list(vectors.items())
        for offset in range(0, len(pairs), 256):
            self.client.upsert(collection_name=name, wait=True, points=[
                self.models.PointStruct(id=label_id(label), vector=vector, payload={"label": label})
                for label, vector in pairs[offset:offset + 256]
            ])

    def query(self, name, vector, limit):
        points = self.client.query_points(
            collection_name=name, query=vector, limit=limit, with_payload=True,
        ).points
        return [(point.payload["label"], float(point.score)) for point in points]

    def delete(self, name):
        self.client.delete_collection(collection_name=name)

    def close(self):
        self.client.close()


class Engine:
    """Inject model_factory(path) and store_factory(path) to test without dependencies."""
    def __init__(self, model_path=None, model_version=None, index_path=None,
                 model_factory=LocalModel, store_factory=QdrantStore):
        raw_path = model_path if model_path is not None else os.environ.get("REASON_VECTOR_MODEL_PATH")
        version = model_version if model_version is not None else os.environ.get("REASON_VECTOR_MODEL_VERSION")
        if not raw_path or not str(raw_path).strip():
            raise VectorError("必须设置 REASON_VECTOR_MODEL_PATH，指向已下载的本地模型快照")
        if not isinstance(version, str) or not version.strip():
            raise VectorError("必须设置 REASON_VECTOR_MODEL_VERSION，填写已核实的固定快照 commit 标识")
        self.model_path = Path(raw_path).expanduser().resolve()
        if not self.model_path.is_dir():
            raise VectorError("本地模型目录不存在；请预先下载固定版本快照，不会自动联网")
        self.version = version.strip()
        self.index_path = Path(index_path or os.environ.get("REASON_VECTOR_INDEX_PATH")
                               or REPO_ROOT / "storage/stock/reason_vectors").expanduser().resolve()
        self.index_path.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.index_path / "manifest.json"
        self.model_factory = model_factory
        self.store_factory = store_factory
        self._model = None
        self._store = None

    @property
    def store(self):
        if self._store is None:
            self._store = self.store_factory(self.index_path / "qdrant")
        return self._store

    def identity(self):
        return dict(schemaVersion=SCHEMA_VERSION, modelId=MODEL_ID, modelVersion=self.version,
                    modelPath=str(self.model_path), dimensions=DIMENSIONS)

    def read_manifest(self):
        if not self.manifest_path.exists():
            return None
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("collection"), str):
                raise ValueError("invalid collection")
            if not data["collection"].startswith("reason_vectors_"):
                raise ValueError("invalid collection prefix")
            if normalize_labels(data["labels"]) != data["labels"] or not isinstance(data["updatedAt"], str):
                raise ValueError("invalid metadata")
            return data
        except (ValueError, KeyError, TypeError, OSError) as exc:
            raise VectorError("manifest.json 损坏或无法读取，请备份索引目录后重建") from exc

    def matches(self, manifest):
        return all(manifest.get(k) == v for k, v in self.identity().items())

    def encode(self, texts):
        if self._model is None:
            self._model = self.model_factory(self.model_path)
        vectors = self._model.encode(texts)
        if len(vectors) != len(texts):
            raise VectorError("模型返回的向量数量不匹配")
        for vector in vectors:
            if len(vector) != DIMENSIONS or any(not math.isfinite(float(x)) for x in vector):
                raise VectorError("模型向量维度错误或包含非有限数值")
            if not any(float(x) != 0 for x in vector):
                raise VectorError("模型返回零向量，无法计算余弦相似度")
        return vectors

    def write_manifest(self, manifest):
        # Same-directory replace is atomic. Flush data before publishing collection pointer.
        fd, temporary = tempfile.mkstemp(prefix="manifest-", suffix=".tmp", dir=self.index_path)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(manifest, handle, ensure_ascii=False, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.manifest_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def cleanup(self, collection):
        try:
            self.store.delete(collection)
        except Exception as exc:
            print(f"清理未使用集合失败 ({collection}): {exc}", file=sys.stderr)

    def refresh(self, labels):
        labels = normalize_labels(labels)
        old = self.read_manifest()
        reusable = old is not None and self.matches(old)
        if reusable and old["labels"] == labels:
            return {"indexedCount": len(labels), "updatedAt": old["updatedAt"]}
        name = "reason_vectors_" + uuid.uuid4().hex
        try:
            self.store.create(name)
            common = sorted(set(labels).intersection(old["labels"])) if reusable else []
            vectors = self.store.vectors(old["collection"], common) if common else {}
            vectors = {label: vector for label, vector in vectors.items() if label in common}
            missing = [label for label in labels if label not in vectors]
            if missing:
                vectors.update(zip(missing, self.encode(missing)))
            if vectors:
                self.store.put(name, vectors)
            manifest = dict(self.identity(), collection=name, labels=labels,
                            updatedAt=datetime.now(timezone.utc).isoformat())
            self.write_manifest(manifest)
        except Exception:
            self.cleanup(name)
            raise
        if old:
            self.cleanup(old["collection"])
        return {"indexedCount": len(labels), "updatedAt": manifest["updatedAt"]}

    def search(self, text, limit, min_score, labels):
        valid = set(normalize_labels(labels))
        if not isinstance(text, str) or not text.strip():
            raise VectorError("搜索 text 必须是非空字符串")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise VectorError("limit 必须是正整数")
        if min_score is not None and (isinstance(min_score, bool)
                or not isinstance(min_score, (int, float)) or not math.isfinite(min_score)
                or not -1 <= min_score <= 1):
            raise VectorError("minScore 必须是 null 或 [-1, 1] 范围内的有限数字")
        manifest = self.read_manifest()
        if manifest is None:
            raise VectorError("向量索引尚未初始化，请先执行 refresh")
        if not self.matches(manifest):
            raise VectorError("索引模型版本、路径、维度或协议已变化，请先执行 refresh 重建索引")
        valid.intersection_update(manifest["labels"])
        if not valid:
            return {"items": []}
        vector = self.encode([text.strip()])[0]
        # Retrieve the whole collection, filter current labels, THEN truncate top k.
        hits = self.store.query(manifest["collection"], vector, len(manifest["labels"]))
        items = [{"label": label, "score": score} for label, score in hits
                 if label in valid and math.isfinite(score)
                 and (min_score is None or score >= min_score)]
        items.sort(key=lambda item: (-item["score"], item["label"]))
        return {"items": items[:limit]}

    def dispatch(self, request):
        action = request.get("action")
        if action == "refresh":
            return self.refresh(request.get("labels"))
        if action == "search":
            return self.search(request.get("text"), request.get("limit"),
                               request.get("minScore"), request.get("labels"))
        raise VectorError("不支持的 action，仅支持 refresh 和 search")

    def close(self):
        if self._store is not None:
            self._store.close()


def reject_json_constant(value):
    raise json.JSONDecodeError(f"非标准 JSON 数值: {value}", "", 0)


def serve(input_stream, output_stream, engine_factory=Engine):
    engine = None
    try:
        for line in input_stream:
            request_id = None
            try:
                request = json.loads(line, parse_constant=reject_json_constant)
                if not isinstance(request, dict):
                    raise VectorError("请求必须是 JSON 对象")
                request_id = request.get("id")
                # Route accidental dependency prints away from the JSONL transport.
                from contextlib import redirect_stdout
                with redirect_stdout(sys.stderr):
                    if engine is None:
                        engine = engine_factory()
                    result = engine.dispatch(request)
                response = {"id": request_id, "result": result}
            except json.JSONDecodeError:
                response = {"id": request_id, "error": "请求不是有效的 JSON"}
            except VectorError as exc:
                response = {"id": request_id, "error": str(exc)}
            except Exception as exc:
                print(f"向量操作异常: {type(exc).__name__}: {exc}", file=sys.stderr)
                response = {"id": request_id, "error": "本地向量操作失败，请查看 worker 标准错误日志；旧索引保持有效（如已存在）"}
            output_stream.write(json.dumps(response, ensure_ascii=False, allow_nan=False) + "\n")
            output_stream.flush()
    finally:
        if engine is not None:
            from contextlib import redirect_stdout
            with redirect_stdout(sys.stderr):
                engine.close()


if __name__ == "__main__":
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    serve(sys.stdin, sys.stdout)
