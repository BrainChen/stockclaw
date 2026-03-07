import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.core.config import get_settings

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None


@dataclass
class Chunk:
    text: str
    source: str
    path: str
    chunk_id: str


class RAGService:
    SUPPORTED_EXTENSIONS = (".md", ".txt", ".json", ".csv", ".pdf")

    def __init__(self, kb_dir: str | None = None) -> None:
        self.settings = get_settings()
        self.kb_dir = Path(kb_dir or self.settings.kb_dir)
        self.chunks: List[Chunk] = []
        self.indexed_files = 0
        self.word_vectorizer = TfidfVectorizer(ngram_range=(1, 2), max_features=100000)
        self.char_vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), max_features=120000)
        self.word_matrix = None
        self.char_matrix = None
        self._lock = threading.RLock()
        self.reindex(force=True)

    def reindex(self, force: bool = False) -> Dict[str, Any]:
        with self._lock:
            if not force and self.chunks:
                return self.get_stats()

            if not self.kb_dir.exists():
                self.chunks = []
                self.indexed_files = 0
                self.word_matrix = None
                self.char_matrix = None
                return self.get_stats()

            loaded_chunks: List[Chunk] = []
            indexed_files = 0
            for file_path in self._iter_supported_files(self.kb_dir):
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
                self.word_matrix = None
                self.char_matrix = None
                return self.get_stats()

            corpus = [chunk.text for chunk in self.chunks]
            self.word_matrix = self.word_vectorizer.fit_transform(corpus)
            self.char_matrix = self.char_vectorizer.fit_transform(corpus)
            return self.get_stats()

    def get_stats(self) -> Dict[str, Any]:
        return {
            "kb_dir": str(self.kb_dir),
            "indexed_files": self.indexed_files,
            "indexed_chunks": len(self.chunks),
            "supported_extensions": list(self.SUPPORTED_EXTENSIONS),
        }

    def retrieve(self, query: str, top_k: int = 6, min_score: float = 0.08) -> List[Dict]:
        with self._lock:
            if self.word_matrix is None or self.char_matrix is None or not self.chunks:
                return []

            query = query.strip()
            if not query:
                return []

            word_query = self.word_vectorizer.transform([query])
            char_query = self.char_vectorizer.transform([query])
            word_scores = cosine_similarity(word_query, self.word_matrix).flatten()
            char_scores = cosine_similarity(char_query, self.char_matrix).flatten()
            scores = 0.55 * word_scores + 0.45 * char_scores

            ranked_idx = scores.argsort()[::-1][:top_k]
            results = []
            for idx in ranked_idx:
                if scores[idx] < min_score:
                    continue
                chunk = self.chunks[idx]
                results.append(
                    {
                        "source_type": "kb",
                        "title": chunk.source,
                        "content": chunk.text,
                        "score": float(scores[idx]),
                        "url": None,
                    }
                )
            return results

    def _iter_supported_files(self, directory: Path) -> Iterable[Path]:
        for file_path in sorted(directory.rglob("*")):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS:
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
        flattened = []
        self._flatten_json(data, flattened, prefix="")
        return "\n".join(flattened)

    def _flatten_json(self, value: Any, collector: List[str], prefix: str) -> None:
        if isinstance(value, dict):
            for key, val in value.items():
                new_prefix = f"{prefix}.{key}" if prefix else str(key)
                self._flatten_json(val, collector, new_prefix)
        elif isinstance(value, list):
            for idx, val in enumerate(value):
                new_prefix = f"{prefix}[{idx}]"
                self._flatten_json(val, collector, new_prefix)
        else:
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

        chunk_size = self.settings.kb_chunk_size
        overlap = self.settings.kb_chunk_overlap
        if overlap >= chunk_size:
            overlap = max(0, chunk_size // 5)
        stride = max(1, chunk_size - overlap)

        chunks: List[Chunk] = []
        position = 0
        relative_path = file_path.as_posix()
        source = file_path.name
        while position < len(clean_text):
            end = min(position + chunk_size, len(clean_text))
            window = clean_text[position:end].strip()
            if window:
                chunk_id = f"{source}:{position}-{end}"
                chunks.append(Chunk(text=window, source=source, path=relative_path, chunk_id=chunk_id))
            if end == len(clean_text):
                break
            position += stride
        return chunks

    def _normalize_text(self, text: str) -> str:
        text = text.replace("\u3000", " ")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
