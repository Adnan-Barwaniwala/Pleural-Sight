"""Stream NIH ChestX-ray14 images_001.tar.gz and keep only the pilot-set films.

Reproducible: labels, views and follow-up order come from Data_Entry_2017_v2020.csv
(data/nih/). Only the listed PNGs are written; the archive is never stored.
"""
import hashlib
import json
import pathlib
import tarfile
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT/'data'/'images'
URL = 'https://nihcc.box.com/shared/static/vfk49d74nhbxq3nqjg0900w5nvkorp5c.gz'
WANTED = {
    # new
    '00000005_006.png', '00000005_007.png', '00000039_003.png', '00000039_004.png',
    '00000056_000.png', '00000056_001.png',
    # resolved
    '00000023_002.png', '00000023_003.png', '00000038_000.png', '00000038_001.png',
    '00000044_000.png', '00000044_001.png',
    # persistent
    '00000084_000.png', '00000084_001.png', '00000096_002.png', '00000096_003.png',
    '00000099_000.png', '00000099_001.png',
    # absent
    '00000003_001.png', '00000003_002.png', '00000008_000.png', '00000008_001.png',
    '00000022_000.png', '00000022_001.png',
    # AP vs PA (comparability gate)
    '00000005_000.png', '00000005_001.png', '00000013_017.png', '00000013_018.png',
    '00000011_004.png', '00000011_005.png',
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    provenance_path = ROOT/'data'/'provenance.json'
    provenance = json.loads(provenance_path.read_text())
    known = {p['image'] for p in provenance}
    missing = {n for n in WANTED if not (OUT/n).exists()}
    if not missing:
        print('All pilot images already present.')
        return
    with urllib.request.urlopen(URL, timeout=120) as response:
        with tarfile.open(fileobj=response, mode='r|gz') as archive:
            for item in archive:
                name = pathlib.PurePosixPath(item.name).name
                if name in missing and item.isfile():
                    data = archive.extractfile(item).read()
                    (OUT/name).write_bytes(data)
                    if name not in known:
                        provenance.append({'image': name, 'bytes': len(data),
                                           'sha256': hashlib.sha256(data).hexdigest(), 'source': URL})
                    missing.discard(name)
                    print(name, len(data), flush=True)
                if not missing:
                    break
    provenance_path.write_text(json.dumps(provenance, indent=2))
    if missing:
        raise RuntimeError('Missing requested images: ' + ', '.join(sorted(missing)))


if __name__ == '__main__':
    main()
