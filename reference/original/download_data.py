"""Stream official NIH archive; retain only prespecified demonstration images."""
import urllib.request, tarfile, pathlib, hashlib, json
ROOT=pathlib.Path(__file__).parent
OUT=ROOT/'data'/'images'; OUT.mkdir(parents=True,exist_ok=True)
URL='https://nihcc.box.com/shared/static/vfk49d74nhbxq3nqjg0900w5nvkorp5c.gz'
WANTED={'00000001_000.png','00000001_001.png','00000001_002.png','00000011_000.png','00000011_001.png','00000061_002.png','00000061_003.png'}
found=[]
with urllib.request.urlopen(URL, timeout=120) as response:
 with tarfile.open(fileobj=response,mode='r|gz') as archive:
  for item in archive:
   name=pathlib.PurePosixPath(item.name).name
   if name in WANTED and item.isfile():
    data=archive.extractfile(item).read()
    (OUT/name).write_bytes(data)
    found.append({'image':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'source':URL})
    print(name,len(data),flush=True)
   if len(found)==len(WANTED): break
(ROOT/'data'/'provenance.json').write_text(json.dumps(found,indent=2))
if len(found)!=len(WANTED): raise RuntimeError('Missing requested images')
