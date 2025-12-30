from typing import Dict
import requests

REGISTRY_URL = "https://gitee.com/AQ16/Resilience/raw/Mellifluous/.github/workflows/Wanderlust"


def check_registration(serial: str) -> Dict:
    """
    Return {registered: bool, qq: str|None, name: str|None, id: str}
    Logic mirrors the provided shell: find a line exactly equal to serial, then
    take the next line (expected commented with #) containing: "<qq> <name...>".
    """
    result = {"registered": False, "qq": None, "name": None, "id": serial or ""}
    if not serial:
        return result
    try:
        text = requests.get(REGISTRY_URL, timeout=10).text
    except Exception:
        return result

    lines = [ln.strip().lstrip("\ufeff") for ln in text.splitlines()]  # trim and drop BOM
    # Search from bottom to top, prefer last occurrence
    for i in range(len(lines) - 1, -1, -1):
        if lines[i] == serial:
            # As per user's layout: info is on the PREVIOUS line of the serial
            k = i - 1
            while k >= 0 and lines[k] == "":
                k -= 1
            if k >= 0:
                prv = lines[k]
                if prv.startswith('#'):
                    prv = prv.lstrip('#').strip()
                parts = prv.split()
                if parts:
                    qq = parts[0]
                    name = " ".join(parts[1:]) if len(parts) > 1 else ""
                    result.update({"registered": True, "qq": qq, "name": name})
                    return result
            # fallback: try next non-empty line as info
            j = i + 1
            while j < len(lines) and lines[j] == "":
                j += 1
            if j < len(lines):
                nxt = lines[j]
                if nxt.startswith('#'):
                    nxt = nxt.lstrip('#').strip()
                parts = nxt.split()
                if parts:
                    qq = parts[0]
                    name = " ".join(parts[1:]) if len(parts) > 1 else ""
                    result.update({"registered": True, "qq": qq, "name": name})
                    return result
            # if matched serial but no info lines, consider registered minimal
            result.update({"registered": True})
            return result
    return result
