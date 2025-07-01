"""Download Client Module

Handles PDF downloads from Elsevier and Anna Archive.
"""

import asyncio
import logging
import os
import re
from io import BytesIO
from pathlib import Path
from typing import Tuple, Optional



from config import APIConfig
from models import Paper, DownloadStatus
from utils import NetworkSession, NetworkError, RateLimiter, retry_on_failure, is_elsevier_doi, format_file_size

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False


class ElsevierDownloader:
    """Downloader for Elsevier/ScienceDirect papers."""
    
    def __init__(self, api_config: APIConfig, rate_limiter: RateLimiter):
        self.api_key = api_config.elsevier
        self.rate_limiter = rate_limiter
        self.logger = logging.getLogger(__name__)
        self.network = NetworkSession()
    
    @retry_on_failure(max_retries=3)
    async def download_pdf(self, paper: Paper, output_path: Path) -> Tuple[bool, int]:
        """Download PDF using the proven strategy from original paper.py."""
        if not paper.doi or not is_elsevier_doi(paper.doi):
            raise ValueError(f"Invalid Elsevier DOI: {paper.doi}")
        
        self.logger.info(f"Downloading Elsevier content: {paper.doi}")
        await self.rate_limiter.wait_if_needed()
        
        # Strategy 1: 🔑 Use proven strategy from original paper.py to download PDF
        success, file_size = await self._download_pdf_abstract(paper.doi, output_path)
        if success:
            return True, file_size
        
        # Strategy 2: If PDF download fails, try to get enhanced XML content as fallback
        success, file_size = await self._get_enhanced_xml_content(paper.doi, output_path)
        if success:
            return True, file_size
        
        return False, 0
    
    async def _get_sciencedirect_fulltext_url(self, doi: str) -> Optional[str]:
        """Use ScienceDirect Search API to find full-text article URL."""
        try:
            # ScienceDirect Search API with institutional token
            search_url = "https://api.elsevier.com/content/search/sciencedirect"
            
            # Enhanced headers with institutional support
            headers = {
                'X-ELS-APIKey': self.api_key,
                'Accept': 'application/json',
                'User-Agent': 'Academic Research Tool/2.0 (Institutional Access)',
                # Note: X-ELS-Insttoken would go here if you have an institutional token
                # 'X-ELS-Insttoken': 'your_institutional_token',
            }
            
            # Search for the specific DOI
            params = {
                'query': f'DOI({doi})',
                'count': '5',
                'field': 'url,title,doi,prism:url,link',  # Request URL fields
                'view': 'STANDARD'
            }
            
            self.logger.debug(f"Searching ScienceDirect for DOI: {doi}")
            response = await self.network.get(search_url, params=params, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                entries = data.get('search-results', {}).get('entry', [])
                
                for entry in entries:
                    # Look for full-text URLs in the entry
                    links = entry.get('link', [])
                    for link in links:
                        if isinstance(link, dict):
                            href = link.get('@href', '')
                            rel = link.get('@rel', '')
                            
                            # Look for full-text or PDF links
                            if any(keyword in rel.lower() for keyword in ['scidir', 'full', 'pdf']):
                                self.logger.info(f"Found ScienceDirect full-text URL: {href[:50]}...")
                                return href
                    
                    # Also check prism:url field
                    prism_url = entry.get('prism:url')
                    if prism_url:
                        self.logger.info(f"Found prism URL: {prism_url[:50]}...")
                        return prism_url
                        
            else:
                self.logger.debug(f"ScienceDirect search failed: {response.status_code}")
                
        except Exception as e:
            self.logger.debug(f"ScienceDirect search error: {e}")
        
        return None
    
    async def _get_enhanced_xml_content(self, doi: str, output_path: Path) -> Tuple[bool, int]:
        """Get enhanced XML content from Elsevier Text Mining API."""
        try:
            headers = {
                'X-ELS-APIKey': self.api_key,
                'Accept': 'text/xml,application/xml',
                'User-Agent': 'Academic Text Mining Tool/2.0',
            }
            
            # Request XML content
            url = f"https://api.elsevier.com/content/article/doi/{doi}"
            
            response = await self.network.get(url, headers=headers)
            
            if response.status_code == 200:
                xml_content = response.text
                
                # Extract meaningful content from XML
                enhanced_content = self._extract_enhanced_content_from_xml(xml_content)
                
                if len(enhanced_content) > 500:  # Substantial content
                    # Save as text file with enhanced formatting
                    text_output_path = output_path.with_suffix('.txt')
                    with open(text_output_path, 'w', encoding='utf-8') as f:
                        f.write(enhanced_content)
                    
                    file_size = text_output_path.stat().st_size
                    self.logger.info(f"✅ Enhanced XML content: {format_file_size(file_size)} (enhanced format)")
                    return True, file_size
                    
        except Exception as e:
            self.logger.debug(f"Enhanced XML extraction error: {e}")
        
        return False, 0
    
    async def _download_pdf_abstract(self, doi: str, output_path: Path) -> Tuple[bool, int]:
        """Download PDF using the proven strategy from original paper.py."""
        try:
            # 🔑 Use proven strategy from original paper.py
            headers = {
                'X-ELS-APIKey': self.api_key,
                'Accept': 'application/pdf,application/xml,*/*',  # Key: Multi-format Accept header
                'User-Agent': 'Academic Research Tool/2.0',
            }
            
            url = f"https://api.elsevier.com/content/article/doi/{doi}"
            
            response = await self.network.get(url, headers=headers)
            
            if response.status_code == 200:
                content = response.content
                content_type = response.headers.get('content-type', '').lower()
                
                if 'application/pdf' in content_type and content.startswith(b'%PDF'):
                    file_size = len(content)
                    
                    with open(output_path, 'wb') as f:
                        f.write(content)
                    
                    # 🎯 Use graded evaluation system from original paper.py
                    if file_size > 500000:  # Greater than 500KB, likely complete PDF
                        self.logger.info(f"✅ Complete PDF download successful: {format_file_size(file_size)}")
                    elif file_size > 100000:  # 100KB-500KB, possibly partial content
                        self.logger.info(f"✅ PDF download successful: {format_file_size(file_size)} (partial content)")
                    else:
                        self.logger.info(f"✅ PDF download successful: {format_file_size(file_size)} (abstract page)")
                    
                    return True, file_size
                    
        except Exception as e:
            self.logger.debug(f"PDF download error: {e}")
        
        return False, 0
    
    def _extract_enhanced_content_from_xml(self, xml_content: str) -> str:
        """Extract and format enhanced content from Elsevier XML response."""
        if not BS4_AVAILABLE:
            # Simple extraction without BeautifulSoup
            import re
            # Extract description content
            desc_match = re.search(r'<dc:description>(.*?)</dc:description>', xml_content, re.DOTALL)
            if desc_match:
                return f"Enhanced Abstract:\n\n{desc_match.group(1).strip()}"
            return ""
        
        try:
            soup = BeautifulSoup(xml_content, 'xml')
            content_parts = []
            
            # Extract title
            title_tags = ['dc:title', 'title', 'ce:title']
            for tag in title_tags:
                title_elem = soup.find(tag)
                if title_elem and title_elem.get_text().strip():
                    content_parts.append(f"Title: {title_elem.get_text().strip()}")
                    break
            
            # Extract authors
            authors = soup.find_all('dc:creator')
            if authors:
                author_names = [author.get_text().strip() for author in authors]
                content_parts.append(f"Authors: {', '.join(author_names)}")
            
            # Extract journal info
            journal_elem = soup.find('prism:publicationName')
            if journal_elem:
                content_parts.append(f"Journal: {journal_elem.get_text().strip()}")
            
            # Extract publication date
            date_elem = soup.find('prism:coverDisplayDate')
            if date_elem:
                content_parts.append(f"Publication Date: {date_elem.get_text().strip()}")
            
            # Extract DOI
            doi_elem = soup.find('prism:doi')
            if doi_elem:
                content_parts.append(f"DOI: {doi_elem.get_text().strip()}")
            
            # Extract enhanced abstract
            desc_elem = soup.find('dc:description')
            if desc_elem and len(desc_elem.get_text().strip()) > 50:
                abstract_text = desc_elem.get_text().strip()
                # Clean up the abstract text
                import re
                abstract_text = re.sub(r'\s+', ' ', abstract_text)
                content_parts.append(f"Enhanced Abstract:\n{abstract_text}")
            
            # Extract keywords
            keywords = soup.find_all('dcterms:subject')
            if keywords:
                keyword_list = [kw.get_text().strip() for kw in keywords if kw.get_text().strip()]
                if keyword_list:
                    content_parts.append(f"Keywords: {', '.join(keyword_list)}")
            
            # Format the final content
            formatted_content = "\n\n".join(content_parts)
            
            # Add header
            header = "=" * 80 + "\n"
            header += "ELSEVIER ENHANCED CONTENT (Text Mining API)\n"
            header += "Note: This is enhanced abstract content with full metadata\n"
            header += "=" * 80 + "\n\n"
            
            return header + formatted_content
            
        except Exception as e:
            self.logger.debug(f"XML parsing failed: {e}")
            return f"Raw XML content:\n{xml_content[:2000]}..."
    
    async def _download_pdf_with_institutional_access(self, doi: str, output_path: Path) -> Tuple[bool, int]:
        """Try to download actual PDF using Text Mining API with institutional access."""
        try:
            # Text Mining API endpoints - these should work with institutional IP
            headers = {
                'X-ELS-APIKey': self.api_key,
                'Accept': 'application/pdf,application/xml,text/xml,*/*',
                'User-Agent': 'Academic Text Mining Tool/2.0',
            }
            
            # Text Mining API URLs (as per documentation)
            endpoints = [
                # Strategy 1: Request full-text view with PDF preference
                f"https://api.elsevier.com/content/article/doi/{doi}?view=FULL&httpAccept=application/pdf",
                
                # Strategy 2: Default Text Mining API (should auto-detect institutional access)
                f"https://api.elsevier.com/content/article/doi/{doi}?httpAccept=application/pdf",
                
                # Strategy 3: Try PII if available
                f"https://api.elsevier.com/content/article/pii/{self._doi_to_pii(doi)}?view=FULL&httpAccept=application/pdf" if self._doi_to_pii(doi) else None,
                
                # Strategy 4: Standard endpoint with institutional detection
                f"https://api.elsevier.com/content/article/doi/{doi}",
            ]
            
            # Filter out None endpoints
            endpoints = [ep for ep in endpoints if ep is not None]
            
            for i, endpoint in enumerate(endpoints, 1):
                try:
                    self.logger.debug(f"Text Mining API endpoint {i}: {endpoint[:60]}...")
                    response = await self.network.get(endpoint, headers=headers)
                    
                    if response.status_code == 200:
                        content = response.content
                        content_type = response.headers.get('content-type', '').lower()
                        
                        # Check if we got a PDF
                        if 'application/pdf' in content_type and content.startswith(b'%PDF'):
                            file_size = len(content)
                            
                            # Accept large PDFs that are likely complete
                            if file_size > 100000:
                                with open(output_path, 'wb') as f:
                                    f.write(content)
                                self.logger.info(f"✅ Institutional PDF: {format_file_size(file_size)}")
                                return True, file_size
                                        
                except Exception as e:
                    self.logger.debug(f"Text Mining endpoint {i} failed: {e}")
                    continue
                    
        except Exception as e:
            self.logger.debug(f"Text Mining API error: {e}")
        
        return False, 0
    
    async def _get_fulltext_as_document(self, doi: str, output_path: Path) -> Tuple[bool, int]:
        """Get full-text content via Text Mining API and save as text document."""
        try:
            # Text Mining API for full-text content
            headers = {
                'X-ELS-APIKey': self.api_key,
                'Accept': 'text/plain,text/xml,application/xml',
                'User-Agent': 'Academic Text Mining Tool/2.0',
            }
            
            # Try to get full-text in plain text format
            endpoints = [
                f"https://api.elsevier.com/content/article/doi/{doi}?view=FULL&httpAccept=text/plain",
                f"https://api.elsevier.com/content/article/doi/{doi}?httpAccept=text/plain",
                f"https://api.elsevier.com/content/article/doi/{doi}?view=FULL&httpAccept=text/xml",
                f"https://api.elsevier.com/content/article/doi/{doi}?httpAccept=text/xml",
            ]
            
            for endpoint in endpoints:
                try:
                    self.logger.debug(f"Requesting full-text: {endpoint[:60]}...")
                    response = await self.network.get(endpoint, headers=headers)
                    
                    if response.status_code == 200:
                        content_type = response.headers.get('content-type', '').lower()
                        
                        if 'text/plain' in content_type:
                            # Got plain text - this is full-text content!
                            text_content = response.text
                            if len(text_content) > 2000:  # Substantial content
                                # Save as text file instead of PDF since we have full-text
                                text_output_path = output_path.with_suffix('.txt')
                                with open(text_output_path, 'w', encoding='utf-8') as f:
                                    f.write(f"Full-text content from Elsevier Text Mining API\n")
                                    f.write(f"DOI: {doi}\n")
                                    f.write("="*80 + "\n\n")
                                    f.write(text_content)
                                
                                file_size = text_output_path.stat().st_size
                                self.logger.info(f"✅ Full-text content saved: {format_file_size(file_size)} (text format)")
                                return True, file_size
                                
                        elif 'xml' in content_type:
                            # Got XML - extract text content
                            xml_content = response.text
                            if len(xml_content) > 2000 and 'full-text' in xml_content.lower():
                                # Extract text from XML and save
                                extracted_text = self._extract_text_from_xml(xml_content)
                                if len(extracted_text) > 1000:
                                    text_output_path = output_path.with_suffix('.txt')
                                    with open(text_output_path, 'w', encoding='utf-8') as f:
                                        f.write(f"Full-text content extracted from Elsevier XML\n")
                                        f.write(f"DOI: {doi}\n")
                                        f.write("="*80 + "\n\n")
                                        f.write(extracted_text)
                                    
                                    file_size = text_output_path.stat().st_size
                                    self.logger.info(f"✅ XML full-text extracted: {format_file_size(file_size)} (text format)")
                                    return True, file_size
                        
                except Exception as e:
                    self.logger.debug(f"Full-text endpoint failed: {e}")
                    continue
                    
        except Exception as e:
            self.logger.debug(f"Full-text extraction error: {e}")
        
        return False, 0
    
    async def _download_from_fulltext_url(self, url: str, output_path: Path) -> Tuple[bool, int]:
        """Download PDF from ScienceDirect full-text URL."""
        try:
            # Headers with institutional support for full-text access
            headers = {
                'X-ELS-APIKey': self.api_key,
                'Accept': 'application/pdf,*/*',
                'User-Agent': 'Academic Research Tool/2.0 (Institutional Access)',
                'Referer': 'https://www.sciencedirect.com/',
                # Note: Add institutional token if available
                # 'X-ELS-Insttoken': 'your_institutional_token',
            }
            
            # Try different approaches to get PDF from the URL
            pdf_endpoints = [
                f"{url}?httpAccept=application/pdf",
                f"{url}/pdfft",  # PDF full-text endpoint
                f"{url}?download=true",
                url,  # Direct access
            ]
            
            for endpoint in pdf_endpoints:
                try:
                    self.logger.debug(f"Trying full-text endpoint: {endpoint[:50]}...")
                    response = await self.network.get(endpoint, headers=headers)
                    
                    if response.status_code == 200:
                        content = response.content
                        content_type = response.headers.get('content-type', '').lower()
                        
                        if 'application/pdf' in content_type and content.startswith(b'%PDF'):
                            file_size = len(content)
                            
                            # Accept large PDFs as likely complete
                            if file_size > 500000:
                                with open(output_path, 'wb') as f:
                                    f.write(content)
                                self.logger.info(f"✅ ScienceDirect PDF: {format_file_size(file_size)}")
                                return True, file_size
                    
                except Exception as e:
                    self.logger.debug(f"Full-text endpoint failed: {e}")
                    continue
                    
        except Exception as e:
            self.logger.debug(f"Full-text download error: {e}")
        
        return False, 0
    
    async def _fallback_content_api(self, doi: str, output_path: Path) -> Tuple[bool, int]:
        """Fallback to direct content API access."""
        try:
            headers = {
                'X-ELS-APIKey': self.api_key,
                'Accept': 'application/pdf,application/xml,*/*',
                'User-Agent': 'Academic Research Tool/2.0 (Institutional Access)',
                # Note: Add institutional token if available
                # 'X-ELS-Insttoken': 'your_institutional_token',
            }
            
            # Try the most promising direct endpoints
            endpoints = [
                f"https://api.elsevier.com/content/article/doi/{doi}?view=FULL&httpAccept=application/pdf",
                f"https://api.elsevier.com/content/article/doi/{doi}?httpAccept=application/pdf",
            ]
            
            best_content = None
            best_size = 0
            
            for endpoint in endpoints:
                try:
                    response = await self.network.get(endpoint, headers=headers)
                    
                    if response.status_code == 200:
                        content = response.content
                        content_type = response.headers.get('content-type', '').lower()
                        
                        if 'application/pdf' in content_type and content.startswith(b'%PDF'):
                            file_size = len(content)
                            if file_size > best_size:
                                best_content = content
                                best_size = file_size
                                
                except Exception as e:
                    self.logger.debug(f"Fallback endpoint failed: {e}")
                    continue
            
            # Use best available content
            if best_content and best_size > 50000:
                with open(output_path, 'wb') as f:
                    f.write(best_content)
                
                self.logger.warning(f"⚠️ Fallback PDF downloaded: {format_file_size(best_size)}")
                return True, best_size
            
        except Exception as e:
            self.logger.debug(f"Fallback download error: {e}")
        
        return False, 0
    
    def _doi_to_pii(self, doi: str) -> Optional[str]:
        """Convert DOI to PII (Publisher Item Identifier) if possible."""
        if not doi:
            return None
        
        # Basic PII extraction for Elsevier DOIs
        # This is a simplified approach - real PII conversion would need more sophisticated logic
        if doi.startswith('10.1016/'):
            # Extract potential PII from DOI path
            pii_candidate = doi.replace('10.1016/', '').replace('/', '').replace('.', '').upper()
            if len(pii_candidate) >= 12:  # Typical PII length
                return pii_candidate[:17]  # Standard PII format
        
        return None
    
    async def get_full_text(self, paper: Paper) -> str:
        """Get full text content from Elsevier API.
        
        Args:
            paper: Paper object with DOI
            
        Returns:
            str: Full text content or empty string
        """
        if not paper.doi or not is_elsevier_doi(paper.doi):
            return ""
        
        await self.rate_limiter.wait_if_needed()
        
        headers = {
            'X-ELS-APIKey': self.api_key,
            'Accept': 'application/xml,text/xml',
            'User-Agent': 'Academic Research Tool/2.0'
        }
        
        url = f"https://api.elsevier.com/content/article/doi/{paper.doi}"
        
        try:
            response = await self.network.get(url, headers=headers)
            
            if response.status_code == 200:
                return self._extract_text_from_xml(response.text)
            
        except Exception as e:
            self.logger.debug(f"Full text retrieval failed: {e}")
        
        return ""
    
    def _extract_text_from_xml(self, xml_content: str) -> str:
        """Extract readable text from XML response."""
        if not BS4_AVAILABLE:
            # Simple text extraction without BeautifulSoup
            import re
            text = re.sub(r'<[^>]+>', ' ', xml_content)
            text = re.sub(r'\s+', ' ', text).strip()
            return text[:10000]  # Limit length
        
        try:
            soup = BeautifulSoup(xml_content, 'xml')
            content_parts = []
            
            # Extract title
            title_tags = ['dc:title', 'title', 'ce:title']
            for tag in title_tags:
                title = soup.find(tag)
                if title and title.get_text().strip():
                    content_parts.append(f"Title: {title.get_text().strip()}")
                    break
            
            # Extract abstract
            abstract_tags = ['dc:description', 'abstract', 'ce:abstract']
            for tag in abstract_tags:
                abstract = soup.find(tag)
                if abstract and len(abstract.get_text().strip()) > 50:
                    content_parts.append(f"Abstract: {abstract.get_text().strip()}")
                    break
            
            # Extract body content
            body_tags = ['body', 'ce:body', 'ce:sections']
            for tag in body_tags:
                body = soup.find(tag)
                if body:
                    text = body.get_text().strip()
                    if len(text) > 100:
                        content_parts.append(f"Content: {text}")
                        break
            
            return "\n\n".join(content_parts)[:15000]  # Limit total length
            
        except Exception as e:
            self.logger.debug(f"XML parsing failed: {e}")
            return xml_content[:10000]


class AnnaArchiveDownloader:
    """Anna Archive PDF downloader - for non-Elsevier journals (based on original paper.py implementation)"""
    
    def __init__(self, api_config: APIConfig, rate_limiter: RateLimiter):
        # Read Anna Archive API Key directly from environment variables (as in original paper.py)
        self.api_key = os.getenv('ANNA_ARCHIVE_API_KEY', '')
        self.rate_limiter = rate_limiter
        self.logger = logging.getLogger(__name__)
        self.network = NetworkSession()
        self.base_url = "https://annas-archive.org"
        
        if self.api_key:
            self.logger.info("🔑 Anna Archive API Key configured - high-speed download enabled")
        else:
            self.logger.info("⚠️ Anna Archive API Key not configured - using standard download mode")
    
    @retry_on_failure(max_retries=3)
    async def download_pdf(self, paper: Paper, output_path: Path) -> Tuple[bool, int]:
        """Download PDF for non-Elsevier journals
        
        Args:
            paper: Paper object
            output_path: Output file path
            
        Returns:
            Tuple[bool, int]: (Success status, file size)
        """
        if not paper.doi:
            self.logger.warning("DOI is empty, cannot download PDF")
            return False, 0
        
        self.logger.info(f"🔍 Anna Archive downloading PDF: {paper.doi}")
        
        try:
            # Step 1: First get the file's MD5
            md5_hash = await self._get_file_md5(paper.doi)
            if not md5_hash:
                self.logger.warning(f"Unable to get MD5 hash for {paper.doi}")
                return False, 0
            
            self.logger.debug(f"Obtained MD5: {md5_hash}")
            
            # Step 2: Use official API to get fast download URL
            if self.api_key:
                download_url = await self._get_fast_download_url(md5_hash)
                if download_url:
                    self.logger.debug("Using official fast download API")
                    success, file_size = await self._download_from_url(download_url, output_path)
                    if success:
                        self.logger.info(f"✅ Fast download successful: {output_path.name} ({file_size:,} bytes)")
                        return True, file_size
            
            # Step 3: Backup method - download using MD5 endpoint
            self.logger.debug("Trying MD5 endpoint download")
            success, file_size = await self._download_by_md5(md5_hash, output_path)
            if success:
                return True, file_size
            
            # Method 2: Traditional search method
            self.logger.debug("SciDB direct access failed, trying traditional search...")
            md5_hash = await self._find_md5_by_search(paper.doi)
            if md5_hash:
                self.logger.debug(f"Search found MD5: {md5_hash}")
                success, file_size = await self._download_by_md5(md5_hash, output_path)
                if success:
                    return True, file_size
            
            return False, 0
            
        except Exception as e:
            self.logger.error(f"Anna Archive download failed: {e}")
            return False, 0
    
    async def _get_file_md5(self, doi: str) -> Optional[str]:
        """Get file MD5 hash from DOI"""
        try:
            # Method 1: Get MD5 from SciDB DOI page
            scidb_url = f"{self.base_url}/scidb/{doi}/"
            self.logger.debug(f"Accessing SciDB page to get MD5: {scidb_url}")
            
            response = await self.network.get(scidb_url)
            
            if response.status_code == 200:
                # Get MD5 from page
                md5_pattern = r'\b([a-f0-9]{32})\b'
                md5_matches = re.findall(md5_pattern, response.text, re.IGNORECASE)
                
                if md5_matches:
                    return md5_matches[0]
            
            # Method 2: Use search strategy to get MD5
            search_queries = [
                doi,
                doi.replace('/', ' '),
                f'doi:{doi}'
            ]
            
            for query in search_queries:
                md5_hash = await self._search_strategy(query)
                if md5_hash:
                    return md5_hash
            
            return None
            
        except Exception as e:
            self.logger.debug(f"Failed to get MD5: {e}")
            return None
    
    async def _get_fast_download_url(self, md5_hash: str) -> Optional[str]:
        """Get fast download URL using official API"""
        try:
            api_url = f"{self.base_url}/dyn/api/fast_download.json"
            params = {
                'md5': md5_hash,
                'key': self.api_key
            }
            
            self.logger.debug(f"Requesting fast download API: {api_url}")
            
            response = await self.network.get(api_url, params=params)
            
            if response.status_code in [200, 204]:
                try:
                    data = response.json()
                    download_url = data.get('download_url')
                    
                    if download_url and download_url != 'null':
                        self.logger.debug(f"Got fast download URL: {download_url[:50]}...")
                        return download_url
                    else:
                        error_msg = data.get('error', 'Unknown error')
                        self.logger.debug(f"Fast download API returned error: {error_msg}")
                        return None
                        
                except Exception as json_error:
                    self.logger.debug(f"Failed to parse fast download API response: {json_error}")
                    return None
            else:
                self.logger.debug(f"Fast download API status code: {response.status_code}")
                return None
                
        except Exception as e:
            self.logger.debug(f"Fast download API request failed: {e}")
            return None
    
    async def _find_md5_by_search(self, doi: str) -> Optional[str]:
        """Find MD5 hash through search"""
        search_strategies = [
            f'"doi:{doi}"',           # Most effective format
            f'doi:{doi}',             # Backup format
            doi,                      # Direct DOI
            f'"{doi}"',              # Quoted
        ]
        
        for i, strategy in enumerate(search_strategies):
            try:
                self.logger.debug(f"Search strategy {i+1}: '{strategy}'")
                md5_hash = await self._search_strategy(strategy)
                if md5_hash:
                    self.logger.debug(f"Strategy {i+1} successful: {md5_hash}")
                    return md5_hash
                await asyncio.sleep(0.8)  # Rate limiting
            except Exception as e:
                self.logger.debug(f"Strategy {i+1} failed: {e}")
                continue
        
        self.logger.warning(f"All search strategies failed: {doi}")
        return None
    
    async def _search_strategy(self, query: str) -> Optional[str]:
        """Execute single search strategy"""
        search_url = f"{self.base_url}/search"
        params = {'q': query}
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }
        
        try:
            response = await self.network.get(search_url, params=params, headers=headers)
            
            if response.encoding is None:
                response.encoding = 'utf-8'
            
            content = response.text
            
            # Extract MD5 hash
            md5_patterns = [
                r'\b([a-f0-9]{32})\b',
                r'/md5/([a-f0-9]{32})',
                r'/fast_download/([a-f0-9]{32})',
                r'md5[=:]\s*([a-f0-9]{32})',
            ]
            
            for pattern in md5_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                if matches:
                    for match in matches:
                        if len(match) == 32 and all(c in '0123456789abcdef' for c in match.lower()):
                            return match.lower()
            
            return None
            
        except Exception as e:
            self.logger.debug(f"Search request failed: {e}")
            return None
    
    async def _download_by_md5(self, md5_hash: str, output_path: Path) -> Tuple[bool, int]:
        """Download PDF using MD5 hash"""
        self.logger.debug(f"Trying MD5 download: {md5_hash}")
        
        download_endpoints = [
            f"{self.base_url}/md5/{md5_hash}",
            f"{self.base_url}/fast_download/{md5_hash}",
            f"{self.base_url}/download/{md5_hash}",
        ]
        
        for i, endpoint in enumerate(download_endpoints):
            try:
                self.logger.debug(f"Endpoint {i+1}: {endpoint}")
                
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                    'Accept': 'application/pdf,application/octet-stream,*/*',
                }
                
                response = await self.network.get(endpoint, headers=headers)
                
                # Check if it's a PDF
                content_type = response.headers.get('content-type', '').lower()
                is_pdf = (
                    response.content.startswith(b'%PDF') or
                    'application/pdf' in content_type or
                    len(response.content) > 1000
                )
                
                if is_pdf:
                    with open(output_path, 'wb') as f:
                        f.write(response.content)
                    file_size = len(response.content)
                    self.logger.debug(f"PDF download successful: {file_size} bytes")
                    return True, file_size
                
            except Exception as e:
                self.logger.debug(f"Endpoint {i+1} failed: {e}")
                continue
        
        return False, 0
    
    async def _download_from_url(self, url: str, output_path: Path) -> Tuple[bool, int]:
        """Download PDF from URL"""
        try:
            response = await self.network.get(url, allow_redirects=True)
            content = response.content
            
            if not content or len(content) < 1000:
                self.logger.debug(f"Download content too small: {len(content)} bytes")
                return False, 0
            
            # Check content type
            if content.startswith(b'%PDF'):
                # Direct PDF content
                with open(output_path, 'wb') as f:
                    f.write(content)
                self.logger.debug(f"Direct PDF download successful: {len(content)} bytes")
                return True, len(content)
            
            elif len(content) > 50000:
                # Possible other PDF format
                with open(output_path, 'wb') as f:
                    f.write(content)
                
                # Check if saved file is PDF
                with open(output_path, 'rb') as f:
                    first_bytes = f.read(10)
                    if b'%PDF' in first_bytes:
                        self.logger.debug(f"PDF content confirmed: {len(content)} bytes")
                        return True, len(content)
                
                # Delete file if not PDF
                output_path.unlink()
            
            self.logger.debug(f"Content not recognized as PDF: {content[:20]}")
            return False, 0
            
        except Exception as e:
            self.logger.debug(f"Download failed from {url}: {e}")
            return False, 0
    


