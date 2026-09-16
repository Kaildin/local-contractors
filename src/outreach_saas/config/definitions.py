import re

# Modifica delle regex di email per maggiore precisione
EMAIL_PATTERNS = [
    r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b',
    r'mailto:\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b'
]

KEYWORDS_BY_INDUSTRY = {
    "metalmeccanica": [
        "officina meccanica",
        "lavorazioni meccaniche",
        "lavorazioni cnc",
        "meccanica di precisione",
        "torneria",
        "fresatura cnc",
        "carpenteria metallica",
        "costruzioni meccaniche",
        "taglio laser metalli",
        "piegatura lamiera",
        "saldatura industriale",
    ],
    "plastica": [
        "stampaggio plastica",
        "stampaggio materie plastiche",
        "iniezione plastica",
        "estrusione plastica",
        "termoformatura plastica",
        "lavorazioni plastica",
    ],
    "legno_arredo": [
        "falegnameria industriale",
        "produzione mobili",
        "mobilificio",
        "fabbrica mobili",
        "lavorazione pannelli legno",
        "lavorazione legno industriale",
        "serramenti legno",
        "infissi legno",
    ],
    "ceramica_laterizi_cemento": [
        "ceramica industriale",
        "piastrelificio",
        "fabbrica piastrelle",
        "fornace laterizi",
        "laterificio",
        "cementificio",
        "calcestruzzo preconfezionato",
    ],
    "carta_packaging_stampa": [
        "cartiera",
        "scatolificio",
        "produzione imballaggi cartone",
        "produzione imballaggi",
        "cartotecnica",
        "tipografia industriale",
        "stamperia industriale",
        "stampa offset",
        "stampa flessografica",
    ],
    "alimentare_industriale": [
        "panificio industriale",
        "forno industriale",
        "caseificio industriale",
        "latteria industriale",
        "salumificio",
        "pastificio industriale",
        "laboratorio alimentare industriale",
        "industria alimentare",
    ],
    "vetro_alluminio_serramenti": [
        "vetreria industriale",
        "vetreria",
        "produzione infissi alluminio",
        "produzione serramenti alluminio",
        "produzione serramenti pvc",
        "fabbrica serramenti",
        "officina infissi",
    ],
    "fotovoltaico": [
        "fotovoltaico",
        "impianti fotovoltaici",
    ],
    "domotica": [
        "domotica",
        "smart home",
        "automazione casa",
        "impianti domotici",
    ],
}

