"""
Configuration file for the Multi-Agent Medical Chatbot

This file contains all the configuration parameters for the project.

If you want to change the LLM and Embedding model:

you can do it by changing all 'llm' and 'embedding_model' variables present in multiple classes below.

Each llm definition has unique temperature value relevant to the specific class. 
"""

import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

# Load environment variables from .env file
load_dotenv()

# Common LLM configuration
API_KEY = os.getenv("OPENAI_API_KEY")
API_BASE = os.getenv("OPENAI_API_BASE", "https://api.yunnet.top/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "claude-opus-4-8")
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "qwen3-embedding-8b")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "4096"))
# 部分模型（如 qwen3-embedding-8b）不支持 matryoshka 降维，
# 请求中带 dimensions 参数会直接返回 400，需要显式关闭。
EMBEDDING_SUPPORTS_DIMENSIONS = os.getenv("EMBEDDING_SUPPORTS_DIMENSIONS", "false").lower() in ("1", "true", "yes")
# The embedding provider is often a different gateway than the chat LLM one.
# Fall back to the chat gateway when not configured separately.
EMBEDDING_API_BASE = os.getenv("EMBEDDING_API_BASE") or API_BASE
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY") or API_KEY

# Reranker configuration. Defaults to the same gateway as the embedding model,
# since both are typically served by the same local inference endpoint.
RERANKER_MODEL_NAME = os.getenv("RERANKER_MODEL_NAME", "qwen3-reranker-0.6b")
RERANKER_API_BASE = os.getenv("RERANKER_API_BASE") or EMBEDDING_API_BASE
RERANKER_API_KEY = os.getenv("RERANKER_API_KEY") or EMBEDDING_API_KEY

# Document parsing is done by a remote vision model over the OpenAI-compatible
# chat endpoint, one rendered page at a time.
DOC_PARSER_MODEL_NAME = os.getenv("DOC_PARSER_MODEL_NAME", "mineru2.5-pro-2605-1.2b")
DOC_PARSER_API_BASE = os.getenv("DOC_PARSER_API_BASE") or EMBEDDING_API_BASE
DOC_PARSER_API_KEY = os.getenv("DOC_PARSER_API_KEY") or EMBEDDING_API_KEY


def create_embeddings() -> OpenAIEmbeddings:
    """Create the shared OpenAIEmbeddings instance.

    ``dimensions`` is only sent when the provider actually supports it,
    otherwise the request is rejected with a 400.
    """
    kwargs = {
        "model": EMBEDDING_MODEL_NAME,
        "openai_api_key": EMBEDDING_API_KEY,
        "openai_api_base": EMBEDDING_API_BASE,
    }
    if EMBEDDING_SUPPORTS_DIMENSIONS:
        kwargs["dimensions"] = EMBEDDING_DIM
    return OpenAIEmbeddings(**kwargs)

def create_llm(temperature: float = 0.3, model: str | None = None) -> ChatOpenAI:
    """Create a ChatOpenAI instance with common configuration."""
    return ChatOpenAI(
        model=model or MODEL_NAME,
        openai_api_key=API_KEY,
        openai_api_base=API_BASE,
        temperature=temperature,
        streaming=True,
    )

class AgentDecisoinConfig:
    def __init__(self):
        self.llm = create_llm(
            temperature=0.1,
            model=os.getenv("DECISION_MODEL_NAME", MODEL_NAME),
        )  # Deterministic

class ConversationConfig:
    def __init__(self):
        self.llm = create_llm(
            temperature=0.7,
            model=os.getenv("CONVERSATION_MODEL_NAME", MODEL_NAME),
        )  # Creative but factual

class WebSearchConfig:
    def __init__(self):
        self.llm = create_llm(
            temperature=0.3,
            model=os.getenv("WEB_SEARCH_MODEL_NAME", MODEL_NAME),
        )  # Slightly creative but factual
        self.context_limit = 20     # include last 20 messsages (10 Q&A pairs) in history

