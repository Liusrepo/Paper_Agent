"""Utility Functions

Common utilities for logging, rate limiting, and helper functions.
"""

import asyncio
import logging
import time
from typing import List, Dict, Any
from functools import wraps

import requests
from requests.adapters import HTTPAdapter

try:
    from urllib3.util.retry import Retry
except ImportError:
    from urllib3.util.retry import Retry


class RateLimiter:
    """Thread-safe rate limiter for API calls."""
    
    def __init__(self, calls_per_minute: int = 60):
        self.calls_per_minute = calls_per_minute
        self.calls = []
        self.last_warning = 0
    
    async def wait_if_needed(self) -> None:
        """Wait if rate limit would be exceeded."""
        now = time.time()
        self.calls = [call_time for call_time in self.calls if now - call_time < 60]
        
        if len(self.calls) >= self.calls_per_minute:
            sleep_time = 60 - (now - self.calls[0])
            if sleep_time > 0:
                if now - self.last_warning > 30:
                    print(f"⏳ Rate limit: waiting {sleep_time:.1f}s...")
                    self.last_warning = now
                await asyncio.sleep(sleep_time)
                now = time.time()
                self.calls = [call_time for call_time in self.calls if now - call_time < 60]
        
        self.calls.append(now)


class NetworkSession:
    """Enhanced HTTP session with retry logic."""
    
    def __init__(self):
        self.session = self._create_session()
    
    def _create_session(self) -> requests.Session:
        """Create session with retry strategy."""
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        session.headers.update({
            'User-Agent': 'MaterialsResearchTool/2.0 (Academic Research)'
        })
        
        return session
    
    async def get(self, url: str, **kwargs) -> requests.Response:
        """Execute GET request with proper error handling."""
        try:
            response = self.session.get(url, timeout=30, **kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            raise NetworkError(f"Request failed: {e}") from e


class NetworkError(Exception):
    """Network-related error."""
    pass


def setup_logger(name: str = "MaterialAnalysis", level: int = logging.INFO) -> logging.Logger:
    """Setup structured logger."""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    
    return logger


def validate_material_id(material_id: str) -> str:
    """Validate and normalize material ID."""
    if not material_id:
        raise ValueError("Material ID cannot be empty")
    
    material_id = material_id.strip()
    
    if material_id.isdigit():
        return f"mp-{material_id}"
    elif material_id.startswith('mp-'):
        return material_id
    else:
        raise ValueError(f"Invalid material ID format: {material_id}")


def is_elsevier_doi(doi: str) -> bool:
    """Check if DOI belongs to Elsevier publisher."""
    if not doi:
        return False
    
    elsevier_prefixes = [
        '10.1016/',  # Elsevier main prefix
        '10.1006/',  # Academic Press
        '10.1053/',  # W.B. Saunders
        '10.1054/',  # Academic Press
        '10.1078/',  # Urban & Fischer
        '10.1529/',  # Cell Press
    ]
    
    non_elsevier_prefixes = [
        '10.1007/',  # Springer
        '10.1021/',  # ACS
        '10.1002/',  # Wiley
        '10.1063/',  # AIP
        '10.1088/',  # IOP
        '10.1103/',  # APS
        '10.1038/',  # Nature
        '10.1126/',  # Science
        '10.3390/',  # MDPI
        '10.1039/',  # RSC
    ]
    
    doi_lower = doi.lower()
    
    # Check if explicitly non-Elsevier
    for prefix in non_elsevier_prefixes:
        if doi_lower.startswith(prefix.lower()):
            return False
    
    # Check if Elsevier
    for prefix in elsevier_prefixes:
        if doi_lower.startswith(prefix.lower()):
            return True
    
    return False


def calculate_text_similarity(text1: str, text2: str) -> float:
    """Calculate similarity between two texts using word overlap."""
    if not text1 or not text2:
        return 0.0
    
    import re
    words1 = set(re.findall(r'\b\w+\b', text1.lower()))
    words2 = set(re.findall(r'\b\w+\b', text2.lower()))
    
    if not words1 or not words2:
        return 0.0
    
    intersection = len(words1 & words2)
    union = len(words1 | words2)
    
    return intersection / union if union > 0 else 0.0


def safe_filename(text: str, max_length: int = 100) -> str:
    """Create safe filename from text."""
    import re
    # Remove/replace invalid characters
    safe_text = re.sub(r'[<>:"/\\|?*]', '_', text)
    safe_text = re.sub(r'\s+', '_', safe_text)
    safe_text = safe_text.strip('._')
    
    if len(safe_text) > max_length:
        safe_text = safe_text[:max_length].rstrip('_')
    
    return safe_text or "unnamed"


def format_file_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    if size_bytes == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB"]
    i = 0
    size = float(size_bytes)
    
    while size >= 1024.0 and i < len(size_names) - 1:
        size /= 1024.0
        i += 1
    
    return f"{size:.1f} {size_names[i]}"


def retry_on_failure(max_retries: int = 3, delay: float = 1.0):
    """Decorator for retrying failed operations."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = Exception("No attempts made")
            
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        await asyncio.sleep(delay * (2 ** attempt))
                    continue
            
            raise last_exception
        return wrapper
    return decorator


def extract_keywords_from_material_formula(formula: str) -> List[str]:
    """Extract search keywords from material formula."""
    import re
    
    # Extract chemical elements
    elements = re.findall(r'[A-Z][a-z]?', formula)
    
    # Add the formula itself
    keywords = [formula]
    
    # Add individual elements for broader search
    keywords.extend(elements)
    
    # Add common material science terms
    keywords.extend(['synthesis', 'characterization', 'properties'])
    
    return keywords


def chunk_list(lst: List[Any], chunk_size: int) -> List[List[Any]]:
    """Split list into chunks of specified size."""
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]


class ProgressTracker:
    """Simple progress tracking for console output."""
    
    def __init__(self, total: int, description: str = "Processing"):
        self.total = total
        self.current = 0
        self.description = description
    
    def update(self, increment: int = 1) -> None:
        """Update progress."""
        self.current += increment
        percentage = (self.current / self.total) * 100 if self.total > 0 else 0
        print(f"\r{self.description}: {self.current}/{self.total} ({percentage:.1f}%)", end="")
        
        if self.current >= self.total:
            print()  # New line when complete
    
    def set_description(self, description: str) -> None:
        """Update description."""
        self.description = description 