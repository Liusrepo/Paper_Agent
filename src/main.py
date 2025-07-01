"""Main Program

Orchestrates the complete workflow for material paper analysis.
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from config import load_config
from core.file_manager import FileManager
from clients.materials_client import MaterialsProjectClient
from clients.search_client import SemanticScholarClient
from clients.gemini_client import GeminiClient
from clients.download_client import DownloadManager
from models import ProcessingStats, DownloadStatus
from utils import setup_logger, validate_material_id, ProgressTracker


class MaterialAnalysisWorkflow:
    """Main workflow coordinator."""
    
    def __init__(self):
        # Load configuration
        self.api_config, self.app_config = load_config()
        
        # Setup logging
        self.logger = setup_logger()
        
        # Initialize managers and clients
        self.file_manager = FileManager(self.app_config.base_dir)
        self._init_clients()
    
    def _init_clients(self):
        """Initialize API clients with rate limiters."""
        from utils import RateLimiter
        
        # Create rate limiters
        rate_limits = self.app_config.rate_limits
        mp_limiter = RateLimiter(rate_limits['materials_project'])
        search_limiter = RateLimiter(rate_limits['semantic_scholar'])
        gemini_limiter = RateLimiter(rate_limits['gemini'])
        
        # Initialize clients
        self.materials_client = MaterialsProjectClient(self.api_config, mp_limiter)
        self.search_client = SemanticScholarClient(self.api_config, search_limiter)
        self.gemini_client = GeminiClient(self.api_config, gemini_limiter)
        self.download_manager = DownloadManager(self.api_config)
        
        # Initialize smart download manager with institutional IP setting
        from core.smart_download_manager import SmartDownloadManager
        self.smart_download_manager = SmartDownloadManager(
            self.download_manager, 
            within_institutional_ip=self.app_config.within_institutional_ip
        )
    
    async def run_analysis(self, material_id: str, target_paper_count: int) -> bool:
        """Run complete analysis workflow.
        
        Args:
            material_id: Materials Project ID
            target_paper_count: Number of papers to download and analyze
            
        Returns:
            bool: True if workflow completed successfully
        """
        # Validate inputs
        try:
            material_id = validate_material_id(material_id)
        except ValueError as e:
            print(f"❌ Invalid material ID: {e}")
            return False
        
        if target_paper_count < 1:
            print("❌ Paper count must be at least 1")
            return False
        
        # Initialize processing stats
        stats = ProcessingStats(
            material_id=material_id,
            start_time=datetime.now()
        )
        # Store the original user request
        stats.target_paper_count = target_paper_count
        
        print(f"\n🚀 Starting Analysis for {material_id}")
        print(f"📊 Target: {target_paper_count} papers")
        print("=" * 60)
        
        try:
            # Step 1: Get material information
            material = await self._get_material_info(material_id)
            if not material:
                return False
            
            # Step 2: Create workspace
            workspace = self.file_manager.create_material_workspace(material_id)
            stats.output_dir = workspace
            
            # Save material info
            self.file_manager.save_material_info(workspace, material)
            self.materials_client.display_material_info(material)
            
            # Step 3: Search for papers
            papers = await self._search_papers(material['formula'], target_paper_count, stats)
            if not papers:
                return False
            
            # Save initial papers list  
            papers_csv = self.file_manager.save_papers_csv(workspace, papers, material_id, "initial_papers.csv")
            stats.papers_csv = papers_csv
            
            # Step 4: Select papers using Gemini
            selected_papers = await self._select_papers(papers, material['formula'], target_paper_count, stats)
            if not selected_papers:
                return False
            
            # Step 5: Download PDFs
            successful_downloads = await self._download_pdfs(selected_papers, workspace, material_id, stats)
            if not successful_downloads:
                print("❌ No PDFs downloaded successfully")
                return False
            
            # Step 6: Analyze PDFs
            analyses = await self._analyze_pdfs(successful_downloads, material['formula'], workspace, material_id, stats)
            
            # Step 7: Generate final outputs
            await self._generate_outputs(workspace, material, papers, analyses, stats)
            
            # Final summary
            self._print_final_summary(stats, successful_downloads, analyses)
            
            return True
            
        except Exception as e:
            self.logger.error(f"Workflow failed: {e}")
            print(f"❌ Analysis failed: {e}")
            return False
    
    async def _get_material_info(self, material_id: str):
        """Get material information."""
        print("🔬 Fetching material information...")
        
        try:
            material = await self.materials_client.get_material_info(material_id)
            return material
        except Exception as e:
            self.logger.error(f"Failed to get material info: {e}")
            print(f"❌ Failed to get material information: {e}")
            return None
    
    async def _search_papers(self, formula: str, target_count: int, stats: ProcessingStats):
        """Search for papers."""
        print(f"\n📚 Searching papers for {formula}...")
        
        # Strictly follow requirement: search num*2 papers
        search_count = target_count * 2
        stats.search_query = f"{formula} synthesis characterization properties"
        
        try:
            papers = await self.search_client.search_papers(formula, search_count)
            stats.papers_found = len(papers)
            
            if papers:
                self.search_client.display_search_results(papers, formula)
                return papers
            else:
                print("❌ No relevant papers found")
                return []
                
        except Exception as e:
            self.logger.error(f"Paper search failed: {e}")
            print(f"❌ Paper search failed: {e}")
            return []
    
    async def _select_papers(self, papers, formula: str, target_count: int, stats: ProcessingStats):
        """Select papers using Gemini AI."""
        print(f"\n🧠 Selecting papers using Gemini AI for {target_count} target downloads...")
        
        try:
            # Pass the target count directly - Gemini will handle backup selection internally
            selected_papers = await self.gemini_client.select_papers(
                papers, formula, target_count
            )
            
            stats.papers_selected = len(selected_papers)
            
            if selected_papers:
                print(f"✅ Selected {len(selected_papers)} papers for download")
                return selected_papers
            else:
                print("❌ No papers selected by Gemini")
                return []
                
        except Exception as e:
            self.logger.error(f"Paper selection failed: {e}")
            print(f"❌ Paper selection failed: {e}")
            return []
    
    async def _download_pdfs(self, selected_papers, workspace: Path, material_id: str, stats: ProcessingStats):
        """Download PDFs using smart download manager."""
        print(f"\n📥 Smart downloading to ensure exact target...")
        
        # Use smart download manager to ensure exact user-requested count
        # Pass the original user target, not the inflated selected count
        successful_downloads = await self.smart_download_manager.ensure_target_downloads(
            selected_papers, workspace, material_id, stats.target_paper_count
        )
        
        # Update stats and rename PDF files to ensure sequential numbering
        pdf_folder = workspace / f"{material_id}-pdf"
        for paper in successful_downloads:
            if paper.journal_type.value == "elsevier":
                stats.elsevier_success += 1
            else:
                stats.anna_archive_success += 1
            
            # Rename PDF file if needed to match the reassigned index
            if paper.pdf_filename:
                old_path = pdf_folder / paper.pdf_filename
                new_filename = f"paper_{paper.paper_index:02d}_{self._safe_filename(paper.title[:30])}.pdf"
                new_path = pdf_folder / new_filename
                
                if old_path.exists() and old_path != new_path:
                    old_path.rename(new_path)
                    paper.pdf_filename = new_filename
        
        print(f"📊 Final result: {len(successful_downloads)} PDFs downloaded")
        
        return successful_downloads
    
    async def _analyze_pdfs(self, downloaded_papers, formula: str, workspace: Path, material_id: str, stats: ProcessingStats):
        """Analyze PDFs using Gemini."""
        print(f"\n🧠 Analyzing {len(downloaded_papers)} PDFs with Gemini...")
        
        analyses = []
        failed_count = 0
        progress = ProgressTracker(len(downloaded_papers), "Analyzing PDFs")
        
        for paper in downloaded_papers:
            progress.update()
            stats.analysis_attempts += 1
            
            # Smart retry mechanism for failed analyses
            analysis_success = False
            max_retries = 2  # Try up to 2 additional times
            retry_delays = [10, 30]  # 10s first retry, 30s second retry
            
            for attempt in range(max_retries + 1):  # 0, 1, 2 (3 total attempts)
                try:
                    pdf_folder_name = f"{material_id}-pdf"
                    pdf_path = workspace / pdf_folder_name / paper.pdf_filename
                    
                    analysis = await self.gemini_client.analyze_pdf(
                        paper, pdf_path, formula
                    )
                    
                    analyses.append(analysis)
                    paper.analysis_completed = True
                    stats.analysis_success += 1
                    analysis_success = True
                    
                    # Save individual analysis
                    self.file_manager.save_analysis_text(workspace, analysis)
                    
                    if attempt == 0:
                        print(f"   ✅ {paper.paper_index:02d}: Analysis completed")
                    else:
                        print(f"   ✅ {paper.paper_index:02d}: Analysis completed (retry {attempt})")
                    
                    break  # Success, exit retry loop
                    
                except Exception as e:
                    error_msg = str(e)
                    self.logger.error(f"Analysis attempt {attempt + 1} failed for paper {paper.paper_index}: {e}")
                    
                    # Check if this is a retryable error
                    is_retryable = self._is_retryable_error(error_msg)
                    
                    if attempt < max_retries and is_retryable:
                        delay = retry_delays[attempt]
                        print(f"   ⏳ {paper.paper_index:02d}: Analysis failed (attempt {attempt + 1}), retrying in {delay}s...")
                        print(f"      Error: {error_msg[:80]}...")
                        await asyncio.sleep(delay)
                    else:
                        # Final failure - create fallback analysis
                        print(f"   ❌ {paper.paper_index:02d}: Analysis failed after {attempt + 1} attempts")
                        print(f"      Final error: {error_msg[:80]}...")
                        
                        paper.analysis_completed = False
                        failed_count += 1
                        
                        # Create a fallback analysis for failed cases
                        from models import PaperAnalysis
                        fallback_analysis = PaperAnalysis(
                            paper_index=paper.paper_index,
                            title=paper.title,
                            doi=paper.doi,
                            research_background=f"❌ Automated analysis failed ({attempt + 1} attempts): {error_msg[:100]}",
                            innovation_points="❌ Analysis failed, manual PDF review recommended",
                            preparation_conditions="❌ Analysis failed, manual PDF review recommended",
                            characterization_results="❌ Analysis failed, manual PDF review recommended",
                            conclusions=f"❌ Automated analysis failed, manual PDF analysis required: {paper.pdf_filename}"
                        )
                        analyses.append(fallback_analysis)
                        break
            
            # Rate limiting
            await asyncio.sleep(2)
        
        print(f"\n📊 Analysis Results:")
        print(f"   ✅ Completed: {stats.analysis_success}")
        print(f"   ❌ Failed: {failed_count}")
        
        return analyses
    
    def _is_retryable_error(self, error_msg: str) -> bool:
        """Determine if an error is worth retrying.
        
        Args:
            error_msg: Error message from exception
            
        Returns:
            bool: True if error is likely temporary and worth retrying
        """
        error_lower = error_msg.lower()
        
        # Retryable errors (temporary issues)
        retryable_patterns = [
            # API/Network issues
            '500', '502', '503', '504',  # Server errors
            'internal error', 'server error', 'service unavailable',
            'timeout', 'timed out', 'connection', 'network',
            
            # Rate limiting/Quota issues
            '429', 'too many requests', 'rate limit', 'quota',
            'exceeded', 'limit reached',
            
            # Temporary AI service issues
            'temporarily unavailable', 'try again', 'retry',
            'overloaded', 'busy', 'unavailable'
        ]
        
        # Non-retryable errors (permanent issues)
        non_retryable_patterns = [
            # Authentication/Permission issues
            '401', '403', 'unauthorized', 'forbidden', 'permission denied',
            'invalid api key', 'authentication failed',
            
            # Content/Format issues
            '400', 'bad request', 'invalid input', 'malformed',
            'unsupported format', 'file corrupted', 'pdf corrupted',
            
            # Not found issues
            '404', 'not found', 'file not found', 'does not exist'
        ]
        
        # Check for non-retryable patterns first
        for pattern in non_retryable_patterns:
            if pattern in error_lower:
                return False
        
        # Check for retryable patterns
        for pattern in retryable_patterns:
            if pattern in error_lower:
                return True
        
        # Default: retry unknown errors (conservative approach)
        return True
    
    async def _generate_outputs(self, workspace: Path, material, papers, analyses, stats: ProcessingStats):
        """Generate final output files."""
        print(f"\n💾 Generating output files...")
        
        # Save updated papers CSV following naming requirement
        papers_csv = self.file_manager.save_papers_csv(workspace, papers, material['material_id'])
        stats.papers_csv = papers_csv
        
        # Save analyses CSV
        if analyses:
            analysis_csv = self.file_manager.save_analysis_csv(workspace, analyses, "analysis.csv")
            stats.analysis_csv = analysis_csv
        
        # Save processing stats
        self.file_manager.save_processing_stats(workspace, stats)
        
        # Generate summary report
        self.file_manager.generate_summary_report(workspace, material, papers, analyses, stats)
        
        print(f"   ✅ Results saved to: {workspace}")
    
    def _print_final_summary(self, stats: ProcessingStats, downloaded_papers, analyses):
        """Print final summary."""
        print(f"\n🎊 Analysis Complete!")
        print(f"📁 Output Directory: {stats.output_dir}")
        print(f"📊 Statistics:")
        print(f"   🎯 User Target: {stats.target_paper_count} papers")
        print(f"   🔍 Papers Found: {stats.papers_found}")
        print(f"   📋 Papers Selected: {stats.papers_selected}")
        print(f"   📥 PDFs Downloaded: {len(downloaded_papers)}")
        print(f"   🧠 Analyses Completed: {stats.analysis_success}")
        print(f"   ❌ Analyses Failed: {stats.analysis_attempts - stats.analysis_success}")
        print(f"   📈 Success Rate: {stats.get_success_rate():.1f}%")
        
        if stats.elsevier_success > 0:
            print(f"   📘 Elsevier Downloads: {stats.elsevier_success}")
        if stats.anna_archive_success > 0:
            print(f"   📙 Anna Archive Downloads: {stats.anna_archive_success}")
    
    def _safe_filename(self, text: str) -> str:
        """Convert text to safe filename."""
        import re
        # Remove or replace unsafe characters
        safe = re.sub(r'[<>:"/\\|?*]', '_', text)
        safe = re.sub(r'\s+', '_', safe)  # Replace spaces with underscores
        return safe.strip('._')  # Remove leading/trailing dots and underscores


async def main():
    """Main entry point."""
    print("🔬 Materials Research Paper Analysis System")
    print("=" * 60)
    print("📋 Workflow:")
    print("   1. Input Materials Project ID and paper count")
    print("   2. Fetch material information")
    print("   3. Search papers with Semantic Scholar")
    print("   4. Select papers with Gemini AI")
    print("   5. Download PDFs (Elsevier + Anna Archive)")
    print("   6. Analyze PDFs with Gemini AI")
    print("   7. Generate comprehensive reports")
    print("=" * 60)
    
    # Get user input
    material_id = input("\n🧪 Materials Project ID (e.g., mp-20783 or 20783): ").strip()
    
    if not material_id:
        print("❌ Material ID required")
        return
    
    paper_count_input = input("📊 Number of papers (default 5): ").strip()
    
    try:
        paper_count = int(paper_count_input) if paper_count_input else 5
        paper_count = max(1, paper_count)  # Remove upper limit
    except ValueError:
        paper_count = 5
    
    print(f"\n🎯 Target: {paper_count} papers for {material_id}")
    
    # Initialize and run workflow
    try:
        workflow = MaterialAnalysisWorkflow()
        success = await workflow.run_analysis(material_id, paper_count)
        
        if success:
            print("\n✅ Analysis completed successfully!")
        else:
            print("\n❌ Analysis failed. Check logs for details.")
            
    except KeyboardInterrupt:
        print("\n⏹️ Analysis interrupted by user")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")


if __name__ == "__main__":
    asyncio.run(main()) 