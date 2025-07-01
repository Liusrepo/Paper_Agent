"""CSV Status Manager

Manages paper status synchronization between CSV and actual download states.
"""

import csv
import logging
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime

from models import Paper, DownloadStatus, JournalType

class CSVStatusManager:
    """Manages CSV status tracking and synchronization."""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def update_paper_status(self, papers: List[Paper], phase: str) -> None:
        """Update paper status based on processing phase.
        
        Args:
            papers: List of papers to update
            phase: Processing phase ("selected", "downloading", "completed")
        """
        if phase == "selected":
            self._mark_selected_papers(papers)
        elif phase == "downloading":
            self._mark_downloading_papers(papers)
        elif phase == "completed":
            self._mark_completed_papers(papers)
    
    def _mark_selected_papers(self, papers: List[Paper]) -> None:
        """Mark papers as selected for download."""
        for paper in papers:
            if paper.is_selected:
                paper.download_status = DownloadStatus.PENDING
                self.logger.debug(f"Marked as pending download: {paper.title[:50]}...")
    
    def _mark_downloading_papers(self, papers: List[Paper]) -> None:
        """Mark papers as currently downloading."""
        for paper in papers:
            if paper.download_status == DownloadStatus.PENDING:
                paper.download_status = DownloadStatus.DOWNLOADING
    
    def _mark_completed_papers(self, papers: List[Paper]) -> None:
        """Mark papers based on final download results."""
        for paper in papers:
            if paper.download_status == DownloadStatus.DOWNLOADING:
                # Check if PDF file actually exists
                if paper.pdf_filename and paper.pdf_size > 0:
                    paper.download_status = DownloadStatus.DOWNLOADED
                    self.logger.debug(f"Confirmed downloaded: {paper.title[:50]}...")
                else:
                    paper.download_status = DownloadStatus.FAILED
                    self.logger.debug(f"Confirmed download failed: {paper.title[:50]}...")
    
    def save_papers_with_status(self, papers: List[Paper], output_file: Path, 
                               material_id: str) -> Path:
        """Save papers with current status to CSV file.
        
        Args:
            papers: List of papers with status
            output_file: Output CSV file path
            material_id: Material ID for filename generation
            
        Returns:
            Path: Actual CSV file path
        """
        # Generate timestamped filename as required
        if not output_file.name.startswith(material_id):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{material_id}-{timestamp}.csv"
            actual_file = output_file.parent / filename
        else:
            actual_file = output_file
        
        # Prepare CSV data with enhanced status information
        csv_data = []
        for paper in papers:
            row = paper.to_dict()
            
            # Add enhanced status fields
            row.update({
                'pending_download': self._is_pending_download(paper),
                'is_elsevier': paper.journal_type == JournalType.ELSEVIER,
                'download_status_cn': self._get_status_chinese(paper.download_status),
                'status_timestamp': datetime.now().isoformat()
            })
            
            csv_data.append(row)
        
        # Write CSV file
        if csv_data:
            with open(actual_file, 'w', newline='', encoding='utf-8') as f:
                fieldnames = list(csv_data[0].keys())
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(csv_data)
        
        self.logger.info(f"CSV status saved: {actual_file}")
        return actual_file
    
    def load_papers_with_status(self, csv_file: Path) -> List[Paper]:
        """Load papers from CSV file with status information.
        
        Args:
            csv_file: CSV file to load
            
        Returns:
            List[Paper]: Papers with loaded status
        """
        papers = []
        
        try:
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                
                for row in reader:
                    # Convert CSV row back to Paper object
                    paper = Paper.from_dict(row)
                    papers.append(paper)
            
            self.logger.info(f"Loaded {len(papers)} paper statuses from CSV")
            
        except Exception as e:
            self.logger.error(f"CSV loading failed: {e}")
        
        return papers
    
    def _is_pending_download(self, paper: Paper) -> bool:
        """Check if paper is pending download."""
        return (paper.is_selected and 
                paper.download_status in [DownloadStatus.PENDING, DownloadStatus.DOWNLOADING])
    
    def _get_status_chinese(self, status: DownloadStatus) -> str:
        """Get status description in English."""
        status_map = {
            DownloadStatus.PENDING: "Pending",
            DownloadStatus.DOWNLOADING: "Downloading", 
            DownloadStatus.DOWNLOADED: "Downloaded",
            DownloadStatus.FAILED: "Failed",
            DownloadStatus.SKIPPED: "Skipped"
        }
        return status_map.get(status, "Unknown status")
    
    def generate_status_report(self, papers: List[Paper]) -> Dict[str, Any]:
        """Generate comprehensive status report.
        
        Args:
            papers: List of papers to analyze
            
        Returns:
            Dict: Status report with detailed statistics
        """
        total_papers = len(papers)
        
        # Count by status
        status_counts = {}
        for status in DownloadStatus:
            status_counts[status.value] = sum(1 for p in papers if p.download_status == status)
        
        # Count by journal type
        elsevier_papers = sum(1 for p in papers if p.journal_type == JournalType.ELSEVIER)
        non_elsevier_papers = total_papers - elsevier_papers
        
        # Download success rates
        total_attempted = status_counts.get('downloading', 0) + status_counts.get('downloaded', 0) + status_counts.get('failed', 0)
        success_rate = (status_counts.get('downloaded', 0) / total_attempted * 100) if total_attempted > 0 else 0
        
        # Selected papers statistics
        selected_papers = sum(1 for p in papers if p.is_selected)
        
        report = {
            'total_papers': total_papers,
            'selected_papers': selected_papers,
            'elsevier_papers': elsevier_papers,
            'non_elsevier_papers': non_elsevier_papers,
            'status_breakdown': status_counts,
            'download_success_rate': round(success_rate, 2),
            'pending_downloads': status_counts.get('pending', 0),
            'completed_downloads': status_counts.get('downloaded', 0),
            'failed_downloads': status_counts.get('failed', 0),
            'report_timestamp': datetime.now().isoformat()
        }
        
        return report
    
    def validate_exact_count(self, papers: List[Paper], target_count: int) -> Dict[str, Any]:
        """Validate that exactly target_count papers are downloaded.
        
        Args:
            papers: List of papers to validate
            target_count: Expected number of downloaded papers
            
        Returns:
            Dict: Validation result with details
        """
        downloaded_papers = [p for p in papers if p.download_status == DownloadStatus.DOWNLOADED]
        actual_count = len(downloaded_papers)
        
        validation = {
            'target_count': target_count,
            'actual_count': actual_count,
            'exact_match': actual_count == target_count,
            'difference': actual_count - target_count,
            'status': 'SUCCESS' if actual_count == target_count else 'MISMATCH',
            'downloaded_papers': [
                {
                    'title': p.title[:50] + '...' if len(p.title) > 50 else p.title,
                    'journal': p.journal,
                    'pdf_filename': p.pdf_filename,
                    'pdf_size': p.pdf_size
                }
                for p in downloaded_papers
            ]
        }
        
        if not validation['exact_match']:
            self.logger.warning(f"Count mismatch: expected {target_count}, actual {actual_count}")
        else:
            self.logger.info(f"✅ Count validation passed: exactly {target_count} papers")
        
        return validation 