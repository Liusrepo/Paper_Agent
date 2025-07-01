"""File Management Module

Handles file organization, CSV export/import, and directory structure.
"""

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from models import Paper, PaperAnalysis, ProcessingStats


class FileManager:
    """Manages file operations and directory structure."""
    
    def __init__(self, base_dir: Path = Path("results")):
        self.base_dir = base_dir
        self.base_dir.mkdir(exist_ok=True)
    
    def create_material_workspace(self, material_id: str) -> Path:
        """Create or rebuild workspace directory for a material."""
        # Use persistent workspace name instead of timestamped
        workspace_name = f"{material_id}-workspace"
        workspace_dir = self.base_dir / workspace_name
        
        # Check if workspace already exists
        if workspace_dir.exists():
            print(f"🔍 Detected existing workspace: {workspace_dir}")
            
            # Show workspace summary
            summary = self.get_workspace_summary(workspace_dir, material_id)
            print(f"   📁 Workspace Info:")
            print(f"      Created: {summary['created_time']}")
            print(f"      PDF files: {summary['pdf_count']} files")
            print(f"      Analysis files: {summary['analysis_count']} files")
            print(f"      Total size: {summary['total_size_mb']:.1f} MB")
            
            # Delete and rebuild workspace
            print(f"🗑️ Deleting old workspace and rebuilding...")
            self._delete_workspace(workspace_dir)
            print(f"   ✅ Old workspace deleted")
        
        # Create fresh workspace
        workspace_dir.mkdir(exist_ok=True)
        
        # Create subdirectories following exact naming requirement
        pdf_folder_name = f"{material_id}-pdf"
        pdf_dir = workspace_dir / pdf_folder_name
        analysis_dir = workspace_dir / "analysis"
        
        pdf_dir.mkdir(exist_ok=True)
        analysis_dir.mkdir(exist_ok=True)
        
        print(f"📁 Creating new workspace: {workspace_dir}")
        
        return workspace_dir
    
    def _delete_workspace(self, workspace_dir: Path) -> None:
        """Safely delete workspace directory and all its contents."""
        import shutil
        
        try:
            if workspace_dir.exists():
                shutil.rmtree(workspace_dir)
        except Exception as e:
            print(f"   ⚠️ Problem occurred while deleting workspace: {e}")
            print(f"   💡 Please manually delete folder: {workspace_dir}")
            raise
    
    def save_material_info(self, workspace_dir: Path, material: Dict[str, Any]) -> Path:
        """Save material information to JSON file."""
        info_file = workspace_dir / "material_info.json"
        
        with open(info_file, 'w', encoding='utf-8') as f:
            json.dump(material, f, indent=2, ensure_ascii=False)
        
        return info_file
    
    def save_papers_csv(self, workspace_dir: Path, papers: List[Paper], 
                       material_id: str, custom_filename: Optional[str] = None) -> Path:
        """Save papers list to CSV file following naming requirement."""
        if not papers:
            raise ValueError("Papers list is empty")
        
        if custom_filename:
            csv_file = workspace_dir / custom_filename
        else:
            # Follow exact naming requirement: mp-id-datetime.csv
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{material_id}-{timestamp}.csv"
            csv_file = workspace_dir / filename
        
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            fieldnames = list(papers[0].to_dict().keys())
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for paper in papers:
                writer.writerow(paper.to_dict())
        
        return csv_file
    
    def load_papers_csv(self, csv_file: Path) -> List[Paper]:
        """Load papers from CSV file."""
        papers = []
        
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                papers.append(Paper.from_dict(row))
        
        return papers
    
    def save_analysis_csv(self, workspace_dir: Path, analyses: List[PaperAnalysis],
                         filename: str = "analysis.csv") -> Path:
        """Save analysis results to CSV file."""
        if not analyses:
            raise ValueError("Analysis list is empty")
        
        csv_file = workspace_dir / filename
        
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            fieldnames = list(analyses[0].to_dict().keys())
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for analysis in analyses:
                writer.writerow(analysis.to_dict())
        
        return csv_file
    
    def save_analysis_text(self, workspace_dir: Path, analysis: PaperAnalysis) -> Path:
        """Save individual analysis as human-readable text."""
        analysis_dir = workspace_dir / "analysis"
        
        from utils import safe_filename
        filename = f"paper_{analysis.paper_index:02d}_{safe_filename(analysis.title[:50])}.txt"
        text_file = analysis_dir / filename
        
        with open(text_file, 'w', encoding='utf-8') as f:
            f.write(analysis.to_readable_text())
        
        return text_file
    
    def save_processing_stats(self, workspace_dir: Path, stats: ProcessingStats) -> Path:
        """Save processing statistics."""
        stats_file = workspace_dir / "processing_stats.json"
        
        with open(stats_file, 'w', encoding='utf-8') as f:
            json.dump(stats.to_dict(), f, indent=2, ensure_ascii=False, default=str)
        
        return stats_file
    
    def generate_summary_report(self, workspace_dir: Path, material: Dict[str, Any],
                               papers: List[Paper], analyses: List[PaperAnalysis],
                               stats: ProcessingStats) -> Path:
        """Generate comprehensive summary report."""
        report_file = workspace_dir / "summary_report.txt"
        
        # Calculate statistics
        total_papers = len(papers)
        selected_papers = sum(1 for p in papers if p.is_selected)
        downloaded_papers = sum(1 for p in papers if p.download_status.value == "downloaded")
        analyzed_papers = len(analyses)
        
        elsevier_papers = sum(1 for p in papers if p.journal_type.value == "elsevier" and p.download_status.value == "downloaded")
        non_elsevier_papers = downloaded_papers - elsevier_papers
        
        # Generate report content
        report_content = f"""
# Material Research Paper Analysis Report

## Basic Information
- Material ID: {material['material_id']}
- Chemical Formula: {material['formula']}
- Crystal System: {material['crystal_system']}
- Space Group: {material['space_group']}
- Analysis Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Processing Statistics

### Paper Search and Filtering
- Search Query: {stats.search_query}
- Total Papers Found: {stats.papers_found}
- Papers After Filtering: {selected_papers}
- Target Download Count: {selected_papers}

### PDF Download Results
- Successfully Downloaded: {downloaded_papers} papers
- Elsevier Journals: {elsevier_papers} papers
- Non-Elsevier Journals: {non_elsevier_papers} papers
- Download Success Rate: {stats.get_success_rate():.1f}%

### AI Analysis Results
- Analysis Completed: {analyzed_papers} papers
- Analysis Success Rate: {(analyzed_papers/downloaded_papers*100) if downloaded_papers > 0 else 0:.1f}%

## Detailed Paper List

"""
        
        # Add paper details
        for i, paper in enumerate(papers, 1):
            if paper.is_selected:
                status_icon = "✅" if paper.download_status.value == "downloaded" else "❌"
                analysis_icon = "🧠" if paper.analysis_completed else "⏳"
                
                report_content += f"""
{i:02d}. {status_icon} {analysis_icon} {paper.title}
    Journal: {paper.journal}
    DOI: {paper.doi}
    Citations: {paper.citation_count}
    Year: {paper.year}
    Journal Type: {paper.journal_type.value}
    Download Status: {paper.download_status.value}
    Analysis Status: {'Completed' if paper.analysis_completed else 'Not completed'}
"""
                if paper.pdf_filename:
                    from utils import format_file_size
                    report_content += f"    PDF File: {paper.pdf_filename} ({format_file_size(paper.pdf_size)})\n"
        
        # Add analysis summaries
        if analyses:
            report_content += "\n\n## Key Preparation Process Summary\n\n"
            
            for analysis in analyses:
                report_content += f"""
### Paper {analysis.paper_index}: {analysis.title[:60]}...

**Preparation Conditions Summary:**
{(analysis.preparation_conditions[:300] + '...') if len(analysis.preparation_conditions) > 300 else analysis.preparation_conditions}

**Characterization Results Summary:**
{(analysis.characterization_results[:300] + '...') if len(analysis.characterization_results) > 300 else analysis.characterization_results}

---
"""
        
        # Add file structure
        pdf_folder_name = f"{material['material_id']}-pdf"
        csv_filename = f"{material['material_id']}-{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        report_content += f"""

