"""Semantic Scholar Search Client

Interface for searching academic papers using Semantic Scholar API.
"""

import logging
from typing import List, Optional, Tuple

from config import APIConfig
from models import Paper, JournalType
from utils import NetworkSession, NetworkError, RateLimiter, retry_on_failure, is_elsevier_doi, ProgressTracker


class SemanticScholarClient:
    """Client for Semantic Scholar API."""
    
    def __init__(self, api_config: APIConfig, rate_limiter: RateLimiter):
        self.api_key = api_config.semantic_scholar
        self.rate_limiter = rate_limiter
        self.logger = logging.getLogger(__name__)
        self.network = NetworkSession()
        self.base_url = "https://api.semanticscholar.org/graph/v1"
    
    @retry_on_failure(max_retries=3)
    async def search_papers(self, material_formula: str, target_count: int) -> List[Paper]:
        """Search for papers related to a material.
        
        Args:
            material_formula: Material chemical formula
            target_count: Target number of papers to find
            
        Returns:
            List[Paper]: List of papers sorted by citation count
        """
        self.logger.info(f"Searching papers for: {material_formula}")
        
        # Search for many more papers to ensure sufficient results after filtering
        search_count = max(target_count * 5, 100)  # At least 5x target or 100, whichever is larger
        
        await self.rate_limiter.wait_if_needed()
        
        headers = {}
        if self.api_key:
            headers['x-api-key'] = self.api_key
        
        # SIMPLE AND DIRECT: Just search for the exact material formula
        # If there are few results, that's the reality - don't pad with irrelevant papers
        
        await self.rate_limiter.wait_if_needed()
        
        self.logger.debug(f"Direct search: {material_formula}")
        
        params = {
            'query': material_formula,
            'limit': search_count,
            'fields': 'paperId,title,authors,venue,year,citationCount,abstract,externalIds'
        }
        
        url = f"{self.base_url}/paper/search"
        
        try:
            response = await self.network.get(url, params=params, headers=headers)
            data = response.json()
            
            papers = []
            
            for paper_data in data.get('data', []):
                # Extract paper information
                doi = paper_data.get('externalIds', {}).get('DOI', '') if paper_data.get('externalIds') else ''
                title = paper_data.get('title') or ''
                abstract = paper_data.get('abstract') or ''
                
                # Filter for material relevance (strict filtering)
                if not self._is_material_relevant(title, abstract, material_formula):
                    continue
                
                # Create paper object
                paper = Paper(
                    title=title,
                    doi=doi,
                    authors=[author.get('name', '') for author in (paper_data.get('authors') or [])],
                    journal=paper_data.get('venue') or '',
                    year=paper_data.get('year') or 0,
                    citation_count=paper_data.get('citationCount') or 0,
                    abstract=abstract,
                    journal_type=JournalType.ELSEVIER if is_elsevier_doi(doi) else JournalType.NON_ELSEVIER
                )
                
                papers.append(paper)
                
        except Exception as e:
            self.logger.error(f"Search failed: {e}")
            return []
        
        # Sort by citation count (descending)
        papers.sort(key=lambda x: x.citation_count, reverse=True)
        
        self.logger.info(f"Found {len(papers)} relevant papers for {material_formula}")
        
        return papers
    
    def _is_material_relevant(self, title: str, abstract: str, material_formula: str) -> bool:
        """STRICT filtering: Must contain target material formula.
        
        Args:
            title: Paper title
            abstract: Paper abstract  
            material_formula: Target material formula
            
        Returns:
            bool: True if paper is directly related to target material
        """
        content = f"{title} {abstract}".lower()
        material_lower = material_formula.lower()
        
        # Basic validation
        if len(content.strip()) < 20:
            return False
        
        # CRITICAL: Must contain the exact target material formula
        if material_lower not in content:
            return False
        
        # Additional check: exclude if material is only mentioned in passing
        # (e.g., in a long list of compared materials)
        title_lower = title.lower()
        
        # If material is in title, definitely relevant
        if material_lower in title_lower:
            return True
        
        # If material is in abstract, check context (STRICT)
        if material_lower in content:
            # Check if it appears with synthesis/characterization keywords
            relevant_contexts = [
                f'{material_lower} synthesis',
                f'{material_lower} preparation', 
                f'{material_lower} characterization',
                f'{material_lower} properties',
                f'{material_lower} nanoparticle',
                f'{material_lower} thin film',
                f'{material_lower} crystal',
                f'synthesis of {material_lower}',
                f'preparation of {material_lower}',
                f'properties of {material_lower}',
                f'{material_lower} magnetic',
                f'{material_lower} optical',
                f'{material_lower} ferroelectric'
            ]
            
            # If any relevant context found, accept
            if any(context in content for context in relevant_contexts):
                return True
            
            # If material appears multiple times in different contexts, likely relevant
            if content.count(material_lower) >= 2:
                return True
        
        # Exclude clearly irrelevant mentions
        exclusion_patterns = [
            'compared with', 'in comparison to', 'similar to', 'different from',
            'unlike', 'as opposed to', 'in contrast to', 'while others'
        ]
        
        for pattern in exclusion_patterns:
            if pattern in content and material_lower in content:
                # Check if material only appears near exclusion pattern
                pattern_pos = content.find(pattern)
                material_pos = content.find(material_lower)
                if abs(pattern_pos - material_pos) < 50:  # Within 50 characters
                    return False
        
        return True
    
    async def get_paper_details(self, paper_id: str) -> Optional[Paper]:
        """Get detailed information for a specific paper.
        
        Args:
            paper_id: Semantic Scholar paper ID
            
        Returns:
            Optional[Paper]: Paper details or None if not found
        """
        await self.rate_limiter.wait_if_needed()
        
        headers = {}
        if self.api_key:
            headers['x-api-key'] = self.api_key
        
        params = {
            'fields': 'title,abstract,authors,venue,year,citationCount,externalIds,tldr'
        }
        
        url = f"{self.base_url}/paper/{paper_id}"
        
        try:
            response = await self.network.get(url, params=params, headers=headers)
            data = response.json()
            
            doi = data.get('externalIds', {}).get('DOI', '') if data.get('externalIds') else ''
            
            paper = Paper(
                title=data.get('title', ''),
                doi=doi,
                authors=[author.get('name', '') for author in (data.get('authors') or [])],
                journal=data.get('venue', ''),
                year=data.get('year', 0) or 0,
                citation_count=data.get('citationCount', 0) or 0,
                abstract=data.get('abstract', ''),
                journal_type=JournalType.ELSEVIER if is_elsevier_doi(doi) else JournalType.NON_ELSEVIER
            )
            
            return paper
            
        except NetworkError:
            self.logger.warning(f"Failed to get details for paper: {paper_id}")
            return None
    
    def display_search_results(self, papers: List[Paper], material_formula: str) -> None:
        """Display search results with citation sorting verification.
        
        Args:
            papers: List of papers
            material_formula: Material formula searched
        """
        print(f"\n📚 Search Results for {material_formula}:")
        print(f"   Found {len(papers)} relevant papers")
        
        # Verify citation sorting as required by idea.txt
        if papers:
            citation_counts = [p.citation_count for p in papers]
            is_properly_sorted = all(citation_counts[i] >= citation_counts[i+1] 
                                   for i in range(len(citation_counts)-1))
            
            sort_status = "✅ Correct" if is_properly_sorted else "❌ Incorrect"
            print(f"   📈 Citation sorting validation: {sort_status}")
            print(f"   📊 Citation range: {max(citation_counts)} - {min(citation_counts)}")
            
            # If not sorted, re-sort to ensure compliance
            if not is_properly_sorted:
                papers.sort(key=lambda x: x.citation_count, reverse=True)
                self.logger.warning("Re-sorting papers to ensure descending citation order")
        
        elsevier_count = sum(1 for p in papers if p.journal_type == JournalType.ELSEVIER)
        non_elsevier_count = len(papers) - elsevier_count
        
        print(f"   📘 Elsevier papers: {elsevier_count}")
        print(f"   📙 Non-Elsevier papers: {non_elsevier_count}")
        
        print("\n   Top 5 papers by citation count:")
        for i, paper in enumerate(papers[:5], 1):
            journal_icon = "📘" if paper.journal_type == JournalType.ELSEVIER else "📙"
            print(f"   {i}. {journal_icon} {paper.title[:60]}...")
            print(f"      Citations: {paper.citation_count} | Journal: {paper.journal}")
            if paper.doi:
                print(f"      DOI: {paper.doi}")
        
        # Additional quality metrics
        avg_citations = sum(p.citation_count for p in papers) / len(papers) if papers else 0
        print(f"\n   📊 Quality metrics:")
        print(f"      Average citations: {avg_citations:.1f}")
        print(f"      High-impact papers (>50): {sum(1 for p in papers if p.citation_count > 50)}")
        print(f"      Recent papers (≥2020): {sum(1 for p in papers if p.year >= 2020)}")
    
    async def validate_api_access(self) -> bool:
        """Validate API access and rate limits.
        
        Returns:
            bool: True if API is accessible
        """
        try:
            await self.rate_limiter.wait_if_needed()
            
            headers = {}
            if self.api_key:
                headers['x-api-key'] = self.api_key
            
            # Simple test search
            params = {
                'query': 'machine learning',
                'limit': 1,
                'fields': 'title'
            }
            
            url = f"{self.base_url}/paper/search"
            response = await self.network.get(url, params=params, headers=headers)
            
            return response.status_code == 200
            
        except Exception as e:
            self.logger.error(f"API validation failed: {e}")
            return False 