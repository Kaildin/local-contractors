import requests

url = input("inserisci url")
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

r = requests.get(url, headers=headers, timeout=15, allow_redirects=True, verify=False)
print("Status code:", r.status_code)
print("Final URL:", r.url)
