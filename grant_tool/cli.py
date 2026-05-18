from grant_tool.config import get_settings


def main() -> None:
    settings = get_settings()
    print(f"{settings.app_name} ({settings.app_env})")
    print("Run the API with: uvicorn grant_tool.main:app --reload")
