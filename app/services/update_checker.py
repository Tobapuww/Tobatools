from PySide6.QtCore import QObject, Signal
import json
import ssl
import urllib.request
from urllib.parse import urlparse


class UpdateCheckerWorker(QObject):
    finished = Signal(dict, str)

    def __init__(self, url: str, current_version: str):
        super().__init__()
        self.url = url
        self.current_version = current_version

    def run(self):
        try:
            if not self.url:
                self.finished.emit({}, "未配置更新地址")
                return
            # Map GitHub/Gitee blob URL to raw content if needed
            url = self.url
            try:
                if "github.com" in url and "/blob/" in url:
                    # e.g. https://github.com/user/repo/blob/branch/path -> https://raw.githubusercontent.com/user/repo/branch/path
                    parts = url.split("github.com/")[-1]
                    user_repo, rest = parts.split("/blob/", 1)
                    url = f"https://raw.githubusercontent.com/{user_repo}/{rest}"
                elif "gitee.com" in url and "/blob/" in url:
                    # e.g. https://gitee.com/user/repo/blob/branch/path -> https://gitee.com/user/repo/raw/branch/path
                    parts = url.split("gitee.com/")[-1]
                    user_repo, rest = parts.split("/blob/", 1)
                    url = f"https://gitee.com/{user_repo}/raw/{rest}"
            except Exception:
                pass
            ctx = ssl.create_default_context()
            req = urllib.request.Request(url, headers={"User-Agent": "PythonFlash/1.0"})
            with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
                data = resp.read()
            text = data.decode("utf-8", errors="ignore").strip()
            # Try JSON first
            obj = None
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    obj = parsed
            except Exception:
                obj = None
            # Try INI-like key=value lines
            if obj is None:
                kv = {}
                try:
                    for line in text.splitlines():
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        if '=' in line:
                            k, v = line.split('=', 1)
                            kv[k.strip()] = v.strip()
                    if 'version' in kv:
                        obj = {
                            'version': kv.get('version', ''),
                            'url': kv.get('url', ''),
                            'notes': kv.get('notes', '')
                        }
                except Exception:
                    obj = None
            # Fallback: plain version string in the first non-empty line
            if obj is None:
                first = None
                for line in text.splitlines():
                    t = line.strip()
                    if t:
                        first = t
                        break
                if first:
                    obj = {'version': first}
            if not isinstance(obj, dict) or 'version' not in obj:
                self.finished.emit({}, "返回数据缺少版本信息")
                return
            self.finished.emit(obj, "")
        except Exception as e:
            self.finished.emit({}, str(e))
