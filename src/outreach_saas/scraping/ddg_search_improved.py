"""DuckDuckGo search using official duckduckgo_search library.

This replaces the previous HTML scraping approach with a more reliable
and maintainable solution using the DDGS API wrapper.
"""
import logging
import time
import random
from typing import List, Dict, Optional

try:
    from ddgs import DDGS
except ImportError:
    raise ImportError(
        "ddgs library not found. "
        "Install it with: pip install ddgs"
    )

logger = logging.getLogger(__name__)


class DDGSearcher:
    """DuckDuckGo searcher using official DDGS library.
    
    Vantaggi rispetto al vecchio metodo:
    - Niente scraping HTML fragile
    - API stabile e mantenuta
    - Delay minimi (1-3s invece di 8-60s)
    - Meno probabilita di ban
    - Codice piu pulito e manutenibile
    """
    
    def __init__(self, min_delay: float = 1.0, max_delay: float = 3.0):
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.current_delay = min_delay
        self.last_request_time = 0
        
    def _wait_with_jitter(self):
        elapsed = time.time() - self.last_request_time
        base_delay = random.uniform(self.min_delay, self.max_delay)
        wait_time = max(0, base_delay - elapsed)
        
        if wait_time > 0:
            logger.info(f"[DDGS] Waiting {wait_time:.1f}s before next request")
            time.sleep(wait_time)
        
        self.last_request_time = time.time()
    
    def search(self, query: str, max_results: int = 5, region: str = "wt-wt",
               safesearch: str = "moderate", timelimit: Optional[str] = None) -> List[Dict[str, str]]:
        """Esegue una ricerca su DuckDuckGo.
        
        Args:
            query: Query di ricerca
            max_results: Numero massimo di risultati (default 5)
            region: Regione (default "wt-wt" = worldwide, "it-it" = Italia)
            safesearch: Livello safesearch ("on", "moderate", "off")
            timelimit: Limite temporale ("d"=giorno, "w"=settimana, "m"=mese, "y"=anno)
        
        Returns:
            Lista di dizionari con 'title', 'snippet', 'url'
        """
        self._wait_with_jitter()
        
        logger.info(f"[DDGS] Starting search for: '{query}' (max_results={max_results})")
        
        try:
            with DDGS() as ddgs:
                raw_results = ddgs.text(
                    query,
                    region=region,
                    safesearch=safesearch,
                    timelimit=timelimit,
                    max_results=max_results
                )
                
                results = []
                for r in raw_results:
                    result = {
                        'title': r.get('title', ''),
                        'snippet': r.get('body', ''),
                        'url': r.get('href', '')
                    }
                    
                    if result['title'] and result['url']:
                        results.append(result)
                        logger.debug(f"[DDGS] Found: {result['title'][:50]}...")
                
                logger.info(f"[DDGS] Successfully found {len(results)} results")
                return results
                
        except Exception as e:
            logger.error(f"[DDGS] Error during search: {e}", exc_info=True)
            return []
    
    def search_with_retry(self, query: str, max_results: int = 5, max_retries: int = 3,
                          **kwargs) -> List[Dict[str, str]]:
        """Ricerca con retry automatico in caso di fallimento.
        
        Args:
            query: Query di ricerca
            max_results: Numero massimo di risultati
            max_retries: Numero massimo di tentativi
            **kwargs: Altri parametri per search()
        
        Returns:
            Lista di risultati
        """
        for attempt in range(1, max_retries + 1):
            logger.info(f"[DDGS] Attempt {attempt}/{max_retries}")
            
            results = self.search(query, max_results, **kwargs)
            
            if results:
                return results
            
            if attempt < max_retries:
                wait_time = random.uniform(2, 5) * attempt
                logger.warning(f"[DDGS] Retry after {wait_time:.1f}s...")
                time.sleep(wait_time)
        
        logger.error(f"[DDGS] All {max_retries} attempts failed for query: {query}")
        return []


_ddg_searcher = DDGSearcher()


def ddg_search_improved(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """Funzione wrapper compatibile con il codice esistente.
    
    Questa funzione mantiene la stessa interfaccia del vecchio metodo
    per garantire compatibilita retroattiva.
    
    Args:
        query: Query di ricerca
        max_results: Numero massimo di risultati (default 5)
    
    Returns:
        Lista di dizionari con 'title', 'snippet', 'url'
    """
    return _ddg_searcher.search_with_retry(query, max_results)
