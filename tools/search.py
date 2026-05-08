import logging
import regex as re
from asyncio import to_thread
from pydantic import PrivateAttr
from dotenv import load_dotenv
from tavily import TavilyClient
from utils.config import Config
from langchain.tools import BaseTool
from utils.patterns import singleton
from typing import Literal, Any, Optional
from langchain_core.tools import ToolException
from schemas.search_schema import SearchResult, ExtractionResult
from langchain_core.callbacks import CallbackManagerForToolRun, AsyncCallbackManagerForToolRun

load_dotenv()
TOPIC = Literal["general", "news", "finance"]
tavily_key = Config.app_settings.get('tavily_key', None)
logging.basicConfig(
    level=logging.INFO,
    format="[WEB-SEARCH]: [%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
LOGGER = logging.getLogger("web_search")


@singleton
class WebSearch(BaseTool):
    name: str = "Web Search"
    description: str = "Useful for when you need to search the web for information. Input should be a search query."
    return_direct: bool = True
    _logger: Any = PrivateAttr()

    def __init__(self, user_tavily_key: str = None, verbose: bool = False, **kwargs: Any):
        super().__init__(**kwargs)
        self._client = TavilyClient(api_key=tavily_key if not user_tavily_key else user_tavily_key)
        self.verbose = verbose
        self._logger = LOGGER

    def health_check(self) -> bool | str:
        """
        Standard health check to see if Tavily is up and running
        """
        try:
            self._client.search(query="health check")
            return True
        except Exception as e:
            return "Tavily API error: {}".format(e)

    def search(self, query: str, topic: TOPIC = "general") -> SearchResult:
        """
        Perform a search using the Tavily API client.

        Args:
            query (str): The search query string to execute
            topic (Literal["general", "news", "finance"]): The topic category to search within.

        Returns:
            SearchResult: The search results from Tavily API

        Raises:
            ValueError: If query is empty or invalid
            Exception: If the API request fails
        """

        if not query or not isinstance(query, str):
            raise ValueError("Search query must be a non-empty string")

        valid_topics = {"general", "news", "finance", None}
        if topic not in valid_topics:
            raise ValueError(f"Topic must be one of {valid_topics}")

        try:
            if self.verbose:
                self._logger.info(f"Searching for query: {query}, topic: {topic}")

            search_result = self._client.search(
                query=query.strip(),
                topic=topic
            )
            return search_result
        except Exception as e:
            raise e

    def extract_info(self, search_result: SearchResult) -> ExtractionResult | None:
        """
        Extracts the search results from the Tavily API response.

        Args:
            search_result (SearchResult): The search results from Tavily API

        Returns:
            ExtractionResult: The extracted search results
        """
        results = search_result['results']
        if not results:
            self._logger.info("No results found")
            return None
        if self.verbose:
            self._logger.info(f"Fetching Urls")
        urls: list = [results[x]['url'] for x in range(len(results))]
        extraction_response: ExtractionResult = self._client.extract(urls)
        cleaned_response = self.clean_extracts(extraction_response)
        if not cleaned_response:
            self._logger.error(f"No extracted data")
        return cleaned_response

    def clean_extracts(self, extraction_result: ExtractionResult) -> ExtractionResult:
        """
        Cleans the extracted search results from the Tavily API response removing URLs, Extra new lines, Trademarks,
        Copyright symbols, image links.

        Args:
            extraction_result (ExtractionResult): The extracted search results from Tavily API

        Returns:
            ExtractionResult: The cleaned extracted search results
        """
        if self.verbose:
            self._logger.info(f"Cleaning extracted results")
        for extraction_item in extraction_result["results"]:
            text = extraction_item["raw_content"]
            cleaned_text = re.sub(r'(https|http)?:\/\/(\w|\.|\/|\?|\=|\&|\%|\-)*\b', "", text,
                                  flags=re.MULTILINE)  # urls
            cleaned_text = re.sub(r"!\[\s*\]|\(\s*\)", '', cleaned_text)  # empty brackets ()
            cleaned_text = re.sub(r"(/)", '', cleaned_text)
            cleaned_text = re.sub(r"!\[\s*\]|\(\s*\)", '', cleaned_text)  # empty brackets ()
            cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text)  # xtra new lines
            cleaned_text = re.sub(r"(®|™|©|\bR\b|\bTM\b)", "", cleaned_text).strip()  # trademarks, copyright,
            extraction_item["raw_content"] = cleaned_text
        return extraction_result

    def _run(self, query: str, topic: TOPIC = "general",
             run_manager: Optional[CallbackManagerForToolRun] = None) -> ExtractionResult:
        """
        Use the tool. Runs a web search using the Tavily API client.

        Args:
            query (str): The search query string to execute
            topic (Literal["general", "news", "finance"]): The topic category to search within.

        Returns:
            ExtractionResult: The extracted search results from Tavily API
        """
        try:
            search_result = self.search(query, topic)
            extraction_result = self.extract_info(search_result)
            if self.verbose:
                self._logger.info(f"Search results: {extraction_result}")
            return extraction_result
        except ToolException as e:
            raise ToolException(f"Tool Exception: {e}")

    async def _arun(self, query: str, topic: TOPIC = "general",
                    run_manager: Optional[AsyncCallbackManagerForToolRun] = None) -> ExtractionResult:
        """
        Use the tool asynchronously. Asynchronously runs a web search using the Tavily API client.

        Args:
            query (str): The search query string to execute
            topic (Literal["general", "news", "finance"]): The topic category to search within.

        Returns:
            ExtractionResult: The extracted search results from Tavily API
        """

        return self._run(query, topic, run_manager=run_manager.get_sync())


def main():
    web_search = WebSearch(verbose=True)
    web_search_2 = WebSearch(verbose=True)
    assert web_search == web_search_2, "Singleton failed"
    web_search.invoke("What is the best way to learn English?")


if __name__ == "__main__":
    main()
