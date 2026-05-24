from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Azure OpenAI
    azure_openai_endpoint: str
    azure_openai_api_key: str
    azure_openai_api_version: str = "2024-12-01-preview"
    azure_openai_deployment: str = "gpt-4o"
    azure_openai_mini_deployment: str = "gpt-4o-mini"
    azure_openai_embedding_deployment: str = "text-embedding-3-small"

    # Azure AI Search
    azure_search_endpoint: str
    azure_search_key: str
    azure_search_index_name: str = "campuslmu-regulations-v2"

    # CORS
    allowed_origins: str = "http://localhost:3000"

    # Documents
    documents_dir: str = "../documents"
    lmu_cdn_base_url: str = "https://cms-cdn.lmu.de/media/contenthub/amtliche-veroeffentlichungen"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
