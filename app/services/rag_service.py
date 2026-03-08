import json
import hashlib
import pickle
import re
import threading
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix, hstack
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer

from app.core.config import get_settings

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

try:
    import faiss
except Exception:
    faiss = None


@dataclass
class Chunk:
    text: str
    source: str
    path: str
    chunk_id: str
    section: str
    start_offset: int
    end_offset: int


class RAGService:
    INDEX_SCHEMA_VERSION = 1
    SUPPORTED_EXTENSIONS = (".md", ".txt", ".json", ".csv", ".pdf")
    QUERY_STOP_PHRASES = (
        "什么是",
        "请问",
        "如何",
        "为什么",
        "一下",
        "解释",
        "概念",
        "区别",
        "分析",
        "介绍",
        "有没有",
    )

    def __init__(self, kb_dir: str | None = None) -> None:
        if faiss is None:
            raise RuntimeError("FAISS 未安装，请先执行 `pip install faiss-cpu`。")

        self.settings = get_settings()
        self.kb_dir = Path(kb_dir or self.settings.kb_dir)
        self.index_dir = Path(self.settings.kb_index_dir)
        self.faiss_index_path = self.index_dir / "kb.faiss"
        self.meta_path = self.index_dir / "kb_meta.json"
        self.objects_path = self.index_dir / "kb_objects.pkl"
        self.chunks: List[Chunk] = []
        self.indexed_files = 0
        self.loaded_from_disk = False
        self.vector_backend = "faiss"
        self.word_vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            lowercase=True,
            max_features=120000,
        )
        self.char_vectorizer = TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(2, 4),
            lowercase=True,
            max_features=150000,
        )
        self.word_matrix = None
        self.char_matrix = None
        self.combined_matrix: csr_matrix | None = None
        self.svd_model: TruncatedSVD | None = None
        self.faiss_index = None
        self.embedding_dim = 0
        self._lock = threading.RLock()
        if not self._load_persisted_index():
            self.reindex(force=True)

    def reindex(self, force: bool = False) -> Dict[str, Any]:
        with self._lock:
            if not force and self.chunks:
                return self.get_stats()

            if not self.kb_dir.exists():
                self._reset_index()
                return self.get_stats()

            loaded_chunks: List[Chunk] = []
            indexed_files = 0
            file_markers: List[str] = []
            for file_path in self._iter_supported_files(self.kb_dir):
                file_markers.append(self._build_file_marker(file_path))
                text = self._load_document(file_path)
                if not text:
                    continue
                indexed_files += 1
                loaded_chunks.extend(self._chunk_text(text=text, file_path=file_path))
                if len(loaded_chunks) >= self.settings.kb_max_chunks:
                    loaded_chunks = loaded_chunks[: self.settings.kb_max_chunks]
                    break

            self.chunks = loaded_chunks
            self.indexed_files = indexed_files
            if not self.chunks:
                self._clear_vector_state()
                return self.get_stats()

            corpus = [self._chunk_to_corpus_text(chunk) for chunk in self.chunks]
            self.word_matrix = self.word_vectorizer.fit_transform(corpus)
            self.char_matrix = self.char_vectorizer.fit_transform(corpus)
            self.combined_matrix = hstack([self.word_matrix, self.char_matrix], format="csr", dtype=np.float32)
            dense_vectors = self._build_dense_embeddings(self.combined_matrix)
            self._build_faiss_index(dense_vectors)
            corpus_signature = self._build_corpus_signature(file_markers=file_markers)
            self._persist_index(corpus_signature=corpus_signature)
            self.loaded_from_disk = False
            return self.get_stats()

    def get_stats(self) -> Dict[str, Any]:
        return {
            "kb_dir": str(self.kb_dir),
            "indexed_files": self.indexed_files,
            "indexed_chunks": len(self.chunks),
            "supported_extensions": list(self.SUPPORTED_EXTENSIONS),
            "chunk_size": self.settings.kb_chunk_size,
            "chunk_overlap": self.settings.kb_chunk_overlap,
            "vector_backend": self.vector_backend,
            "index_size": int(self.faiss_index.ntotal) if self.faiss_index is not None else 0,
            "embedding_dim": self.embedding_dim,
            "index_dir": str(self.index_dir),
            "loaded_from_disk": self.loaded_from_disk,
        }

    def retrieve(self, query: str, top_k: int = 6, min_score: float = 0.08) -> List[Dict[str, Any]]:
        with self._lock:
            if (
                self.word_vectorizer is None
                or self.char_vectorizer is None
                or self.faiss_index is None
                or self.faiss_index.ntotal == 0
                or not self.chunks
            ):
                return []

            normalized_query = self._normalize_text(query)
            if not normalized_query:
                return []

            word_query = self.word_vectorizer.transform([normalized_query])
            char_query = self.char_vectorizer.transform([normalized_query])
            query_sparse = hstack([word_query, char_query], format="csr", dtype=np.float32)
            query_vector = self._project_query_vector(query_sparse)
            if query_vector.size == 0:
                return []

            candidate_k = min(max(top_k * 8, top_k + 12), len(self.chunks))
            distances, indices = self.faiss_index.search(query_vector, candidate_k)
            query_terms = self._extract_query_terms(normalized_query)
            keyword_bonus = self._keyword_overlap_bonus(query_terms) if query_terms else None
            title_bonus = self._title_overlap_bonus(query_terms) if query_terms else None

            candidates: list[tuple[int, float]] = []
            for raw_idx, raw_score in zip(indices[0], distances[0]):
                idx = int(raw_idx)
                if idx < 0 or idx >= len(self.chunks):
                    continue
                score = float(raw_score)
                if keyword_bonus is not None:
                    score += float(keyword_bonus[idx])
                if title_bonus is not None:
                    score += float(title_bonus[idx])
                candidates.append((idx, score))

            candidates.sort(key=lambda item: item[1], reverse=True)

            if query_terms:
                min_score = max(0.03, min_score)
            results: List[Dict[str, Any]] = []
            seen_keys: set[tuple[str, int]] = set()
            for idx, score in candidates:
                if score < min_score:
                    continue

                chunk = self.chunks[idx]
                dedupe_key = (chunk.path, chunk.start_offset // 40)
                if dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)

                title = chunk.source if not chunk.section else f"{chunk.source} · {chunk.section}"
                results.append(
                    {
                        "source_type": "kb",
                        "title": title,
                        "content": chunk.text,
                        "score": round(score, 4),
                        "url": None,
                        "path": chunk.path,
                        "chunk_id": chunk.chunk_id,
                    }
                )
                if len(results) >= top_k:
                    break
            return results

    def _reset_index(self) -> None:
        self.chunks = []
        self.indexed_files = 0
        self._clear_vector_state()

    def _clear_vector_state(self) -> None:
        self.word_matrix = None
        self.char_matrix = None
        self.combined_matrix = None
        self.svd_model = None
        self.faiss_index = None
        self.embedding_dim = 0
        self.loaded_from_disk = False

    def _iter_supported_files(self, directory: Path) -> Iterable[Path]:
        for file_path in sorted(directory.rglob("*")):
            if file_path.name.lower() == "readme.md":
                continue
            if file_path.is_file() and file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                yield file_path

    def _load_document(self, file_path: Path) -> str:
        suffix = file_path.suffix.lower()
        try:
            if suffix in [".md", ".txt"]:
                return file_path.read_text(encoding="utf-8", errors="ignore")
            if suffix == ".json":
                return self._load_json(file_path)
            if suffix == ".csv":
                return self._load_csv(file_path)
            if suffix == ".pdf":
                return self._load_pdf(file_path)
        except Exception:
            return ""
        return ""

    def _load_json(self, file_path: Path) -> str:
        data = json.loads(file_path.read_text(encoding="utf-8", errors="ignore"))
        flattened: List[str] = []
        self._flatten_json(data, flattened, prefix="")
        return "\n".join(flattened)

    def _flatten_json(self, value: Any, collector: List[str], prefix: str) -> None:
        if isinstance(value, dict):
            for key, val in value.items():
                new_prefix = f"{prefix}.{key}" if prefix else str(key)
                self._flatten_json(val, collector, new_prefix)
            return
        if isinstance(value, list):
            for idx, val in enumerate(value):
                new_prefix = f"{prefix}[{idx}]"
                self._flatten_json(val, collector, new_prefix)
            return
        collector.append(f"{prefix}: {value}")

    def _load_csv(self, file_path: Path, max_rows: int = 3000) -> str:
        frame = pd.read_csv(file_path, dtype=str, nrows=max_rows).fillna("")
        if frame.empty:
            return ""
        lines = []
        for _, row in frame.iterrows():
            row_text = " | ".join([f"{col}={str(row[col]).strip()}" for col in frame.columns])
            lines.append(row_text)
        return "\n".join(lines)

    def _load_pdf(self, file_path: Path) -> str:
        if PdfReader is None:
            return ""
        reader = PdfReader(str(file_path))
        texts = []
        for page in reader.pages:
            texts.append(page.extract_text() or "")
        return "\n".join(texts)

    def _chunk_text(self, text: str, file_path: Path) -> List[Chunk]:
        clean_text = self._normalize_text(text)
        if not clean_text:
            return []

        sections = self._split_markdown_sections(clean_text)
        chunks: List[Chunk] = []
        relative_path = file_path.as_posix()
        source = file_path.name
        section_idx = 0
        for section, section_text in sections:
            for start, end, window in self._build_windows(section_text):
                if not window:
                    continue
                chunk_id = f"{source}:{section_idx}:{start}-{end}"
                chunks.append(
                    Chunk(
                        text=window,
                        source=source,
                        path=relative_path,
                        chunk_id=chunk_id,
                        section=section,
                        start_offset=start,
                        end_offset=end,
                    )
                )
            section_idx += 1
        return chunks

    def _split_markdown_sections(self, text: str) -> List[Tuple[str, str]]:
        lines = text.splitlines()
        sections: List[Tuple[str, str]] = []
        current_title = "文档摘要"
        buffer: List[str] = []

        for line in lines:
            heading_match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
            if heading_match:
                section_text = "\n".join(buffer).strip()
                if section_text:
                    sections.append((current_title, section_text))
                current_title = heading_match.group(1).strip()
                buffer = []
                continue
            buffer.append(line)

        section_text = "\n".join(buffer).strip()
        if section_text:
            sections.append((current_title, section_text))
        return sections or [("文档摘要", text)]

    def _build_windows(self, section_text: str) -> List[Tuple[int, int, str]]:
        clean = self._normalize_text(section_text)
        if not clean:
            return []

        chunk_size = max(150, int(self.settings.kb_chunk_size))
        overlap = max(0, int(self.settings.kb_chunk_overlap))
        if overlap >= chunk_size:
            overlap = chunk_size // 4
        stride = max(1, chunk_size - overlap)

        windows: List[Tuple[int, int, str]] = []
        position = 0
        while position < len(clean):
            end = min(position + chunk_size, len(clean))
            if end < len(clean):
                boundary = self._find_window_boundary(clean, position, end)
                if boundary > position + 80:
                    end = boundary

            window = clean[position:end].strip()
            if window:
                windows.append((position, end, window))
            if end >= len(clean):
                break
            position += stride
        return windows

    def _find_window_boundary(self, text: str, start: int, end: int) -> int:
        candidate = -1
        for token in ["\n", "。", "！", "？", ".", ";", "；"]:
            idx = text.rfind(token, start, end)
            candidate = max(candidate, idx)
        return candidate + 1 if candidate >= 0 else end

    def _build_dense_embeddings(self, sparse_matrix: csr_matrix) -> np.ndarray:
        if sparse_matrix.shape[0] == 0:
            return np.zeros((0, 0), dtype=np.float32)

        n_samples, n_features = sparse_matrix.shape
        max_components = min(384, n_samples - 1, n_features - 1)
        if max_components >= 64:
            self.svd_model = TruncatedSVD(n_components=max_components, random_state=42)
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=RuntimeWarning)
                dense_vectors = self.svd_model.fit_transform(sparse_matrix).astype(np.float32)
        else:
            self.svd_model = None
            dense_vectors = sparse_matrix.toarray().astype(np.float32)

        if dense_vectors.ndim == 1:
            dense_vectors = dense_vectors.reshape(1, -1)
        dense_vectors = np.ascontiguousarray(dense_vectors, dtype=np.float32)
        if dense_vectors.shape[1] == 0:
            return np.zeros((0, 0), dtype=np.float32)

        dense_vectors = np.nan_to_num(dense_vectors, nan=0.0, posinf=0.0, neginf=0.0)
        faiss.normalize_L2(dense_vectors)
        return dense_vectors

    def _project_query_vector(self, sparse_query: csr_matrix) -> np.ndarray:
        if sparse_query.shape[0] == 0:
            return np.zeros((0, 0), dtype=np.float32)

        if self.svd_model is not None:
            dense_query = self.svd_model.transform(sparse_query).astype(np.float32)
        else:
            dense_query = sparse_query.toarray().astype(np.float32)

        if dense_query.ndim == 1:
            dense_query = dense_query.reshape(1, -1)
        dense_query = np.ascontiguousarray(dense_query, dtype=np.float32)
        if dense_query.shape[1] == 0:
            return np.zeros((0, 0), dtype=np.float32)
        dense_query = np.nan_to_num(dense_query, nan=0.0, posinf=0.0, neginf=0.0)
        faiss.normalize_L2(dense_query)
        return dense_query

    def _build_faiss_index(self, dense_vectors: np.ndarray) -> None:
        if dense_vectors.size == 0 or dense_vectors.shape[1] == 0:
            self.faiss_index = None
            self.embedding_dim = 0
            return

        self.embedding_dim = int(dense_vectors.shape[1])
        self.faiss_index = faiss.IndexFlatIP(self.embedding_dim)
        self.faiss_index.add(dense_vectors)

    def _build_file_marker(self, file_path: Path) -> str:
        try:
            stat = file_path.stat()
            relative_path = file_path.resolve().relative_to(self.kb_dir.resolve()).as_posix()
            return f"{relative_path}|{stat.st_size}|{int(stat.st_mtime_ns)}"
        except Exception:
            return file_path.as_posix()

    def _build_corpus_signature(self, file_markers: List[str] | None = None) -> str:
        markers = file_markers if file_markers is not None else [
            self._build_file_marker(path) for path in self._iter_supported_files(self.kb_dir)
        ]
        digest = hashlib.sha256()
        digest.update(f"schema={self.INDEX_SCHEMA_VERSION}|".encode("utf-8"))
        digest.update(f"chunk_size={self.settings.kb_chunk_size}|".encode("utf-8"))
        digest.update(f"chunk_overlap={self.settings.kb_chunk_overlap}|".encode("utf-8"))
        digest.update(f"kb_max_chunks={self.settings.kb_max_chunks}|".encode("utf-8"))
        digest.update(f"supported={','.join(self.SUPPORTED_EXTENSIONS)}|".encode("utf-8"))
        for marker in sorted(markers):
            digest.update(marker.encode("utf-8", errors="ignore"))
            digest.update(b"\n")
        return digest.hexdigest()

    def _persist_index(self, corpus_signature: str) -> None:
        if self.faiss_index is None:
            return

        self.index_dir.mkdir(parents=True, exist_ok=True)
        faiss_tmp = self.faiss_index_path.with_suffix(self.faiss_index_path.suffix + ".tmp")
        objects_tmp = self.objects_path.with_suffix(self.objects_path.suffix + ".tmp")
        meta_tmp = self.meta_path.with_suffix(self.meta_path.suffix + ".tmp")

        faiss.write_index(self.faiss_index, str(faiss_tmp))
        with objects_tmp.open("wb") as fp:
            pickle.dump(
                {
                    "word_vectorizer": self.word_vectorizer,
                    "char_vectorizer": self.char_vectorizer,
                    "svd_model": self.svd_model,
                    "chunks": self.chunks,
                    "indexed_files": self.indexed_files,
                    "embedding_dim": self.embedding_dim,
                },
                fp,
                protocol=pickle.HIGHEST_PROTOCOL,
            )
        meta = {
            "schema_version": self.INDEX_SCHEMA_VERSION,
            "kb_dir": str(self.kb_dir.resolve()),
            "index_dir": str(self.index_dir.resolve()),
            "corpus_signature": corpus_signature,
            "chunk_size": self.settings.kb_chunk_size,
            "chunk_overlap": self.settings.kb_chunk_overlap,
            "kb_max_chunks": self.settings.kb_max_chunks,
            "indexed_files": self.indexed_files,
            "indexed_chunks": len(self.chunks),
            "vector_backend": self.vector_backend,
            "embedding_dim": self.embedding_dim,
        }
        meta_tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        faiss_tmp.replace(self.faiss_index_path)
        objects_tmp.replace(self.objects_path)
        meta_tmp.replace(self.meta_path)

    def _load_persisted_index(self) -> bool:
        with self._lock:
            if not self.meta_path.exists() or not self.faiss_index_path.exists() or not self.objects_path.exists():
                return False
            if not self.kb_dir.exists():
                return False

            try:
                meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
                if int(meta.get("schema_version", -1)) != self.INDEX_SCHEMA_VERSION:
                    return False
                if Path(meta.get("kb_dir", "")).resolve() != self.kb_dir.resolve():
                    return False
                if int(meta.get("chunk_size", -1)) != int(self.settings.kb_chunk_size):
                    return False
                if int(meta.get("chunk_overlap", -1)) != int(self.settings.kb_chunk_overlap):
                    return False
                if int(meta.get("kb_max_chunks", -1)) != int(self.settings.kb_max_chunks):
                    return False

                current_signature = self._build_corpus_signature()
                if meta.get("corpus_signature") != current_signature:
                    return False

                loaded_faiss_index = faiss.read_index(str(self.faiss_index_path))
                with self.objects_path.open("rb") as fp:
                    payload = pickle.load(fp)

                loaded_chunks = payload.get("chunks") or []
                loaded_word_vectorizer = payload.get("word_vectorizer")
                loaded_char_vectorizer = payload.get("char_vectorizer")
                loaded_svd_model = payload.get("svd_model")
                loaded_indexed_files = int(payload.get("indexed_files", 0))

                if loaded_word_vectorizer is None or loaded_char_vectorizer is None:
                    return False
                if len(loaded_chunks) != int(loaded_faiss_index.ntotal):
                    return False

                self.word_vectorizer = loaded_word_vectorizer
                self.char_vectorizer = loaded_char_vectorizer
                self.svd_model = loaded_svd_model
                self.chunks = loaded_chunks
                self.indexed_files = loaded_indexed_files
                self.word_matrix = None
                self.char_matrix = None
                self.combined_matrix = None
                self.faiss_index = loaded_faiss_index
                self.embedding_dim = int(loaded_faiss_index.d)
                self.loaded_from_disk = True
                return True
            except Exception:
                return False

    def _extract_query_terms(self, query: str) -> List[str]:
        normalized = query.lower()
        segments = re.findall(r"[a-z][a-z0-9\.\-_]{1,}|[\u4e00-\u9fff]{2,}", normalized)
        terms: set[str] = set()
        for segment in segments:
            cleaned = segment
            for phrase in self.QUERY_STOP_PHRASES:
                cleaned = cleaned.replace(phrase, " ")
            for token in cleaned.split():
                if len(token) >= 2:
                    terms.add(token)
        return sorted(terms)

    def _keyword_overlap_bonus(self, query_terms: List[str]) -> np.ndarray:
        bonuses = np.zeros(len(self.chunks))
        if not query_terms:
            return bonuses

        for idx, chunk in enumerate(self.chunks):
            lowered_chunk = chunk.text.lower()
            overlap_count = 0
            for term in query_terms:
                if term in lowered_chunk:
                    overlap_count += 1
            bonuses[idx] = min(0.18, overlap_count * 0.06)
        return bonuses

    def _title_overlap_bonus(self, query_terms: List[str]) -> np.ndarray:
        bonuses = np.zeros(len(self.chunks))
        if not query_terms:
            return bonuses

        for idx, chunk in enumerate(self.chunks):
            section_text = f"{chunk.source} {chunk.section}".lower()
            overlap_count = 0
            for term in query_terms:
                if term in section_text:
                    overlap_count += 1
            bonuses[idx] = min(0.08, overlap_count * 0.04)
        return bonuses

    def _chunk_to_corpus_text(self, chunk: Chunk) -> str:
        section_prefix = f"{chunk.section} " if chunk.section else ""
        return f"{section_prefix}{chunk.text}"

    def _normalize_text(self, text: str) -> str:
        text = text.replace("\u3000", " ")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\r\n?", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
