"""API Clients package for paper crawl system."""

from .materials_client import MaterialsProjectClient
from .search_client import SemanticScholarClient
from .gemini_client import GeminiClient
from .download_client import DownloadManager, ElsevierDownloader, AnnaArchiveDownloader

__all__ = [
    'MaterialsProjectClient',
    'SemanticScholarClient', 
    'GeminiClient',
    'DownloadManager',
    'ElsevierDownloader',
    'AnnaArchiveDownloader'
]
