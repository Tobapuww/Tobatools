from typing import List, Dict
import requests


def load_manifest(url: str) -> List[Dict]:
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise ValueError("清单必须是数组")
    items: List[Dict] = []
    for it in data:
        if isinstance(it, dict):
            items.append(it)
    return items