INDUSTRY_CONFIG = {
    "metalmeccanica": {
        "positive": [
            "lavorazioni", "produzione", "industriale",
            "cnc", "torneria", "fresatura",
            "carpenteria", "taglio laser", "piegatura",
            "lamiera", "saldatura", "costruzioni meccaniche",
            "officina stampi", "costruzione stampi",
            "macchine utensili", "macchinari industriali",
        ],
        "negative": [
            "riparazione", "assistenza", "centro assistenza",
            "ricambi", "autofficina", "carrozzeria",
            "usato", "vendita", "negozio",
            "concessionaria", "noleggio auto",
        ],
    },
    "plastica": {
        "positive": [
            "stampaggio", "iniezione", "estrusione",
            "termoformatura", "produzione",
            "materie plastiche", "polimeri",
            "soffiaggio", "profili plastici",
        ],
        "negative": [
            "negozio", "rivendita", "vendita", "shop",
            "bricolage", "fai da te", "casalinghi",
        ],
    },
    "fotovoltaico": {
        "positive": [
            "fotovoltaico", "pannelli", "inverter", "accumulo",
            "impianto", "energia solare", "kwh", "kwp",
        ],
        "negative": [
            "riparazione elettrodomestici", "negozio", "rivendita",
            "ecommerce", "supermercato",
        ],
    },
    "domotica": {
        "positive": [
            "domotica", "smart home", "automazione", "knx",
            "home automation", "controllo luci", "termostato smart",
            "building automation",
        ],
        "negative": [
            "negozio", "rivendita", "ecommerce",
            "informatica", "telefonia",
        ],
    },
    "legno_arredo": {
        "positive": [
            "produzione", "fabbrica", "industriale",
            "mobilificio", "mobili", "falegnameria",
            "pannelli legno", "lavorazione legno",
            "arredamento", "cucine su misura",
        ],
        "negative": [
            "negozio", "showroom", "rivendita",
            "design", "interior design",
            "arredamento negozio", "mobilificio al dettaglio",
        ],
    },
    "ceramica_laterizi_cemento": {
        "positive": [
            "ceramica", "piastrelificio", "piastrelle",
            "fornace", "laterizi", "laterificio",
            "cementificio", "calcestruzzo", "prefabbricati",
            "blocco cemento",
        ],
        "negative": [
            "negozio", "rivendita", "showroom",
            "arredo bagno", "rivenditore ceramiche",
            "fai da te", "bricolage",
        ],
    },
    "carta_packaging_stampa": {
        "positive": [
            "cartiera", "cartotecnica", "scatolificio",
            "imballaggi", "packaging", "imballaggi cartone",
            "stampa", "tipografia", "stamperia",
            "offset", "flessografica", "etichette adesive",
        ],
        "negative": [
            "copisteria", "cartoleria", "negozio",
            "service stampa", "fotocopie",
            "shop online",
        ],
    },
    "alimentare_industriale": {
        "positive": [
            "panificio industriale", "forno industriale",
            "caseificio", "latteria", "salumificio",
            "pastificio", "laboratorio alimentare",
            "stabilimento", "trasformazione alimentare",
            "confezionamento alimentare",
        ],
        "negative": [
            "ristorante", "pizzeria", "bar",
            "gastronomia", "panificio artigianale",
            "negozio alimentari", "supermercato",
        ],
    },
    "vetro_alluminio_serramenti": {
        "positive": [
            "vetreria", "vetreria industriale",
            "serramenti", "infissi", "alluminio",
            "pvc", "fabbrica serramenti",
            "officina infissi", "produzione infissi",
        ],
        "negative": [
            "showroom", "negozio",
            "rivendita serramenti", "posa serramenti",
            "installazione infissi",
        ],
    },
}

IGNORED_EMAIL_DOMAINS = {
    "sentry.io", "wixpress.com", "sentry.wixpress.com", 
    "sentrynext.wixpress.com", "users.wix.com",
    "example.com", "test.com", "yourdomain.com", "mydomain.com",
    "website.com", "domain.com", "localhost",
    "google.com", "googleapis.com", "googleusercontent.com", "googlegroups.com",
    "facebook.com", "twitter.com", "instagram.com",
    "doubleclick.net", "googletagmanager.com", "googleadservices.com",
    "gstatic.com", "googlesyndication.com", "wixstatic.com",
    "amazonaws.com", "appspot.com", "cdn.com", "cloudfront.net",
    "windows.net", "azure.com", "microsoft.com", "msn.com", "outlook.com", "live.com",
    "apple.com", "icloud.com",
    "yahoo.com", "aol.com", "mail.com"
}

LOCAL_PART_IGNORE_PATTERNS = [
    re.compile(r"^[a-f0-9]{24,}$"),
    re.compile(r"^[a-z0-9]{30,}$"),
    re.compile(r"^(noreply|no-reply|donotreply|unsubscribe|mailer-daemon|postmaster|abuse|bounces?|devnull|null)$"),
    re.compile(r"privacy|gdpr|legal|copyright", re.IGNORECASE),
    re.compile(r"^.{1,2}@"),
    re.compile(r"^(info|contact|support|sales|admin|office|hello|enquiries|marketing)$")
]

BIG_COMPANY_KEYWORDS = [
    "enel", "eni", "edison", "a2a", "sorgenia", "iren", "hera", "vivi energia", 
    "engie", "acea", "e.on", "axpo", "multinazionale", "gruppo", "corporation", 
    "holding", "s.p.a.", "spa"
]
