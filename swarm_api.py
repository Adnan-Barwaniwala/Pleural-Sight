"""Local OpenSwarm API client. Credentials never enter results or logs."""
import json
import os
import pathlib
import sys
import urllib.request

BASE = os.environ.get('OPENSWARM_URL', 'http://127.0.0.1:8324')

def token_path():
    override = os.environ.get('OPENSWARM_TOKEN_PATH')
    if override:
        return pathlib.Path(override).expanduser()
    if sys.platform == 'darwin':
        return pathlib.Path.home() / 'Library/Application Support/openswarm/data/auth.token'
    if sys.platform == 'win32':
        return pathlib.Path(os.environ.get('APPDATA', pathlib.Path.home() / 'AppData/Roaming')) / 'openswarm/data/auth.token'
    return pathlib.Path.home() / '.config/openswarm/data/auth.token'

def call(path, data=None, method=None, timeout=30):
    token = token_path().read_text().strip()
    request = urllib.request.Request(BASE + path, data=None if data is None else json.dumps(data).encode(), headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)
