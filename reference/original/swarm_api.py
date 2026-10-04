import json, pathlib, urllib.request
BASE='http://127.0.0.1:8324'
def call(path, data=None, method=None):
 token=(pathlib.Path.home()/'AppData/Roaming/openswarm/data/auth.token').read_text().strip()
 req=urllib.request.Request(BASE+path,data=None if data is None else json.dumps(data).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},method=method)
 with urllib.request.urlopen(req,timeout=120) as r: return json.load(r)
