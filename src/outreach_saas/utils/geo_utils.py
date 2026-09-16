import csv
import math
import logging
import time
import os
import random
import requests
import pandas as pd
from urllib.parse import quote_plus
from typing import List, Dict, Any, Tuple, Optional

logger = logging.getLogger(__name__)

def load_comuni(file_path="data/comuni_italiani.csv"):
    """Carica la lista dei comuni italiani da un file CSV"""
    comuni = []
    try:
        if not os.path.exists(file_path):
            logger.error(f"File comuni non trovato: {file_path}")
            return []
            
        with open(file_path, mode='r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                if 'denominazione_ita' in row:
                    comuni.append(row['denominazione_ita'])
                elif 'comune' in row:
                    comuni.append(row['comune'])
        
        logger.info(f"Caricati {len(comuni)} comuni da {file_path}")
        return comuni
    except Exception as e:
        logger.error(f"Errore nel caricamento dei comuni: {e}")
        return []

def _load_processed_comuni(processed_file="logs/comuni_elaborati.csv") -> set:
    """Carica la lista dei comuni gia elaborati dal log"""
    if not os.path.exists(processed_file):
        return set()
    
    try:
        df = pd.read_csv(processed_file)
        return set(df['comune'].tolist()) if 'comune' in df.columns else set()
    except Exception as e:
        logging.warning(f"Errore nel caricamento comuni elaborati: {e}")
        return set()

def _save_processed_comuni(comuni_list, processed_file="logs/comuni_elaborati.csv"):
    """Salva i comuni elaborati nel log"""
    try:
        os.makedirs(os.path.dirname(processed_file), exist_ok=True)
        
        all_new_comuni = set(comuni_list)
        existing = _load_processed_comuni(processed_file)
        
        final_set = existing.union(all_new_comuni)
        
        df = pd.DataFrame({'comune': sorted(list(final_set))})
        df.to_csv(processed_file, index=False)
        logger.info(f"Salvati comuni nel log {processed_file}. Totale: {len(final_set)}")
    except Exception as e:
        logger.error(f"Errore nel salvataggio dei comuni processati: {e}")

def filter_and_limit_comuni(all_comuni: List[str], processed_comuni: set, limit: Optional[int] = None, region_filter: Optional[str] = None) -> List[str]:
    """Filtra i comuni (escludendo quelli gia processati) e applica un limite opzionale"""
    available_comuni = [c for c in all_comuni if c not in processed_comuni]
    
    if not available_comuni:
        logger.warning("Nessun comune nuovo da processare.")
        return []
    
    random.shuffle(available_comuni)
    
    if limit:
        selected_comuni = available_comuni[:limit]
        logger.info(f"Selezionati {len(selected_comuni)} comuni su {len(available_comuni)} disponibili (limit={limit})")
    else:
        selected_comuni = available_comuni
        logger.info(f"Selezionati tutti i {len(available_comuni)} comuni disponibili")
        
    return selected_comuni

def get_comune_coordinates(comune_name: str) -> Optional[Dict[str, float]]:
    """Ottiene le coordinate geografiche di un comune utilizzando OpenStreetMap Nominatim API"""
    try:
        search_query = f"{comune_name}, Italia"
        encoded_query = quote_plus(search_query)
        url = f"https://nominatim.openstreetmap.org/search?q={encoded_query}&format=json&limit=1"
        
        headers = {
            'User-Agent': 'LocalContractorsScraper/1.0',
            'Accept': 'application/json'
        }
        
        response = requests.get(url, headers=headers)
        data = response.json()
        
        if data and len(data) > 0:
            lat = float(data[0]['lat'])
            lon = float(data[0]['lon'])
            
            if 'boundingbox' in data[0]:
                bbox = data[0]['boundingbox']
                lat_diff = abs(float(bbox[1]) - float(bbox[0]))
                lon_diff = abs(float(bbox[3]) - float(bbox[2]))
                
                earth_radius = 6371
                lat_km = lat_diff * (math.pi/180) * earth_radius
                lon_km = lon_diff * (math.pi/180) * earth_radius * math.cos(lat * math.pi/180)
                radius = max(lat_km, lon_km) / 2
                
                radius = max(2, min(radius, 10))
            else:
                radius = 5
                
            display_name = data[0].get('display_name', '')
            
            return {
                'lat': lat,
                'lon': lon,
                'radius': radius,
                'display_name': display_name
            }
        else:
            logging.warning(f"Coordinate non trovate per il comune: {comune_name}")
            return None
            
    except Exception as e:
        logging.error(f"Errore nel recupero delle coordinate per {comune_name}: {str(e)}")
        return None

def build_comune_coordinates_dict(comuni: List[str]) -> Dict[str, Dict[str, float]]:
    """Crea un dizionario di coordinate per tutti i comuni"""
    coordinates_dict = {}
    total_comuni = len(comuni)
    
    for i, comune in enumerate(comuni):
        logger.info(f"Recupero coordinate per {comune} ({i+1}/{total_comuni})")
        coordinates = get_comune_coordinates(comune)
        
        if coordinates:
            coordinates_dict[comune] = coordinates
            logger.info(f"Coordinate trovate per {comune}: {coordinates['lat']}, {coordinates['lon']}, raggio: {coordinates['radius']} km")
        else:
            logger.warning(f"Impossibile trovare coordinate per {comune}")
        
        time.sleep(1.5)
    
    return coordinates_dict

def is_within_comune_boundaries(lat, lon, comune_coords, max_distance_km=15):
    """Verifica se una posizione e all'interno dei confini di un comune"""
    if not lat or not lon or not comune_coords:
        return False
    
    try:
        def haversine(lat1, lon1, lat2, lon2):
            R = 6371
            dLat = math.radians(lat2 - lat1)
            dLon = math.radians(lon2 - lon1)
            a = (math.sin(dLat/2) * math.sin(dLat/2) +
                 math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
                 math.sin(dLon/2) * math.sin(dLon/2))
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
            distance = R * c
            return distance
        
        distance = haversine(
            float(lat), 
            float(lon), 
            float(comune_coords['lat']), 
            float(comune_coords['lon'])
        )
        
        max_radius = min(comune_coords['radius'], max_distance_km)
        
        return distance <= max_radius
        
    except Exception as e:
        logger.error(f"Errore nel calcolo della distanza: {str(e)}")
        return False

def generate_search_urls_with_coordinates(comuni: List[str], keywords: List[str], coordinates_dict: Dict[str, Dict[str, float]]) -> List[Dict[str, Any]]:
    """Genera URL di ricerca Google Maps combinando keyword e comuni, usando le coordinate"""
    urls = []
    
    comuni_with_coords = [c for c in comuni if c in coordinates_dict]
    missing = len(comuni) - len(comuni_with_coords)
    if missing > 0:
        logger.warning(f"{missing} comuni saltati per mancanza di coordinate.")
    
    for comune in comuni_with_coords:
        coords = coordinates_dict[comune]
        lat, lon = coords['lat'], coords['lon']
        radius = coords.get('radius', 5.0)

        for keyword in keywords:
            search_term = f"{keyword} {comune}"
            encoded_term = quote_plus(search_term)
            
            zoom = max(13 - int(radius/3), 10)
            
            url = f"https://www.google.com/maps/search/{encoded_term}/@{lat},{lon},{zoom}z"
            
            urls.append({
                "comune": comune, 
                "keyword": keyword, 
                "url": url,
                "lat": lat,
                "lon": lon,
                "radius": radius
            })
    
    return urls
