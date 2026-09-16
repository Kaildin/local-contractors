import re
from urllib.parse import urlparse

def clean_url(url):
    """Pulisce l'URL del sito web (rimuove percorsi e parametri)"""
    if not url:
        return ""
    
    url = url.replace("mailto:", "")
    
    try:
        parsed = urlparse(url)
        
        if not parsed.netloc and parsed.path:
             if "." in parsed.path:
                 return f"http://{parsed.path}"
             return url
             
        clean = f"{parsed.scheme}://{parsed.netloc}"
        
        return clean
    except:
        return url

def clean_extracted_text(text):
    """Pulisce il testo estratto rimuovendo prefissi, caratteri indesiderati e spazi iniziali"""
    if not text:
        return ""
    
    prefixes = ["Indirizzo:", "Address:", "Telefono:", "Phone:", "Tel:", "Website:", "Sito web:"]
    cleaned = text
    for prefix in prefixes:
        cleaned = cleaned.replace(prefix, "")
    
    cleaned = re.sub(r'[\n\r\t]', ' ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned)
    
    cleaned = re.sub(r'^[\s,.:;-]+', '', cleaned)
    
    cleaned = cleaned.replace('\ue0c8', '').replace('\ue0b0', '')
    
    return cleaned.strip()

def normalize_text(text: str) -> str:
    """Normalizza stringhe generiche: lowercase, strip spazi"""
    if not text:
        return ""
    t = text.lower()
    t = re.sub(r"\s+", " ", t)
    return t.strip()

def is_same_domain(url: str, candidate: str) -> bool:
    """Verifica se due URL appartengono allo stesso dominio (o sottodominio)"""
    try:
        u = urlparse(url)
        c = urlparse(candidate)
        u_base = u.netloc.split(':')[0].lower().replace('www.', '')
        c_base = c.netloc.split(':')[0].lower().replace('www.', '')
        
        return u_base == c_base
    except:
        return False
