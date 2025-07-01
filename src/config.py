"""Configuration Management Module

Handles environment variables, API keys, and application settings.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@dataclass(frozen=True)
class APIConfig:
    """API configuration container."""
    
    materials_project: str
    semantic_scholar: Optional[str]
    gemini: str
    elsevier: str
    anna_archive: Optional[str] = None
    
    def __post_init__(self):
        """Validate required API keys."""
        required_keys = {
            'Materials Project': self.materials_project,
            'Gemini': self.gemini,
            'Elsevier': self.elsevier
        }
        
        missing = [name for name, key in required_keys.items() if not key]
        if missing:
            raise ValueError(f"Missing required API keys: {', '.join(missing)}")


@dataclass(frozen=True)
class AppConfig:
    """Application configuration."""
    
    base_dir: Path = Path("results")
    # Institutional IP setting: configurable for institutional network access
    within_institutional_ip: bool = field(default=False)
    rate_limits: Dict[str, int] = field(default_factory=lambda: {
        'gemini': 15,  # RPM for Gemini 2.5 Flash
        'semantic_scholar': 90,
        'elsevier': 50,
        'materials_project': 60
    })
    file_formats: Dict[str, str] = field(default_factory=lambda: {
        'papers_csv': 'papers_{timestamp}.csv',
        'analysis_csv': 'analysis_{timestamp}.csv',
        'pdf_folder': '{material_id}-pdf',
        'analysis_folder': 'analysis'
    })


def load_config() -> tuple[APIConfig, AppConfig]:
    """Load and validate configuration."""
    api_config = APIConfig(
        materials_project=os.getenv('MP_API_KEY', ''),
        semantic_scholar=os.getenv('SEMANTIC_SCHOLAR_API_KEY'),
        gemini=os.getenv('GEMINI_API_KEY', ''),
        elsevier=os.getenv('ELSEVIER_API_KEY', ''),
        anna_archive=os.getenv('ANNA_ARCHIVE_API_KEY')
    )
    
    # Read institutional IP setting from environment variable
    within_institutional_ip = os.getenv('WITHIN_INSTITUTIONAL_IP', 'false').lower() in ('true', '1', 'yes', 'on')
    
    app_config = AppConfig(within_institutional_ip=within_institutional_ip)
    return api_config, app_config 