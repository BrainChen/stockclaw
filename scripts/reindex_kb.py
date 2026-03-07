from app.services.rag_service import RAGService


def main() -> None:
    service = RAGService()
    stats = service.reindex(force=True)
    print("Knowledge base indexed:")
    for key, value in stats.items():
        print(f"- {key}: {value}")


if __name__ == "__main__":
    main()
