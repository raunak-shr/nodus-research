import logging
from pydantic import PrivateAttr
from typing import List, Dict, Any, Optional
from langchain_core.tools import BaseTool, ArgsSchema
from schemas.cite_summarize_schema import CitationInput
from schemas.search_schema import ExtractionResult, ExtractionItem
from langchain_core.callbacks import CallbackManagerForToolRun, AsyncCallbackManagerForToolRun

logging.basicConfig(
    level=logging.INFO,
    format="[CITER]: [%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
LOGGER = logging.getLogger("citer")


class CitationFormatter(BaseTool):
    name: str = "Citation Formatter"
    description: str = "Useful for when you want to format citations."
    return_direct: bool = True
    args_schema: ArgsSchema = CitationInput
    _logger: Any = PrivateAttr()

    def __init__(self, verbose: bool = False, **kwargs: Any):
        """
        Initialize with extracted results (title + URL).
        """
        super().__init__(**kwargs)
        self.verbose = verbose
        self._logger = LOGGER

    def generate_citations(self, extraction_result: ExtractionResult) -> List[Dict[str, str]]:
        """
        Returns raw citation data as a list of dicts with 'title' and 'url'.
        """
        citations = []
        if self.verbose:
            self._logger.info(f"Generating citations")
        for item in extraction_result.results:
            if item.url:
                citations.append({"title": item.title, "url": item.url})
        return citations

    def format_numbered(self, extraction_result: ExtractionResult) -> str:
        """
        Formats the citations into a numbered inline reference list.

        Returns:
            str: Numbered citations as a formatted string.
        """
        formatted = []
        if self.verbose:
            self._logger.info(f"Formatting citations")
        for idx, item in enumerate(extraction_result.results, start=1):
            if item.url:
                formatted.append(f"[{idx}] {item.title}: {item.url}")
        return "\n".join(formatted)

    def _run(self, extraction_response: ExtractionResult, run_manager: Optional[CallbackManagerForToolRun] = None):
        """
        Use the tool. Returns a list of raw citations and formatted citations.
        """
        raw_results = self.generate_citations(extraction_response)
        formatted_results = self.format_numbered(extraction_response)

        return raw_results, formatted_results

    async def _arun(self, extraction_response: ExtractionResult,
                    run_manager: Optional[AsyncCallbackManagerForToolRun] = None):
        """
        Use the tool asynchronously. Returns a list of raw citations and formatted citations.
        """
        return self._run(extraction_response, run_manager=run_manager.get_sync())


def main():
    extraction_result: ExtractionResult = ExtractionResult(**{'results':
        [
            ExtractionItem(**{"title": "Example Title 1", "url": "http://example.com/1",
                              "raw_content": "Example Content 1", "images": ["hash1"], "score": 0.95}),
            ExtractionItem(**{"title": "Example Title 2", "url": "http://example.com/2",
                              "raw_content": "Example Content 2", "images": ["hash2"], "score": 0.73})
        ]
    })
    formatter = CitationFormatter(verbose=True)
    raw_citations, formatted_citations = formatter.invoke({"extraction_response": extraction_result})
    print("\nRaw Citations:", raw_citations)
    print("Formatted Citations:", formatted_citations)
    print(formatted_citations)


if __name__ == "__main__":
    main()
