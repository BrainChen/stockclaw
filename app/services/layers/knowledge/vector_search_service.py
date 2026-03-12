import warnings
from typing import Any, Tuple

import numpy as np
from scipy.sparse import hstack
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer

try:
    import faiss
except Exception:
    faiss = None


class VectorSearchService:
    def __init__(self) -> None:
        if faiss is None:
            raise RuntimeError("FAISS 未安装，请先执行 `pip install faiss-cpu`。")

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
        self.svd_model: TruncatedSVD | None = None
        self.faiss_index = None
        self.embedding_dim = 0

    @property
    def ready(self) -> bool:
        return self.faiss_index is not None and int(self.faiss_index.ntotal) > 0

    @property
    def index_size(self) -> int:
        return int(self.faiss_index.ntotal) if self.faiss_index is not None else 0

    def clear(self) -> None:
        self.svd_model = None
        self.faiss_index = None
        self.embedding_dim = 0

    def build_index(self, corpus: list[str]) -> None:
        if not corpus:
            self.clear()
            return

        word_matrix = self.word_vectorizer.fit_transform(corpus)
        char_matrix = self.char_vectorizer.fit_transform(corpus)
        combined_matrix = hstack([word_matrix, char_matrix], format="csr", dtype=np.float32)
        dense_vectors = self._build_dense_embeddings(combined_matrix)
        self._build_faiss_index(dense_vectors)

    def search(self, normalized_query: str, candidate_k: int) -> Tuple[np.ndarray, np.ndarray]:
        word_query = self.word_vectorizer.transform([normalized_query])
        char_query = self.char_vectorizer.transform([normalized_query])
        query_sparse = hstack([word_query, char_query], format="csr", dtype=np.float32)
        query_vector = self._project_query_vector(query_sparse)
        if query_vector.size == 0:
            return np.array([[]], dtype=np.float32), np.array([[]], dtype=np.int64)
        return self.faiss_index.search(query_vector, candidate_k)

    def export_state(self) -> dict[str, Any]:
        return {
            "word_vectorizer": self.word_vectorizer,
            "char_vectorizer": self.char_vectorizer,
            "svd_model": self.svd_model,
            "embedding_dim": self.embedding_dim,
        }

    def load_state(self, state: dict[str, Any], loaded_faiss_index: Any) -> bool:
        loaded_word_vectorizer = state.get("word_vectorizer")
        loaded_char_vectorizer = state.get("char_vectorizer")
        if loaded_word_vectorizer is None or loaded_char_vectorizer is None:
            return False
        self.word_vectorizer = loaded_word_vectorizer
        self.char_vectorizer = loaded_char_vectorizer
        self.svd_model = state.get("svd_model")
        self.faiss_index = loaded_faiss_index
        self.embedding_dim = int(getattr(loaded_faiss_index, "d", state.get("embedding_dim", 0) or 0))
        return True

    def _build_dense_embeddings(self, sparse_matrix) -> np.ndarray:
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

    def _project_query_vector(self, sparse_query) -> np.ndarray:
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