class DownloadManager:
    """Manages PDF downloads for both Elsevier and non-Elsevier papers."""
    
    def __init__(self, api_config: APIConfig):
        self.logger = logging.getLogger(__name__)
        
        # Initialize downloaders with appropriate rate limits
        elsevier_limiter = RateLimiter(calls_per_minute=50)
        anna_limiter = RateLimiter(calls_per_minute=30)
        
        self.elsevier_downloader = ElsevierDownloader(api_config, elsevier_limiter)
        self.anna_downloader = AnnaArchiveDownloader(api_config, anna_limiter)
    
    async def download_paper(self, paper: Paper, output_path: Path) -> bool:
        """Download PDF for a paper with enhanced fallback."""
        if not paper.doi:
            self.logger.warning(f"No DOI for paper: {paper.title[:50]}...")
            paper.download_status = DownloadStatus.FAILED
            return False
        
        paper.download_status = DownloadStatus.DOWNLOADING
        
        try:
            # Try primary download method
            if is_elsevier_doi(paper.doi):
                self.logger.debug(f"Trying Elsevier download: {paper.doi}")
                success, file_size = await self.elsevier_downloader.download_pdf(paper, output_path)
            else:
                self.logger.debug(f"Trying Anna Archive download: {paper.doi}")
                success, file_size = await self.anna_downloader.download_pdf(paper, output_path)
            
            if success:
                paper.download_status = DownloadStatus.DOWNLOADED
                paper.pdf_filename = output_path.name
                paper.pdf_size = file_size
                self.logger.info(f"✅ Download successful: {paper.title[:50]}...")
                return True
            else:
                # Try alternative method if primary fails
                self.logger.warning(f"Primary download failed, trying alternative: {paper.doi}")
                
                if is_elsevier_doi(paper.doi):
                    # If Elsevier failed, try Anna Archive as backup
                    success, file_size = await self.anna_downloader.download_pdf(paper, output_path)
                    if success:
                        paper.download_status = DownloadStatus.DOWNLOADED
                        paper.pdf_filename = output_path.name
                        paper.pdf_size = file_size
                        self.logger.info(f"✅ Anna Archive backup successful: {paper.title[:50]}...")
                        return True
                
                # If all methods failed
                paper.download_status = DownloadStatus.FAILED
                self.logger.warning(f"❌ All download methods failed: {paper.title[:50]}...")
                return False
                
        except Exception as e:
            self.logger.error(f"Download exception: {e}")
            paper.download_status = DownloadStatus.FAILED
            return False
    
 