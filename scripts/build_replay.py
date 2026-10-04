"""Run cases live and cache the results as replays (shown with a Replay tag in the UI).

    python scripts/build_replay.py --engine openswarm case-A case-C
    python scripts/build_replay.py --engine headless --all-demo
"""
import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import server  # noqa: E402


async def run_case(case_id, engine):
    selected = server.case(case_id)
    rid = uuid.uuid4().hex
    folder = (server.RUNTIME/'runs'/rid).resolve()
    folder.mkdir(parents=True)
    manifest = {'run_id': rid, 'case_id': case_id, 'case_name': selected['name'],
                'prior': str(server.image_path(selected, 'prior').resolve()),
                'current': str(server.image_path(selected, 'current').resolve()),
                'reports': selected['reports'], 'gate': selected['gate']}
    (folder/'manifest.json').write_text(json.dumps(manifest))
    started = time.time()
    result = await server.ENGINES[engine](folder/'manifest.json', progress=lambda s: print(f'  {case_id}: {s}', flush=True))
    record = {'id': rid, 'case_id': case_id, 'status': 'complete', 'stage': 'human_review', 'result': result,
              'trace': result['agents'], 'error': None, 'created': started, 'updated': time.time(), 'engine': engine}
    server.REPLAY.mkdir(parents=True, exist_ok=True)
    (server.REPLAY/f'{case_id}.json').write_text(json.dumps(record, indent=1))
    print(f'{case_id}: {result["verdict"]["status"]} - {result["verdict"]["summary"]}', flush=True)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('cases', nargs='*')
    parser.add_argument('--engine', choices=sorted(server.ENGINES), default='openswarm')
    parser.add_argument('--all-demo', action='store_true')
    args = parser.parse_args()
    ids = args.cases or ([c['id'] for c in server.cases() if c.get('set') == 'demo'] if args.all_demo else [])
    for case_id in ids:
        try:
            await run_case(case_id, args.engine)
        except Exception as exc:
            print(f'{case_id}: FAILED {exc}', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