class RAGConfig:
    def __init__(self):
        self.vector_db_type = "qdrant"
        self.embedding_dim = EMBEDDING_DIM
        self.distance_metric = "Cosine"
        self.use_local = True
        self.vector_local_path = "./data/qdrant_db"
        self.doc_local_path = "./data/docs_db"
        self.parsed_content_dir = "./data/parsed_docs"
        self.url = os.getenv("QDRANT_URL")
        self.api_key = os.getenv("QDRANT_API_KEY")
        self.collection_name = "medical_assistance_rag"
        self.chunk_size = 512
        self.chunk_overlap = 50
        self.embedding_model = create_embeddings()
        self.llm = create_llm(
            temperature=0.3,
            model=os.getenv("RAG_MODEL_NAME", MODEL_NAME),
        )
        self.summarizer_model = create_llm(
            temperature=0.5,
            model=os.getenv("RAG_SUMMARIZER_MODEL_NAME", os.getenv("RAG_MODEL_NAME", MODEL_NAME)),
        )
        self.chunker_model = create_llm(
            temperature=0.0,
            model=os.getenv("RAG_CHUNKER_MODEL_NAME", os.getenv("RAG_MODEL_NAME", MODEL_NAME)),
        )
        self.response_generator_model = create_llm(
            temperature=0.3,
            model=os.getenv("RAG_RESPONSE_MODEL_NAME", os.getenv("RAG_MODEL_NAME", MODEL_NAME)),
        )
        self.top_k = 5
        self.vector_search_type = 'similarity'  # or 'mmr'

        self.huggingface_token = os.getenv("HUGGINGFACE_TOKEN")

        # Reranking is served over an OpenAI-compatible /rerank endpoint.
        self.reranker_model = RERANKER_MODEL_NAME
        self.reranker_api_base = RERANKER_API_BASE
        self.reranker_api_key = RERANKER_API_KEY
        self.reranker_timeout = int(os.getenv("RERANKER_TIMEOUT", "30"))
        self.reranker_top_k = 3
        # Per-document cap sent to the reranker. The model's context is 8192
        # tokens for the whole batch, so leave headroom for several documents.
        self.reranker_max_doc_chars = int(os.getenv("RERANKER_MAX_DOC_CHARS", "4000"))

        # Remote document parser (vision model, page-by-page).
        self.doc_parser_model = DOC_PARSER_MODEL_NAME
        self.doc_parser_api_base = DOC_PARSER_API_BASE
        self.doc_parser_api_key = DOC_PARSER_API_KEY
        self.doc_parser_timeout = int(os.getenv("DOC_PARSER_TIMEOUT", "180"))
        # Total context is 8192; the cap must leave room for the page image.
        self.doc_parser_max_tokens = int(os.getenv("DOC_PARSER_MAX_TOKENS", "4096"))

        self.max_context_length = 8192  # (Change based on your need) # 1024 proved to be too low (retrieved content length > context length = no context added) in formatting context in response_generator code

        self.include_sources = True  # Show links to reference documents and images along with corresponding query response

        # ADJUST ACCORDING TO ASSISTANT'S BEHAVIOUR BASED ON THE DATA INGESTED:
        self.min_retrieval_confidence = 0.40  # The auto routing from RAG agent to WEB_SEARCH agent is dependent on this value

        self.context_limit = 20     # include last 20 messsages (10 Q&A pairs) in history

class MedicalCVConfig:
    def __init__(self):
        self.brain_tumor_model_path = "./agents/image_analysis_agent/brain_tumor_agent/models/brain_tumor_segmentation.pth"
        self.chest_xray_model_path = "./agents/image_analysis_agent/chest_xray_agent/models/covid_chest_xray_model.pth"
        self.skin_lesion_model_path = "./agents/image_analysis_agent/skin_lesion_agent/models/checkpointN25_.pth.tar"
        self.skin_lesion_segmentation_output_path = "./uploads/skin_lesion_output/segmentation_plot.png"
        self.llm = create_llm(
            temperature=0.1,
            model=os.getenv("MEDICAL_CV_MODEL_NAME", MODEL_NAME),
        )  # Keep deterministic for classification tasks

class SpeechConfig:
    def __init__(self):
        self.eleven_labs_api_key = os.getenv("ELEVEN_LABS_API_KEY")  # Replace with your actual key
        self.eleven_labs_voice_id = "21m00Tcm4TlvDq8ikWAM"    # Default voice ID (Rachel)

class ValidationConfig:
    def __init__(self):
        self.require_validation = {
            "CONVERSATION_AGENT": False,
            "RAG_AGENT": False,
            "WEB_SEARCH_AGENT": False,
            "BRAIN_TUMOR_AGENT": True,
            "CHEST_XRAY_AGENT": True,
            "SKIN_LESION_AGENT": True
        }
        self.validation_timeout = 300
        self.default_action = "reject"

class APIConfig:
    def __init__(self):
        self.host = "0.0.0.0"
        self.port = 8000
        self.debug = True
        self.rate_limit = 10
        self.max_image_upload_size = 5  # max upload size in MB

class UIConfig:
    def __init__(self):
        self.theme = "light"
        # self.max_chat_history = 50
        self.enable_speech = True
        self.enable_image_upload = True

class Config:
    def __init__(self):
        self.agent_decision = AgentDecisoinConfig()
        self.conversation = ConversationConfig()
        self.rag = RAGConfig()
        self.medical_cv = MedicalCVConfig()
        self.web_search = WebSearchConfig()
        self.api = APIConfig()
        self.speech = SpeechConfig()
        self.validation = ValidationConfig()
        self.ui = UIConfig()
        self.eleven_labs_api_key = os.getenv("ELEVEN_LABS_API_KEY")
        self.tavily_api_key = os.getenv("TAVILY_API_KEY")
        self.max_conversation_history = 20  # Include last 20 messsages (10 Q&A pairs) in history

# # Example usage
# config = Config()
