import os

from .app import app

__all__ = ["app", "main"]


def main() -> None:
    sentry_dsn = os.environ.get("SENTRY_DSN")
    if sentry_dsn:
        import sentry_sdk

        sentry_sdk.init(dsn=sentry_dsn, traces_sample_rate=0.1)

    import uvicorn

    uvicorn.run("mock_agent_backend:app", host="0.0.0.0", port=8000, reload=True)