## Output File Structure

```
{workspace_dir.name}/
├── material_info.json          # Basic material information
├── {csv_filename}              # Detailed paper list
├── analysis.csv               # Analysis results (CSV format)
├── processing_stats.json      # Processing statistics
├── summary_report.txt         # This report
├── {pdf_folder_name}/         # PDF folder
│   ├── paper_01_*.pdf
│   ├── paper_02_*.pdf
│   └── ...
└── analysis/                  # Detailed analysis folder
    ├── paper_01_*.txt
    ├── paper_02_*.txt
    └── ...
```

## Usage Recommendations

1. **View Papers**: Open `{pdf_folder_name}/` folder to view downloaded PDF files
2. **Read Analysis**: Open `analysis/` folder to view detailed AI analysis results
3. **Data Processing**: Use `papers.csv` and `analysis.csv` for further data analysis
4. **Material Info**: View `material_info.json` to understand basic physical and chemical properties of the material

---
Report Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report_content)
        
        return report_file
    
    def get_pdf_path(self, workspace_dir: Path, material_id: str, paper_index: int, title: str) -> Path:
        """Generate PDF file path."""
        from utils import safe_filename
        pdf_folder_name = f"{material_id}-pdf"
        pdf_dir = workspace_dir / pdf_folder_name
        filename = f"paper_{paper_index:02d}_{safe_filename(title[:50])}.pdf"
        return pdf_dir / filename
    
    def cleanup_failed_downloads(self, workspace_dir: Path, material_id: str) -> int:
        """Remove failed/incomplete PDF downloads."""
        pdf_folder_name = f"{material_id}-pdf"
        pdf_dir = workspace_dir / pdf_folder_name
        if not pdf_dir.exists():
            return 0
        
        removed_count = 0
        for pdf_file in pdf_dir.glob("*.pdf"):
            try:
                # Check if file is too small (likely incomplete)
                if pdf_file.stat().st_size < 1000:  # Less than 1KB
                    pdf_file.unlink()
                    removed_count += 1
                    continue
                
                # Check if file is actually a PDF
                with open(pdf_file, 'rb') as f:
                    header = f.read(10)
                    if not header.startswith(b'%PDF'):
                        pdf_file.unlink()
                        removed_count += 1
                        
            except Exception:
                # If we can't read the file, it's probably corrupted
                try:
                    pdf_file.unlink()
                    removed_count += 1
                except:
                    pass
        
        return removed_count
    
    def _cleanup_failed_analyses(self, analysis_dir: Path) -> int:
        """Remove incomplete or corrupted analysis files."""
        if not analysis_dir.exists():
            return 0
        
        removed_count = 0
        for analysis_file in analysis_dir.glob("*.txt"):
            try:
                # Check if file is too small (likely incomplete)
                if analysis_file.stat().st_size < 100:  # Less than 100 bytes
                    analysis_file.unlink()
                    removed_count += 1
                    continue
                
                # Check if file contains error markers
                with open(analysis_file, 'r', encoding='utf-8') as f:
                    content = f.read(500)  # Read first 500 chars
                    if ('❌ Automatic analysis failed' in content or 
                        '❌ Analysis failed' in content or
                        len(content.strip()) < 50):  # Very short content
                        analysis_file.unlink()
                        removed_count += 1
                        
            except Exception:
                # If we can't read the file, it's probably corrupted
                try:
                    analysis_file.unlink()
                    removed_count += 1
                except:
                    pass
        
        return removed_count
    
    def get_workspace_summary(self, workspace_dir: Path, material_id: str) -> Dict[str, Any]:
        """Get summary of workspace contents."""
        pdf_folder_name = f"{material_id}-pdf"
        
        # Find papers CSV files matching the pattern mp-id-timestamp.csv
        papers_csv_files = list(workspace_dir.glob(f"{material_id}-*.csv"))
        
        summary = {
            'workspace_dir': str(workspace_dir),
            'created_time': datetime.fromtimestamp(workspace_dir.stat().st_ctime).strftime('%Y-%m-%d %H:%M:%S'),
            'has_material_info': (workspace_dir / "material_info.json").exists(),
            'has_papers_csv': len(papers_csv_files) > 0,
            'has_analysis_csv': (workspace_dir / "analysis.csv").exists(),
            'pdf_count': len(list((workspace_dir / pdf_folder_name).glob("*.pdf"))) if (workspace_dir / pdf_folder_name).exists() else 0,
            'analysis_count': len(list((workspace_dir / "analysis").glob("*.txt"))) if (workspace_dir / "analysis").exists() else 0,
            'total_size_mb': sum(f.stat().st_size for f in workspace_dir.rglob("*") if f.is_file()) / (1024 * 1024)
        }
        
        return summary 