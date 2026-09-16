import os
from dotenv import load_dotenv

load_dotenv()

# API Keys
try:
    OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
except KeyError:
    OPENAI_API_KEY = None

# DeepSeek API Key (alternative to OpenAI, much cheaper)
try:
    DEEPSEEK_API_KEY = os.environ["DEEPSEEK_API_KEY"]
except KeyError:
    DEEPSEEK_API_KEY = None

SCRAPING_METHOD = "selenium"
API_KEY = "TUA_API_KEY_SERPAPI"
GOOGLE_PLACES_API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY", os.environ.get("GOOGLE_MAPS_API_KEY", ""))

# Other constants
OUTPUT_FILE = "aziende_fotovoltaico_filtrate.csv"
PLACES_DETAILS_MODE = os.environ.get("PLACES_DETAILS_MODE", "web")
