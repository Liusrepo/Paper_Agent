"""Smart Download Manager

Ensures exactly the target number of PDFs are downloaded.
"""

import asyncio
import logging
from typing import List
from pathlib import Path

from models import Paper, DownloadStatus, JournalType
from clients.download_client import DownloadManager
from utils import ProgressTracker


class SmartDownloadManager:
    """Intelligent download manager that guarantees target paper count."""
    
    def __init__(self, download_manager: DownloadManager, within_institutional_ip: bool = False):
        self.download_manager = download_manager
        self.within_institutional_ip = within_institutional_ip
        self.logger = logging.getLogger(__name__)
    
    async def ensure_target_downloads(self, papers: List[Paper], workspace_dir: Path, 
                                    material_id: str, target_count: int) -> List[Paper]:
        """Ensure exactly target_count PDFs are downloaded.
        
        Three-phase approach:
        1. Priority download (Elsevier first)
        2. Smart supplementation 
        3. Precise selection
        
        Returns:
            List[Paper]: Successfully downloaded papers (exactly target_count)
        """
        self.logger.info(f"Smart download: target {target_count} papers")
        
        # Phase 1: Priority download - Elsevier first
        priority_downloads = await self._priority_download_phase(
            papers, workspace_dir, material_id, target_count
        )
        
        if len(priority_downloads) >= target_count:
            return priority_downloads[:target_count]
        
        # Phase 2: Smart supplementation with remaining papers
        remaining_needed = target_count - len(priority_downloads)
        self.logger.info(f"Need {remaining_needed} more papers, starting supplementation")
        
        remaining_papers = [p for p in papers if p not in priority_downloads]
        supplemental_downloads = await self._supplementation_phase(
            remaining_papers, workspace_dir, material_id, remaining_needed
        )
        
        all_downloads = priority_downloads + supplemental_downloads
        
        # Phase 3: Precise selection to meet exact target
        if len(all_downloads) >= target_count:
            return self._precise_selection(all_downloads, target_count)
        else:
            self.logger.warning(f"Could only download {len(all_downloads)} of {target_count} papers")
            return all_downloads
    
    def _calculate_priority_scores(self, papers: List[Paper]) -> List[Paper]:
        """Calculate download priority scores and sort papers.
        
        Priority factors:
        1. Relevance score (from Gemini)
        2. Journal type (Elsevier gets boost for API reliability)
        3. Citation count
        4. Recency (for Elsevier) or Age (for Non-Elsevier)
        
        Returns:
            List[Paper]: Papers sorted by download priority
        """
        scored_papers = []
        
        for paper in papers:
            score = 0.0
            
            # Base relevance score (0-10)
            score += paper.relevance_score
            
            # Journal type bonus
            if paper.journal_type.name == 'ELSEVIER':
                score += 3.0  # Elsevier API more reliable
                # Prefer recent Elsevier papers
                if paper.year >= 2018:
                    score += 1.0
            else:
                score += 1.0  # Non-Elsevier still valuable
                # Prefer older papers for Anna Archive
                if paper.year <= 2019:
                    score += 1.0
                if 2010 <= paper.year <= 2018:
                    score += 0.5
            
            # Citation count bonus (normalized)
            citation_bonus = min(paper.citation_count / 50.0, 2.0)  # Max 2 points
            score += citation_bonus
            
            paper.priority_score = score
            scored_papers.append(paper)
        
        # Sort by priority score descending
        scored_papers.sort(key=lambda p: p.priority_score, reverse=True)
        
        self.logger.info(f"Calculated priority scores: best={scored_papers[0].priority_score:.1f}, worst={scored_papers[-1].priority_score:.1f}")
        return scored_papers
    
    async def _priority_download_phase(self, papers: List[Paper], workspace_dir: Path,
                                     material_id: str, target_count: int) -> List[Paper]:
        """Phase 1: Download highest priority papers (Elsevier first)."""
        
        # Sort papers by priority score
        priority_papers = self._calculate_priority_scores(papers)
        
        # Try to download top papers up to target count
        successful_downloads = []
        total_papers = len(priority_papers)
        
        print(f"📥 Starting download (priority phase): target {target_count} papers, candidates {total_papers} papers")
        
        for idx, paper in enumerate(priority_papers, 1):  # Try ALL available papers
            # Update CSV status to downloading
            paper.download_status = DownloadStatus.DOWNLOADING
            
            # Show detailed download progress
            journal_type = "📘 Elsevier" if paper.journal_type.name == 'ELSEVIER' else "📙 Non-Elsevier"
            print(f"   📄 [{idx:02d}/{total_papers:02d}] {journal_type}: {paper.title[:60]}...")
            print(f"      Journal: {paper.journal}")
            print(f"      DOI: {paper.doi}")
            
            # Generate PDF path
            pdf_path = workspace_dir / f"{material_id}-pdf" / f"paper_{paper.paper_index:02d}_{self._safe_filename(paper.title[:30])}.pdf"
            pdf_path.parent.mkdir(exist_ok=True)
            
            # Attempt download
            success = await self._download_single_paper(paper, pdf_path)
            
            if success:
                paper.download_status = DownloadStatus.DOWNLOADED
                paper.pdf_filename = pdf_path.name
                paper.pdf_size = pdf_path.stat().st_size if pdf_path.exists() else 0
                successful_downloads.append(paper)
                
                from utils import format_file_size
                print(f"      ✅ Download successful: {format_file_size(paper.pdf_size)}")
                
                # Stop if we have enough
                if len(successful_downloads) >= target_count:
                    print(f"   🎯 Target count reached: {len(successful_downloads)}/{target_count}")
                    break
                    
            else:
                paper.download_status = DownloadStatus.FAILED
                print(f"      ❌ Download failed")
            
            # Rate limiting
            await asyncio.sleep(1)
        
        print(f"📊 Priority phase completed: {len(successful_downloads)}/{target_count} papers downloaded successfully")
        return successful_downloads
    
    async def _supplementation_phase(self, remaining_papers: List[Paper], workspace_dir: Path,
                                   material_id: str, needed_count: int) -> List[Paper]:
        """Phase 2: Download from remaining papers to meet target."""
        
        if not remaining_papers or needed_count <= 0:
            return []
        
        # Score remaining papers
        scored_papers = self._calculate_priority_scores(remaining_papers)
        
        successful_downloads = []
        total_remaining = len(scored_papers)
        
        print(f"📥 Supplemental download phase: still need {needed_count} papers, candidates {total_remaining} papers")
        
        for idx, paper in enumerate(scored_papers, 1):  # Try ALL remaining papers
            # Paper status will be updated below
            paper.download_status = DownloadStatus.DOWNLOADING
            
            # Show detailed download progress
            journal_type = "📘 Elsevier" if paper.journal_type.name == 'ELSEVIER' else "📙 Non-Elsevier"
            print(f"   📄 [Supp {idx:02d}/{total_remaining:02d}] {journal_type}: {paper.title[:60]}...")
            print(f"      Journal: {paper.journal}")
            print(f"      DOI: {paper.doi}")
            
            pdf_path = workspace_dir / f"{material_id}-pdf" / f"paper_{paper.paper_index:02d}_{self._safe_filename(paper.title[:30])}.pdf"
            
            success = await self._download_single_paper(paper, pdf_path)
            
            if success:
                paper.download_status = DownloadStatus.DOWNLOADED
                paper.pdf_filename = pdf_path.name
                paper.pdf_size = pdf_path.stat().st_size if pdf_path.exists() else 0
                successful_downloads.append(paper)
                
                from utils import format_file_size
                print(f"      ✅ Supplemental download successful: {format_file_size(paper.pdf_size)}")
                
                if len(successful_downloads) >= needed_count:
                    print(f"   🎯 Supplemental target completed: {len(successful_downloads)}/{needed_count}")
                    break
                    
            else:
                paper.download_status = DownloadStatus.FAILED
                print(f"      ❌ Supplemental download failed")
            
            await asyncio.sleep(1)
        
        print(f"📊 Supplemental phase completed: {len(successful_downloads)}/{needed_count} papers downloaded successfully")
        return successful_downloads
    
    def _precise_selection(self, all_downloads: List[Paper], target_count: int) -> List[Paper]:
        """Phase 3: Select exactly target_count papers from successful downloads."""
        
        if len(all_downloads) <= target_count:
            return all_downloads
        
        # Score and select the best papers
        scored_downloads = self._calculate_priority_scores(all_downloads)
        selected = scored_downloads[:target_count]
        
        # Mark non-selected papers as skipped
        for paper in all_downloads:
            if paper not in selected:
                paper.download_status = DownloadStatus.SKIPPED
        
        # Reassign paper indices for final selection to ensure sequential numbering
        for idx, paper in enumerate(selected, 1):
            paper.paper_index = idx
        
        self.logger.info(f"Final selection: {len(selected)} papers with reassigned indices")
        return selected
    
    async def _download_single_paper(self, paper: Paper, pdf_path: Path) -> bool:
        """Download a single paper using optimal strategy based on institutional IP access."""
        from utils import is_elsevier_doi, format_file_size
        
        paper.download_status = DownloadStatus.DOWNLOADING
        
        try:
            is_elsevier_journal = is_elsevier_doi(paper.doi)
            
            # 🎯 User-configurable download strategy
            if self.within_institutional_ip:
                # 🏛️ Within institutional IP: Elsevier uses official API, non-Elsevier uses Anna Archive
                if is_elsevier_journal:
                    print(f"      📘 Institutional IP: Using Elsevier API download...")
                    success = await self.download_manager.download_paper(paper, pdf_path)
                    
                    if success:
                        paper.download_status = DownloadStatus.DOWNLOADED
                        file_size = pdf_path.stat().st_size if pdf_path.exists() else 0
                        print(f"      ✅ Elsevier download successful: {format_file_size(file_size)}")
                        return True
                    else:
                        print(f"      ❌ Elsevier download failed")
                        return False
                else:
                    # Non-Elsevier journals, use Anna Archive
                    print(f"      📙 Institutional IP: Non-Elsevier journals use Anna Archive...")
                    success = await self.download_manager.download_paper(paper, pdf_path)
                    
                    if success:
                        paper.download_status = DownloadStatus.DOWNLOADED
                        file_size = pdf_path.stat().st_size if pdf_path.exists() else 0
                        print(f"      ✅ Anna Archive download successful: {format_file_size(file_size)}")
                        return True
                    else:
                        print(f"      ❌ Anna Archive download failed")
                        return False
            else:
                # 🏠 Non-institutional IP: All journals use Anna Archive
                print(f"      🌐 Non-institutional IP: Using Anna Archive download...")
                
                # Temporarily change to non-Elsevier type, force use of Anna Archive
                original_journal_type = paper.journal_type
                paper.journal_type = JournalType.NON_ELSEVIER
                
                try:
                    success = await self.download_manager.download_paper(paper, pdf_path)
                    
                    if success:
                        paper.download_status = DownloadStatus.DOWNLOADED
                        file_size = pdf_path.stat().st_size if pdf_path.exists() else 0
                        journal_source = "📘 Elsevier" if is_elsevier_journal else "📙 Non-Elsevier"
                        print(f"      ✅ Anna Archive download successful: {format_file_size(file_size)} ({journal_source})")
                        return True
                    else:
                        journal_source = "📘 Elsevier" if is_elsevier_journal else "📙 Non-Elsevier"
                        print(f"      ❌ Anna Archive download failed ({journal_source})")
                        return False
                        
                finally:
                    # Restore original journal type
                    paper.journal_type = original_journal_type
                    
        except Exception as e:
            self.logger.error(f"Download error for {paper.doi}: {e}")
            print(f"      ❌ Download exception: {e}")
            return False
        finally:
            if paper.download_status == DownloadStatus.DOWNLOADING:
                paper.download_status = DownloadStatus.FAILED
    
    def _safe_filename(self, text: str) -> str:
        """Create safe filename from text."""
        import re
        # Remove or replace unsafe characters
        safe = re.sub(r'[<>:"/\\|?*]', '_', text)
        safe = re.sub(r'\s+', '_', safe)
        return safe[:50]  # Limit length 