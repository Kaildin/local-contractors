"""DeepSeek v3 integration for admin name extraction.

DeepSeek v3 is a powerful and cost-effective alternative to GPT models:
- Performance: Comparable to GPT-4 on many tasks
- Cost: ~14x cheaper than GPT-3.5-turbo ($0.14/M vs $2/M tokens)
- Speed: Fast response times
- API: OpenAI-compatible, drop-in replacement

Usage:
    from deepseek_extractor import extract_admin_with_deepseek
    admin = extract_admin_with_deepseek(payload_text)

Requires:
    - pip install openai (same client, different endpoint)
    - DEEPSEEK_API_KEY in .env file

Get API key at: https://platform.deepseek.com/api_keys
"""
import logging
from typing import Optional
from openai import OpenAI

from ..config.settings import DEEPSEEK_API_KEY

logger = logging.getLogger(__name__)

# DeepSeek API endpoint (OpenAI-compatible)
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"


def extract_admin_with_deepseek(texts: str, timeout: int = 30) -> Optional[str]:
    """Estrae il nome dell'amministratore dai testi usando DeepSeek v3.
    
    Args:
        texts: Testo contenente informazioni sull'azienda (payload da DDG search)
        timeout: Timeout in secondi per la richiesta API (default 30s)
    
    Returns:
        Nome dell'amministratore estratto, o None se non trovato/errore
    """
    if not DEEPSEEK_API_KEY:
        logger.error("[DeepSeek] DEEPSEEK_API_KEY non configurata in .env")
        return None
    
    if not texts or not texts.strip():
        logger.warning("[DeepSeek] Testo vuoto fornito")
        return None
    
    try:
        client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
            timeout=timeout
        )
        
        prompt = f"""Analizza i seguenti risultati di ricerca e estrai SOLO il nome completo dell'amministratore, amministratore delegato, CEO, fondatore o titolare dell'azienda.

REGOLE IMPORTANTI:
1. Rispondi SOLO con il nome completo (es: "Mario Rossi")
2. NON aggiungere titoli, ruoli o spiegazioni
3. Se trovi pi persone, scegli la figura di maggior rilievo (amministratore > CEO > fondatore > titolare)
4. Se NON trovi alcun nome, rispondi ESATTAMENTE: "Nessun amministratore trovato"
5. Ignora nomi generici come "amministratore condominiale", "amministratore di sistema"
6. Cerca preferibilmente in:
   - Titoli come "Amministratore delegato: Nome Cognome"
   - Frasi come "L'amministratore Mario Rossi..."
   - Link LinkedIn con nomi associati a ruoli direttivi

TESTO DA ANALIZZARE:
{texts}

RISPOSTA (solo il nome):"""
        logger.info("[DeepSeek] Invio richiesta a DeepSeek v3...")
        
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "Sei un assistente esperto nell'estrazione di nomi di persone da testi. Segui ESATTAMENTE le istruzioni fornite."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.1,
            max_tokens=100,
            top_p=0.95
        )
        
        admin_name = response.choices[0].message.content.strip()
        
        logger.info(f"[DeepSeek] Risposta ricevuta: {admin_name}")
        logger.info(f"[DeepSeek] Token usati: prompt={response.usage.prompt_tokens}, completion={response.usage.completion_tokens}, totale={response.usage.total_tokens}")
        
        negative_phrases = [
            "nessun amministratore",
            "non ho trovato",
            "non e possibile",
            "non trovato",
            "non disponibile",
            "non riesco",
            "non sono in grado",
            "non presente"
        ]
        
        admin_name_lower = admin_name.lower()
        if any(phrase in admin_name_lower for phrase in negative_phrases):
            logger.warning(f"[DeepSeek] Nessun amministratore trovato nel testo")
            return None
        
        words = admin_name.split()
        if len(words) < 2:
            logger.warning(f"[DeepSeek] Nome estratto troppo corto o invalido: '{admin_name}'")
            return None
        
        if len(words) > 5:
            logger.warning(f"[DeepSeek] Risposta troppo lunga, probabilmente non e un nome: '{admin_name}'")
            return None
        
        logger.info(f"[DeepSeek] Amministratore estratto: {admin_name}")
        return admin_name
        
    except Exception as e:
        logger.error(f"[DeepSeek] Errore durante l'estrazione: {e}", exc_info=True)
        return None


def extract_admin_with_deepseek_batch(texts_list: list[str], timeout: int = 30) -> list[Optional[str]]:
    """Estrae amministratori da una lista di testi in batch.
    
    Args:
        texts_list: Lista di testi da analizzare
        timeout: Timeout in secondi per la richiesta API
    
    Returns:
        Lista di nomi estratti (None se non trovato per quel testo)
    """
    results = []
    for i, texts in enumerate(texts_list, 1):
        logger.info(f"[DeepSeek Batch] Elaborazione {i}/{len(texts_list)}")
        admin = extract_admin_with_deepseek(texts, timeout=timeout)
        results.append(admin)
    return results
