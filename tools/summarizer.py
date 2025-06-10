import logging
from utils.config import Config
from pydantic import PrivateAttr
from typing import Any, Optional
from utils.patterns import singleton
from langchain_ollama.llms import OllamaLLM
from schemas.search_schema import ExtractionResult
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import BaseTool, ArgsSchema
from schemas.cite_summarize_schema import SummarizerInput
from langchain_core.callbacks import CallbackManagerForToolRun, AsyncCallbackManagerForToolRun

logging.basicConfig(
    level=logging.INFO,
    format="[SUMMARIZER]: [%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
LOGGER = logging.getLogger("summarizer")
SUMMARIZER_MODEL = Config.summarizer_settings.get("model")
TOP_P = Config.summarizer_settings.get("top_p")
TEMPERATURE = Config.summarizer_settings.get("temperature")
TOP_K = Config.summarizer_settings.get("top_k")
MAX_TOKENS = Config.summarizer_settings.get("max_tokens")


@singleton
class Summarizer(BaseTool):
    name: str = "Summarizer"
    description: str = "Useful for when you need to summarize key points into a single source of truth."
    args_schema: ArgsSchema = SummarizerInput
    return_direct: bool = True
    _logger: Any = PrivateAttr()

    def __init__(self, verbose: bool = False, **kwargs: Any):
        super().__init__(**kwargs)
        self.verbose = verbose
        self._logger = LOGGER
        self._client = OllamaLLM(model=SUMMARIZER_MODEL)

    def _run(self, clean_extracts: ExtractionResult, run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        # Implement the summarizer logic here
        # This is a placeholder implementation
        return "This is a summary of the extracted information."

    def _arun(self, clean_extracts: ExtractionResult, run_manager: Optional[AsyncCallbackManagerForToolRun] = None) -> str:
        # Implement the asynchronous summarizer logic here
        # This is a placeholder implementation
        return "This is a summary of the extracted information."  # type
