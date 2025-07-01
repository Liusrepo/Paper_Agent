"""Data Models

Core data structures for the paper analysis system.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Optional, Dict, Any


class DownloadStatus(Enum):
    """PDF download status."""
    PENDING = "pending"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    FAILED = "failed"
    SKIPPED = "skipped"


class JournalType(Enum):
    """Journal publisher type."""
    ELSEVIER = "elsevier"
    NON_ELSEVIER = "non_elsevier"
    UNKNOWN = "unknown"


@dataclass
class Material:
    """Material information from Materials Project."""
    
    material_id: str
    formula: str
    crystal_system: str = ""
    space_group: str = ""
    band_gap: float = 0.0
    formation_energy: float = 0.0
    density: float = 0.0
    is_magnetic: bool = False
    theoretical: bool = True
    method: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'material_id': self.material_id,
            'formula': self.formula,
            'crystal_system': self.crystal_system,
            'space_group': self.space_group,
            'band_gap': self.band_gap,
            'formation_energy': self.formation_energy,
            'density': self.density,
            'is_magnetic': self.is_magnetic,
            'theoretical': self.theoretical,
            'method': self.method
        }


@dataclass
class Paper:
    """Research paper metadata."""
    
    title: str
    doi: str = ""
    authors: List[str] = field(default_factory=list)
    journal: str = ""
    year: int = 0
    citation_count: int = 0
    abstract: str = ""
    
    # Processing metadata
    paper_index: int = 0
    relevance_score: float = 0.0
    priority_score: float = 0.0
    is_selected: bool = False
    journal_type: JournalType = JournalType.UNKNOWN
    download_status: DownloadStatus = DownloadStatus.PENDING
    
    # File information
    pdf_filename: str = ""
    pdf_size: int = 0
    
    # Analysis status
    analysis_completed: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for CSV export."""
        return {
            'paper_index': self.paper_index,
            'title': self.title,
            'doi': self.doi,
            'authors': '; '.join(self.authors),
            'journal': self.journal,
            'year': self.year,
            'citation_count': self.citation_count,
            'abstract': self.abstract,
            'relevance_score': self.relevance_score,
            'priority_score': self.priority_score,
            'is_selected': self.is_selected,
            'journal_type': self.journal_type.value,
            'download_status': self.download_status.value,
            'pdf_filename': self.pdf_filename,
            'pdf_size': self.pdf_size,
            'analysis_completed': self.analysis_completed
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Paper':
        """Create Paper from dictionary."""
        authors = data.get('authors', '')
        if isinstance(authors, str):
            authors = [a.strip() for a in authors.split(';') if a.strip()]
        
        return cls(
            title=data.get('title', ''),
            doi=data.get('doi', ''),
            authors=authors,
            journal=data.get('journal', ''),
            year=int(data.get('year', 0) or 0),
            citation_count=int(data.get('citation_count', 0) or 0),
            abstract=data.get('abstract', ''),
            paper_index=int(data.get('paper_index', 0) or 0),
            relevance_score=float(data.get('relevance_score', 0.0) or 0.0),
            priority_score=float(data.get('priority_score', 0.0) or 0.0),
            is_selected=bool(data.get('is_selected', False)),
            journal_type=JournalType(data.get('journal_type', 'unknown')),
            download_status=DownloadStatus(data.get('download_status', 'pending')),
            pdf_filename=data.get('pdf_filename', ''),
            pdf_size=int(data.get('pdf_size', 0) or 0),
            analysis_completed=bool(data.get('analysis_completed', False))
        )


@dataclass
class PaperAnalysis:
    """Structured analysis of a research paper."""
    
    paper_index: int
    title: str
    doi: str
    
    # Analysis sections
    research_background: str = ""
    innovation_points: str = ""
    preparation_conditions: str = ""
    characterization_results: str = ""
    conclusions: str = ""
    
    # Metadata
    analysis_timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for CSV export."""
        return {
            'paper_index': self.paper_index,
            'title': self.title,
            'doi': self.doi,
            'research_background': self.research_background,
            'innovation_points': self.innovation_points,
            'preparation_conditions': self.preparation_conditions,
            'characterization_results': self.characterization_results,
            'conclusions': self.conclusions,
            'analysis_timestamp': self.analysis_timestamp
        }
    
    def to_readable_text(self) -> str:
        """Convert to human-readable text format."""
        sections = [
            f"Paper Title: {self.title}",
            f"DOI: {self.doi}",
            f"Analysis Time: {self.analysis_timestamp}",
            "",
            "=" * 60,
            "",
            "Research Background:",
            self.research_background or "Information not available",
            "",
            "Research Innovation Points:",
            self.innovation_points or "Information not available",
            "",
            "Preparation Conditions (detailed for reproducibility):",
            self.preparation_conditions or "Information not available",
            "",
            "Characterization Results (detailed for review):",
            self.characterization_results or "Information not available",
            "",
            "Conclusions:",
            self.conclusions or "Information not available",
            "",
            "=" * 60
        ]
        return "\n".join(sections)


@dataclass
class ProcessingStats:
    """Statistics for the processing workflow."""
    
    material_id: str
    start_time: datetime
    target_paper_count: int = 0  # User's original request
    
    # Search statistics
    search_query: str = ""
    papers_found: int = 0
    papers_selected: int = 0
    
    # Download statistics
    elsevier_attempts: int = 0
    elsevier_success: int = 0
    anna_archive_attempts: int = 0
    anna_archive_success: int = 0
    
    # Analysis statistics
    analysis_attempts: int = 0
    analysis_success: int = 0
    
    # File paths
    output_dir: Optional[Path] = None
    papers_csv: Optional[Path] = None
    analysis_csv: Optional[Path] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for reporting."""
        return {
            'material_id': self.material_id,
            'start_time': self.start_time.isoformat(),
            'target_paper_count': self.target_paper_count,
            'search_query': self.search_query,
            'papers_found': self.papers_found,
            'papers_selected': self.papers_selected,
            'elsevier_attempts': self.elsevier_attempts,
            'elsevier_success': self.elsevier_success,
            'anna_archive_attempts': self.anna_archive_attempts,
            'anna_archive_success': self.anna_archive_success,
            'analysis_attempts': self.analysis_attempts,
            'analysis_success': self.analysis_success,
            'total_pdfs_downloaded': self.elsevier_success + self.anna_archive_success,
            'success_rate': self.get_success_rate()
        }
    
    def get_success_rate(self) -> float:
        """Calculate overall success rate."""
        total_attempts = self.elsevier_attempts + self.anna_archive_attempts
        total_success = self.elsevier_success + self.anna_archive_success
        return (total_success / total_attempts * 100) if total_attempts > 0 else 0.0 