from config.settings import settings

def get_chat_llm(temperature=0):
    if not settings.llm_api_key or not settings.llm_model:
        raise RuntimeError("LLM_API_KEY and LLM_MODEL are required")
    if settings.llm_provider == "google_genai":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(google_api_key=settings.llm_api_key,model=settings.llm_model,temperature=temperature)
    if settings.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(api_key=settings.llm_api_key,model=settings.llm_model,temperature=temperature)
    if settings.llm_provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(api_key=settings.llm_api_key,model=settings.llm_model,temperature=temperature)
    if settings.llm_provider == "nvidia":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(api_key=settings.llm_api_key,model=settings.llm_model,temperature=temperature,base_url="https://integrate.api.nvidia.com/v1",timeout=60)
    raise ValueError(f"Unsupported LLM_PROVIDER: {settings.llm_provider}")
