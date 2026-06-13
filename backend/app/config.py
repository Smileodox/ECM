from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Azure OpenAI
    azure_openai_endpoint: str
    azure_openai_api_key: str
    azure_openai_api_version: str = "2024-12-01-preview"
    azure_openai_deployment: str = "gpt-5.4"
    azure_openai_mini_deployment: str = "gpt-5.4-nano"
    azure_openai_embedding_deployment: str = "text-embedding-3-small"

    # Available chat models — JSON array of {"id","label"} for Azure OpenAI
    # deployments, or {"id","label","endpoint","key_env"} for Azure AI serverless
    available_models: str = ""

    # Azure AI Search
    azure_search_endpoint: str
    azure_search_key: str
    azure_search_index_name: str = "campuslmu-regulations-v2"
    azure_search_web_index_name: str = "campuslmu-web-v1"

    # Retrieval tuning — Azure semantic reranker score ranges 0..4 (NOT 0..1).
    # Three-band answerability gate (calibrate via `python -m eval.calibration`):
    #   raw_top >= solid     -> SOLID     (answer confidently)
    #   uncertain <= raw_top -> UNCERTAIN (answer with explicit uncertainty + escalation)
    #   raw_top <  uncertain -> ABSTAIN   (hand off, no answer)
    # Calibrated 2026-06 against 50 answerable + 11 unanswerable cases (eval/calibration_report.json).
    # NB: the score gate only catches the near-zero tail — entity/scope-mismatch queries (e.g. a
    # nonexistent program) score 'solid' too. Those are handled by the model's own prompt-abstention
    # plus the grounding verifier, not by the retrieval score.
    reranker_solid_score: float = 1.8
    reranker_uncertain_score: float = 1.0
    # Deprecated — kept so existing .env files don't break. No longer used by the gate.
    reranker_min_score: float = 0.8
    reranker_fallback_score: float = 0.3
    model_context_limit: int = 128_000

    # Legal-safety feature flags (toggle without code changes)
    enable_answerability_gate: bool = True
    enable_grounding_check: bool = True

    # CORS
    allowed_origins: str = "http://localhost:3000"

    # Documents
    documents_dir: str = "../documents"
    lmu_cdn_base_url: str = "https://cms-cdn.lmu.de/media/contenthub/amtliche-veroeffentlichungen"

    # LMU CMS Search API (for Studiengangsfinder crawler)
    lmu_search_user: str = ""
    lmu_search_pass: str = ""

    # Redis (optional — falls back to in-memory cache if unset)
    redis_url: str = ""

    # Feedback — /home/feedback is persistent on Azure App Service
    feedback_dir: str = "/home/feedback"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
