"""Compatibility entrypoint for local development.

The actual FastAPI application lives in grant_tool.main.
"""

from grant_tool.main import app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("grant_tool.main:app", host="0.0.0.0", port=8000, reload=True)
