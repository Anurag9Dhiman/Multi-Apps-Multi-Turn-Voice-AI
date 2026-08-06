from .app import app

__all__ = ["app", "main"]


def main() -> None:
    import uvicorn

    uvicorn.run("mock_agent_backend:app", host="0.0.0.0", port=8000, reload=True)
