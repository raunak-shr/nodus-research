import os
import logging
from dotenv import load_dotenv
from errors import InternalError

load_dotenv()


class Config:
    version = "1.0.0"
    title = "App Management"

    app_settings = {
        # 'qdrant_test': os.getenv('QDRANT_TEST'),
        # 'qdrant_url': os.getenv('QDRANT_URL'),
        # 'ollama_url': os.getenv('OLLAMA_URL'),
        # 'qdrant_collection': os.getenv('QDRANT_COLLECTION'),
        # 'embedding_model': os.getenv('EMBEDDING_MODEL'),
        # 'max_tokens': int(os.getenv('MAX_TOKENS')),
        # 'top_p': float(os.getenv('TOP_P')),
        # 'temperature': float(os.getenv('TEMPERATURE')),
        # 'top_k': int(os.getenv('TOP_K')),
        # 'model_id': os.getenv('OLLAMA_MODEL'),
        'tavily_key': os.getenv('TAVILY_KEY')
    }

    @classmethod
    def app_settings_validate(cls):
        for k, v in cls.app_settings.items():
            if v is None:
                logging.error(f'Config variable error. {k} cannot be None')
                raise InternalError([{"message": "Server configure error"}])
            else:
                logging.info(f'Config variable {k} is {v}')
