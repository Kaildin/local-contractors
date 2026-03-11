import re
from urllib.parse import urlparse

def clean_url(url):
    """Pulisce l'URL del sito web (rimuove percorsi e parametri)"""
    if not url:
        return ""
    
    # Rimuovi mailto: se presente
    url = url.replace("mailto:", "")
    
    # Analizziamo l'URL
    try:
        parsed = urlparse(url)
        
        # Costruisci l'URL base (schema + netloc)
        # Se manca lo schema, assume http o lascia vuoto se invalido
        if not parsed.netloc and parsed.path:
             # Caso url tipo "www.google.com" senza schema
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
    
    # Rimuovi prefissi comuni
    prefixes = ["Indirizzo:", "Address:", "Telefono:", "Phone:", "Tel:", "Website:", "Sito web:"]
    cleaned = text
    for prefix in prefixes:
        cleaned = cleaned.replace(prefix, "")
    
    # Rimuovi caratteri di controllo e spazi extra
    cleaned = re.sub(r'[\n\r\t]', ' ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned)
    
    # Rimuovi caratteri speciali e spazi all'inizio
    cleaned = re.sub(r'^[\s,.:;-]+', '', cleaned)
    
    # Rimuovi icone Google Maps
    cleaned = cleaned.replace('', '').replace('', '')
    
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
