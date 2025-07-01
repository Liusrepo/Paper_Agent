"""Gemini AI Client

Interface for paper relevance evaluation and PDF content analysis using Gemini API.
"""

import json
import logging
from typing import List, Tuple, Optional
from pathlib import Path

from config import APIConfig
from models import Paper, PaperAnalysis, DownloadStatus
from utils import RateLimiter, retry_on_failure, ProgressTracker

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False


class GeminiClient:
    """Client for Gemini AI API."""
    
    def __init__(self, api_config: APIConfig, rate_limiter: RateLimiter):
        self.api_key = api_config.gemini
        self.rate_limiter = rate_limiter
        self.logger = logging.getLogger(__name__)
        
        if not GEMINI_AVAILABLE:
            raise ImportError("Gemini library not available")
        
        genai.configure(api_key=self.api_key)
        
        # Try to initialize with the best available model
        self.model = self._initialize_model()
        self.logger.info(f"Gemini client initialized with model: {self.model.model_name}")
    
    def _initialize_model(self):
        """Initialize the best available Gemini model."""
        models_to_try = [
            'gemini-2.5-flash',
            'gemini-2.0-flash-lite', 
            'gemini-2.0-flash',
            'gemini-1.5-pro',
            'gemini-1.5-flash',
            'gemini-pro'
        ]
        
        for model_name in models_to_try:
            try:
                model = genai.GenerativeModel(model_name)
                self.logger.info(f"Using Gemini model: {model_name}")
                return model
            except Exception as e:
                self.logger.debug(f"Model {model_name} not available: {e}")
                continue
        
        raise ValueError("No Gemini model available")
    
    @retry_on_failure(max_retries=3)
    async def select_papers(self, papers: List[Paper], material_formula: str, 
                           target_count: int) -> List[Paper]:
        """Select papers using 60/40 Elsevier/Non-Elsevier strategy.
        
        Strategy:
        - 60% Elsevier papers (prefer recent ones, we have API access)
        - 40% Non-Elsevier papers (prefer older ones, Anna Archive coverage)
        
        Args:
            papers: List of papers to evaluate
            material_formula: Target material formula
            target_count: Number of papers to select
            
        Returns:
            List[Paper]: Selected papers with optimal download success rate
        """
        self.logger.info(f"Evaluating {len(papers)} papers with 60/40 strategy for {material_formula}")
        
        await self.rate_limiter.wait_if_needed()
        
        # Smart backup selection to ensure adequate candidates for downloads
        # Calculate target distribution with reasonable backup for download failures  
        backup_multiplier = 1.5  # More conservative backup to avoid over-selection
        target_elsevier = int(target_count * 0.6 * backup_multiplier)  # 60% Elsevier
        target_non_elsevier = int(target_count * 0.4 * backup_multiplier)  # 40% Non-Elsevier
        
        self.logger.info(f"Target distribution with backup: {target_elsevier} Elsevier + {target_non_elsevier} Non-Elsevier (1.5x for download reliability)")
        
        # Separate papers by journal type
        elsevier_papers = [p for p in papers if p.journal_type.name == 'ELSEVIER']
        non_elsevier_papers = [p for p in papers if p.journal_type.name == 'NON_ELSEVIER']
        
        # Select Elsevier papers (prefer recent)
        selected_elsevier = await self._select_elsevier_papers(
            elsevier_papers, material_formula, target_elsevier
        )
        
        # Select Non-Elsevier papers (prefer older)
        selected_non_elsevier = await self._select_non_elsevier_papers(
            non_elsevier_papers, material_formula, target_non_elsevier
        )
        
        # Combine and assign paper indices
        all_selected = selected_elsevier + selected_non_elsevier
        for i, paper in enumerate(all_selected, 1):
            paper.paper_index = i
            paper.is_selected = True
        
        self.logger.info(f"Final selection: {len(selected_elsevier)} Elsevier + {len(selected_non_elsevier)} Non-Elsevier = {len(all_selected)} total")
        return all_selected
    
    async def _select_elsevier_papers(self, elsevier_papers: List[Paper], 
                                    material_formula: str, target_count: int) -> List[Paper]:
        """Select Elsevier papers with preference for recent publications.
        
        Args:
            elsevier_papers: List of Elsevier papers
            material_formula: Target material formula
            target_count: Number of papers to select
            
        Returns:
            List[Paper]: Selected Elsevier papers
        """
        if not elsevier_papers:
            self.logger.warning("No Elsevier papers available")
            return []
        
        self.logger.info(f"Selecting {target_count} from {len(elsevier_papers)} Elsevier papers (prefer recent)")
        
        # Get paper titles for evaluation
        paper_titles = [paper.title for paper in elsevier_papers]
        
        # Use Gemini to evaluate relevance
        evaluations = await self._evaluate_paper_relevance(material_formula, paper_titles)
        
        # Apply scores and filter relevant papers
        scored_papers = []
        for idx, score, reason in evaluations:
            if idx < len(elsevier_papers) and score >= 5.0:  # Lower threshold for Elsevier
                paper = elsevier_papers[idx]
                paper.relevance_score = score
                
                # Boost score for recent papers (2018+)
                if paper.year >= 2018:
                    paper.relevance_score += 1.0
                
                scored_papers.append(paper)
        
        # Sort by relevance score (with recency boost) and citation count
        scored_papers.sort(key=lambda p: (p.relevance_score, p.citation_count), reverse=True)
        
        selected = scored_papers[:target_count]
        self.logger.info(f"Selected {len(selected)} Elsevier papers (avg year: {sum(p.year for p in selected)/len(selected) if selected else 0:.0f})")
        
        return selected
    
    async def _select_non_elsevier_papers(self, non_elsevier_papers: List[Paper], 
                                        material_formula: str, target_count: int) -> List[Paper]:
        """Select Non-Elsevier papers with preference for older publications.
        
        Args:
            non_elsevier_papers: List of Non-Elsevier papers
            material_formula: Target material formula
            target_count: Number of papers to select
            
        Returns:
            List[Paper]: Selected Non-Elsevier papers
        """
        if not non_elsevier_papers:
            self.logger.warning("No Non-Elsevier papers available")
            return []
        
        self.logger.info(f"Selecting {target_count} from {len(non_elsevier_papers)} Non-Elsevier papers (prefer older)")
        
        # Get paper titles for evaluation
        paper_titles = [paper.title for paper in non_elsevier_papers]
        
        # Use Gemini to evaluate relevance
        evaluations = await self._evaluate_paper_relevance(material_formula, paper_titles)
        
        # Apply scores and filter relevant papers
        scored_papers = []
        for idx, score, reason in evaluations:
            if idx < len(non_elsevier_papers) and score >= 5.0:  # Lower threshold for Non-Elsevier
                paper = non_elsevier_papers[idx]
                paper.relevance_score = score
                
                # Boost score for older papers (before 2020) - Anna Archive coverage is better
                if paper.year <= 2019:
                    paper.relevance_score += 1.0
                
                # Extra boost for papers from 2010-2018 (golden age for Anna Archive)
                if 2010 <= paper.year <= 2018:
                    paper.relevance_score += 0.5
                
                scored_papers.append(paper)
        
        # Sort by relevance score (with age boost) and citation count
        scored_papers.sort(key=lambda p: (p.relevance_score, p.citation_count), reverse=True)
        
        selected = scored_papers[:target_count]
        self.logger.info(f"Selected {len(selected)} Non-Elsevier papers (avg year: {sum(p.year for p in selected)/len(selected) if selected else 0:.0f})")
        
        return selected
    
    async def _evaluate_paper_relevance(self, material_formula: str, 
                                       paper_titles: List[str]) -> List[Tuple[int, float, str]]:
        """Evaluate paper relevance with advanced quality filtering.
        
        Args:
            material_formula: Target material formula
            paper_titles: List of paper titles
            
        Returns:
            List of (index, score, reason) tuples
        """
        titles_text = "\n".join([f"{i+1}. {title}" for i, title in enumerate(paper_titles)])
        
        prompt = f"""
As a senior materials science expert and journal editor, please evaluate the relevance and academic quality of the following papers to the target material "{material_formula}".

【Intelligent Selection Criteria】:

1. **Relevance Assessment**:
   - Papers directly studying {material_formula}: Priority selection
   - Papers studying {material_formula} doping, modification, or composites: Selectable
   - Papers mentioning {material_formula} in comparative studies: Considerable

2. **Article Type Filtering**:
   ❌ **Absolutely Exclude**:
   - Review articles (review, survey, overview, advances, progress, state-of-art)
   - Short communications (short communication, brief report)
   - Conference abstracts (conference abstract, proceedings)
   - Editorial comments (editorial, commentary)
   
   ✅ **Priority Selection**:
   - Original research articles (research article, original paper)
   - Experimental studies (experimental study)
   - Technical reports (technical report)

3. **Journal Quality Assessment**:
   ❌ **Exclude Low-Quality Journals**:
   - Obviously predatory journals
   - Journals with excessively low impact factors (Q4 quartile)
   - Non-peer-reviewed publications
   
   ✅ **Priority High-Quality Journals**:
   - Top materials science journals (Nature, Science sub-journals)
   - SCI Q1/Q2 quartile journals
   - Renowned publisher journals (Elsevier, Springer, Wiley, etc.)

Target Material: {material_formula}

Paper List:
{titles_text}

【Scoring Criteria】(0-10 points):
- 9-10 points: High-quality experimental papers directly studying {material_formula}
- 7-8 points: Highly relevant quality research papers
- 5-6 points: Moderately relevant research papers
- 1-4 points: Weakly relevant but referenceable papers
- 0 points: Review articles, low-quality journals, or irrelevant papers

Please return in JSON format, selecting high-quality relevant papers (recommend 10-15 papers):

{{
  "selected_papers": [
    {{
      "index": 1,
      "score": 9.5,
      "reason": "High-quality experimental paper directly studying {material_formula} synthesis and characterization"
    }}
  ]
}}

Return only JSON, no other text.
"""
        
        try:
            response = self.model.generate_content(prompt)
            result_text = response.text.strip()
            
            # Clean JSON format
            if result_text.startswith('```json'):
                result_text = result_text.split('```json')[1].split('```')[0].strip()
            elif result_text.startswith('```'):
                result_text = result_text.split('```')[1].split('```')[0].strip()
            
            result = json.loads(result_text)
            evaluations = []
            
            for paper in result.get('selected_papers', []):
                index = paper.get('index', 1) - 1  # Convert to 0-based index
                score = paper.get('score', 0.0)
                reason = paper.get('reason', '')
                evaluations.append((index, score, reason))
            
            self.logger.info(f"Gemini evaluated {len(evaluations)} relevant papers")
            return evaluations
            
        except Exception as e:
            self.logger.error(f"Gemini evaluation failed: {e}")
            # Fallback to simple selection based on material formula presence
            return self._fallback_paper_selection(material_formula, paper_titles)
    
    def _fallback_paper_selection(self, material_formula: str, 
                                 paper_titles: List[str]) -> List[Tuple[int, float, str]]:
        """Fallback paper selection when Gemini fails."""
        self.logger.warning("Using fallback paper selection")
        
        evaluations = []
        for i, title in enumerate(paper_titles):
            title_lower = title.lower()
            formula_lower = material_formula.lower()
            
            score = 0.0
            reason = "fallback evaluation"
            
            if formula_lower in title_lower:
                score = 8.0
                reason = "Contains target material in title"
                
                # Boost score for synthesis/characterization keywords
                if any(keyword in title_lower for keyword in ['synthesis', 'characterization', 'properties']):
                    score = 9.0
                    reason = "Contains target material and synthesis keywords"
                
                # Reduce score for reviews
                if any(keyword in title_lower for keyword in ['review', 'overview', 'progress']):
                    score = 3.0
                    reason = "Review article - lower priority"
                
                evaluations.append((i, score, reason))
        
        # Sort by score and return top candidates
        evaluations.sort(key=lambda x: x[1], reverse=True)
        return evaluations[:15]  # Return top 15 for selection
    
    @retry_on_failure(max_retries=3)
    async def analyze_pdf(self, paper: Paper, pdf_path: Path, 
                         material_formula: str) -> PaperAnalysis:
        """Analyze PDF content and extract structured information.
        
        Args:
            paper: Paper object
            pdf_path: Path to PDF file
            material_formula: Material formula for context
            
        Returns:
            PaperAnalysis: Structured analysis results
        """
        self.logger.info(f"Analyzing PDF: {paper.title[:50]}...")
        
        await self.rate_limiter.wait_if_needed()
        
        # Extract text from PDF
        pdf_text = await self._extract_pdf_text(pdf_path)
        
        if not pdf_text or len(pdf_text) < 500:
            self.logger.warning(f"PDF text too short: {len(pdf_text) if pdf_text else 0} chars")
            return self._create_fallback_analysis(paper)
        
        # Analyze with Gemini
        analysis = await self._analyze_with_gemini(paper, pdf_text, material_formula)
        
        self.logger.info(f"Analysis completed for: {paper.title[:50]}...")
        return analysis
    
    async def _extract_pdf_text(self, pdf_path: Path) -> str:
        """Extract text content from PDF file."""
        try:
            # Try PyMuPDF first
            try:
                import fitz
                doc = fitz.open(str(pdf_path))
                text_parts = []
                
                for page_num in range(min(len(doc), 30)):  # Limit to 30 pages
                    page = doc[page_num]
                    text = page.get_text()
                    if text.strip():
                        text_parts.append(text)
                
                doc.close()
                return "\n".join(text_parts)
                
            except ImportError:
                # Fallback to PyPDF2
                import PyPDF2
                with open(pdf_path, 'rb') as file:
                    reader = PyPDF2.PdfReader(file)
                    text_parts = []
                    
                    for page_num in range(min(len(reader.pages), 30)):
                        page = reader.pages[page_num]
                        text = page.extract_text()
                        if text.strip():
                            text_parts.append(text)
                    
                    return "\n".join(text_parts)
                    
        except Exception as e:
            self.logger.error(f"PDF text extraction failed: {e}")
            return ""
    
    async def _analyze_with_gemini(self, paper: Paper, pdf_text: str, 
                                  material_formula: str) -> PaperAnalysis:
        """Analyze paper content using Gemini AI."""
        
        prompt = f"""
As a senior materials science expert, please conduct a detailed analysis of the following academic paper about {material_formula}.

Paper Title: {paper.title}
Paper Content: {pdf_text[:15000]}  # Limit content length

Please conduct detailed analysis following the template below:

## Research Background
[Describe research background and significance, 1-2 paragraphs]

## Research Innovation Points
[List main technical innovations and breakthroughs, specifically explain differences from existing technologies]

## Preparation Conditions (Detailed, for reproduction)
[Detailed description of material preparation process, including:
- Raw material ratios and purity
- Reaction temperature, time, atmosphere
- Equipment models and key parameters
- Post-treatment conditions]

## Characterization Results (Detailed, for review)
[Detailed description of characterization techniques and results, including:
- Characterization methods used (XRD, SEM, TEM, etc.)
- Key data and chart analysis
- Performance parameters and values
- Structural feature descriptions]

## Conclusions
[Summarize the original conclusions without losing their meaning]

Please ensure each section contains specific information and avoid generalities. If information in any section is insufficient, please clearly state "The text does not describe XX information in detail".
"""
        
        try:
            response = self.model.generate_content(prompt)
            content = response.text.strip()
            
            # Parse the structured response
            analysis = self._parse_analysis_content(paper, content)
            return analysis
            
        except Exception as e:
            self.logger.error(f"Gemini analysis failed: {e}")
            return self._create_fallback_analysis(paper)
    
    def _parse_analysis_content(self, paper: Paper, content: str) -> PaperAnalysis:
        """Parse Gemini analysis response into structured format."""
        import re
        
        analysis = PaperAnalysis(
            paper_index=paper.paper_index,
            title=paper.title,
            doi=paper.doi
        )
        
        # Split by section headers
        sections = re.split(r'##\s+', content)
        
        for section in sections:
            section = section.strip()
            if not section:
                continue
            
            if section.startswith('Research Background'):
                analysis.research_background = section.replace('Research Background', '').strip()
            elif section.startswith('Research Innovation Points') or section.startswith('Innovation Points'):
                analysis.innovation_points = section.replace('Research Innovation Points', '').replace('Innovation Points', '').strip()
            elif section.startswith('Preparation Conditions'):
                analysis.preparation_conditions = section.replace('Preparation Conditions (Detailed, for reproduction)', '').replace('Preparation Conditions', '').strip()
            elif section.startswith('Characterization Results'):
                analysis.characterization_results = section.replace('Characterization Results (Detailed, for review)', '').replace('Characterization Results', '').strip()
            elif section.startswith('Conclusions'):
                analysis.conclusions = section.replace('Conclusions', '').strip()
        
        # Ensure minimum content
        if not analysis.research_background:
            analysis.research_background = f"Research background analysis based on the paper '{paper.title}'"
        
        return analysis
    
    def _create_fallback_analysis(self, paper: Paper) -> PaperAnalysis:
        """Create fallback analysis when AI analysis fails."""
        return PaperAnalysis(
            paper_index=paper.paper_index,
            title=paper.title,
            doi=paper.doi,
            research_background=f"Paper title: {paper.title}. AI analysis is temporarily unavailable, please refer to the PDF for detailed information.",
            innovation_points="Manual review of PDF file required",
            preparation_conditions="Detailed PDF content review required",
            characterization_results="Detailed PDF content review required",
            conclusions="Manual review of original text required"
        )
    
    async def validate_api_access(self) -> bool:
        """Validate Gemini API access.
        
        Returns:
            bool: True if API is accessible
        """
        try:
            await self.rate_limiter.wait_if_needed()
            
            # Simple test
            response = self.model.generate_content("Hello, this is a test.")
            return bool(response.text)
            
        except Exception as e:
            self.logger.error(f"Gemini API validation failed: {e}")
            return False 