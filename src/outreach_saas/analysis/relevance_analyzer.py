import re
import requests
import logging
from typing import Optional, Dict, List, NamedTuple
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from ..config.definitions import INDUSTRY_CONFIG

logger = logging.getLogger(__name__)

class RelevanceResult(NamedTuple):
    """Risultato dell'analisi di pertinenza"""
    relevant: bool
    score: int
    category: str
    confidence: str
    reason: str

class WebsiteRelevanceAnalyzer:
    def __init__(
        self,
        industry: str = "fotovoltaico",
        industry_config: Optional[Dict[str, Dict[str, List[str]]]] = None,
        min_score: int = 20,
    ):
        self.industry = industry
        self.min_score = min_score

        if industry_config is None:
            industry_config = INDUSTRY_CONFIG

        conf = industry_config.get(industry)
        if not conf:
            raise ValueError(
                f"Industry '{industry}' non presente in INDUSTRY_CONFIG. "
                f"Disponibili: {list(industry_config.keys())}"
            )

        self.positive_keywords = [k.lower().strip() for k in conf.get("positive", []) if k.strip()]
        self.negative_keywords = [k.lower().strip() for k in conf.get("negative", []) if k.strip()]

        self._pos_patterns = [re.compile(re.escape(k), re.IGNORECASE) for k in self.positive_keywords]
        self._neg_patterns = [re.compile(re.escape(k), re.IGNORECASE) for k in self.negative_keywords]

        self.fotovoltaico_keywords = self.positive_keywords if industry == "fotovoltaico" else []
        self.domotica_keywords = self.positive_keywords if industry == "domotica" else []
        
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }

    @staticmethod
    def _normalize(text: Optional[str]) -> str:
        if not text:
            return ""
        t = text.lower()
        t = re.sub(r"\s+", " ", t)
        return t.strip()

    @staticmethod
    def _count_hits(text: str, patterns: List[re.Pattern]) -> int:
        hits = 0
        for p in patterns:
            if p.search(text):
                hits += 1
        return hits

    def analyze_text(self, text: str) -> RelevanceResult:
        """Analisi di pertinenza su testo generico."""
        t = self._normalize(text)
        pos_hits = self._count_hits(t, self._pos_patterns)
        neg_hits = self._count_hits(t, self._neg_patterns)

        raw = (pos_hits * 12) - (neg_hits * 18)
        score = max(0, min(100, 50 + raw))

        relevant = score >= self.min_score and pos_hits >= max(1, neg_hits)

        confidence = self._confidence(score, pos_hits, neg_hits)
        reason = f"pos_hits={pos_hits}, neg_hits={neg_hits}, score={score}"

        return RelevanceResult(
            relevant=relevant,
            score=score,
            category=self.industry,
            confidence=confidence,
            reason=reason,
        )

    @staticmethod
    def _confidence(score: int, pos_hits: int, neg_hits: int) -> str:
        if score >= 70 and pos_hits >= 3 and neg_hits == 0:
            return "alta"
        if score >= 40 and pos_hits >= 2:
            return "media"
        return "bassa"

    def normalize_url(self, url):
        """Normalizza l'URL aggiungendo il protocollo se necessario."""
        if not url:
            return ""
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        return url
    
    def fetch_website_content(self, url):
        """Scarica il contenuto HTML del sito web."""
        if not url:
            return None
            
        try:
            url = self.normalize_url(url)
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                return response.text
            else:
                logger.warning(f"Impossibile accedere al sito {url}. Status code: {response.status_code}")
                return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Errore durante l'accesso a {url}: {e}")
            
            if url.startswith('https://'):
                try:
                    http_url = url.replace('https://', 'http://')
                    logger.info(f"Provo con protocollo HTTP: {http_url}")
                    response = requests.get(http_url, headers=self.headers, timeout=10)
                    if response.status_code == 200:
                        return response.text
                except:
                    pass
            return None
    
    def extract_domain(self, url):
        """Estrae il dominio principale dall'URL."""
        if not url:
            return ""
            
        try:
            parsed_url = urlparse(self.normalize_url(url))
            domain = parsed_url.netloc
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain
        except:
            return url
    
    def extract_text_from_html(self, html):
        """Estrae il testo pulito dall'HTML."""
        if not html:
            return ""
        
        soup = BeautifulSoup(html, 'html.parser')
        
        for script_or_style in soup(['script', 'style', 'iframe', 'noscript']):
            script_or_style.decompose()
        
        text = soup.get_text(separator=' ', strip=True)
        text = re.sub(r'\s+', ' ', text)
        
        return text.lower()
    
    def extract_meta_info(self, html):
        """Estrae informazioni da meta tag, titolo e descrizione."""
        if not html:
            return ""
        
        soup = BeautifulSoup(html, 'html.parser')
        meta_info = []
        
        if soup.title and soup.title.string:
            try:
                title_text = soup.title.string.strip()
                if title_text:
                    meta_info.append(title_text)
            except:
                pass
        
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc:
            try:
                content = meta_desc.get('content')
                if isinstance(content, str) and content.strip():
                    meta_info.append(content.strip())
            except:
                pass
        
        meta_keywords = soup.find('meta', attrs={'name': 'keywords'})
        if meta_keywords:
            try:
                content = meta_keywords.get('content')
                if isinstance(content, str) and content.strip():
                    meta_info.append(content.strip())
            except:
                pass
        
        for header in soup.find_all(['h1', 'h2', 'h3']):
            if header.text.strip():
                meta_info.append(header.text.strip())
        
        safe_parts = [part for part in meta_info if isinstance(part, str) and part]
        return ' '.join(safe_parts).lower()
    
    def analyze_website_relevance(self, url):
        """Analizza la pertinenza del sito web rispetto al settore specificato."""
        if not url:
            return {
                'is_relevant': False,
                'confidence': 0.0,
                'category': 'unknown',
                'reason': "URL non valido o mancante"
            }
            
        logger.info(f"Analisi pertinenza del sito: {url}")
        
        domain = self.extract_domain(url)
        domain_keywords = re.findall(r'([a-zA-Z]+)', domain)
        domain_text = ' '.join(domain_keywords).lower()
        
        industry_in_domain = any(kw in domain_text for kw in self.positive_keywords)
        
        if industry_in_domain:
            logger.info(f"Rilevanza immediata dal dominio: {domain}")
            return {
                'is_relevant': True,
                'confidence': 0.8,
                'category': self.industry,
                'reason': f"Parole chiave rilevanti nel dominio: {domain}"
            }
        
        html_content = self.fetch_website_content(url)
        if not html_content:
            return {
                'is_relevant': False, 
                'confidence': 0.5,
                'category': 'unknown',
                'reason': "Impossibile accedere al sito web"
            }
        
        full_text = self.extract_text_from_html(html_content)
        meta_text = self.extract_meta_info(html_content)
        
        weighted_text = meta_text + " " + meta_text + " " + full_text
        
        positive_matches = sum(weighted_text.count(kw) for kw in self.positive_keywords)
        negative_matches = sum(weighted_text.count(kw) for kw in self.negative_keywords)
        
        text_length_factor = min(1.0, 2000 / max(len(weighted_text), 500))
        positive_score = positive_matches * text_length_factor
        negative_score = negative_matches * text_length_factor
        
        total_score = positive_score - (negative_score * 1.5)
        
        is_relevant = total_score >= 3.0 and positive_matches >= max(1, negative_matches)
        category = self.industry if is_relevant else 'non_pertinente'
        
        confidence = min(1.0, max(0.5, 0.5 + (total_score / 20)))
        
        result = {
            'is_relevant': is_relevant,
            'confidence': round(confidence, 2),
            'category': category,
            'scores': {
                'positive': round(positive_score, 2),
                'negative': round(negative_score, 2),
                'total': round(total_score, 2)
            },
            'reason': self.generate_reason_website(is_relevant, positive_score, negative_score)
        }
        
        logger.info(f"Analisi completata per {url}: {result['is_relevant']} ({result['category']}, {result['confidence']})")
        return result
    
    def generate_reason_website(self, is_relevant, positive_score, negative_score):
        """Genera una spiegazione della decisione."""
        if not is_relevant:
            return f"Contenuto insufficiente relativo al settore {self.industry}"
        
        reason = f"Rilevato contenuto pertinente al settore {self.industry} "
        
        if positive_score > 8:
            reason += f"con alto numero di riferimenti specifici"
        else:
            reason += f"con riferimenti sufficienti"
            
        return reason
