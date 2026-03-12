from pathlib import Path
import sys

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.services.layers.knowledge.rag_service import RAGService


def main() -> None:
    service = RAGService()
    stats = service.reindex(force=True)
    print("Knowledge base indexed:")
    for key, value in stats.items():
        print(f"- {key}: {value}")


if __name__ == "__main__":
    main()
