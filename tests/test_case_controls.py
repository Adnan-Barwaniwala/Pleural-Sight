import asyncio
import json
import pytest
import server
from test_intake import client, POST, png


def upload(client):
    return client.post('/api/cases', headers=POST, data={'same_patient':'true','chronological':'true'},
                       files={'prior':('a.png',png()),'current':('b.png',png((4,4,4)))}).json()


def test_revision_reports_swap_and_restore(client):
    original=upload(client); cid=original['id']
    assert client.post(f'/api/cases/{cid}/reports',headers=POST,data={'revision':1,'current_report':'No effusion.'}).status_code==200
    item=server.case(cid)
    assert item['revision']==2 and item['reports'][0]['scope']=='current'
    assert client.post(f'/api/cases/{cid}/swap',headers=POST,json={'revision':1,'confirmed':True}).status_code==409
    assert client.post(f'/api/cases/{cid}/swap',headers=POST,json={'revision':2,'confirmed':True,'move_reports':True}).status_code==200
    swapped=server.case(cid)
    assert swapped['prior']['sha256']==original['current']['sha256']
    assert swapped['reports'][0]['scope']=='prior' and swapped['revision']==3
    assert client.post(f'/api/cases/{cid}/swap',headers=POST,json={'revision':3,'confirmed':True,'move_reports':False}).status_code==200
    assert server.case(cid)['reports'][0]['scope']=='prior'
    assert client.delete(f'/api/cases/{cid}',headers=POST).status_code==200
    assert cid not in [c['id'] for c in server.cases()]
    assert client.post(f'/api/cases/{cid}/restore',headers=POST).status_code==200
    assert server.case(cid)['revision']==4


def test_empty_library_and_demo_restore(client):
    for item in server.cases():
        assert client.delete('/api/cases/'+item['id'],headers=POST).status_code==200
    assert client.get('/api/state').json()['cases']==[]
    assert client.post('/api/cases/case-1/restore',headers=POST).status_code==200
    assert [c['id'] for c in server.cases()]==['case-1']


def test_interruption_blocks_mutation_and_late_completion(client):
    item=upload(client); cid=item['id']; rid='control-run'
    with server.connect() as c:
        c.execute('INSERT INTO runs(id,case_id,status,created,updated) VALUES (?,?,?,?,?)',(rid,cid,'running',1,1))
    assert client.delete('/api/cases/'+cid,headers=POST).status_code==409
    assert client.post('/api/cases/'+cid+'/reports',headers=POST,data={'revision':1,'current_report':'No effusion.'}).status_code==409
    assert client.post('/api/runs/'+rid+'/interrupt',headers=POST).json()['status']=='interrupted'
    server.update_run(rid,status='complete',result={'bad':'late'})
    assert server.run_record(rid)['status']=='interrupted'
    assert server.run_record(rid)['result'] is None
    assert (server.RUNTIME/'runs'/rid/'cancelled').exists()


def test_report_validation(client):
    cid=upload(client)['id']
    assert client.post('/api/cases/'+cid+'/reports',headers=POST,data={'revision':1}).status_code==422
    assert client.post('/api/cases/'+cid+'/reports',headers=POST,data={'revision':1},files={'current_report_file':('a.pdf',b'not pdf')}).status_code==422


def test_reports_are_one_per_study_and_text_xor_file(client):
    base={'same_patient':'true','chronological':'true','prior_report':'No effusion.'}
    both=client.post('/api/cases',headers=POST,data=base,files={
        'prior':('a.png',png()),'current':('b.png',png((2,2,2))),
        'prior_report_file':('prior.txt',b'Pleural effusion is present.')})
    assert both.status_code==422 and 'not both' in both.json()['detail']

    item=upload(client);cid=item['id']
    added=client.post(f'/api/cases/{cid}/reports',headers=POST,data={
        'revision':1,'prior_report':'No effusion.','current_report':'Effusion is present.'})
    assert added.status_code==200 and len(server.case(cid)['reports'])==2
    duplicate=client.post(f'/api/cases/{cid}/reports',headers=POST,data={
        'revision':2,'current_report':'A second current report.'})
    assert duplicate.status_code==422 and 'already has a report' in duplicate.json()['detail']


def test_replace_report_and_image_preserves_old_input(client):
    item=upload(client);cid=item['id']
    add=client.post(f'/api/cases/{cid}/reports',headers=POST,data={'revision':1,'prior_report':'No effusion.'})
    assert add.status_code==200
    edited=client.put(f'/api/cases/{cid}/reports/prior',headers=POST,data={'revision':2,'prior_report':'Effusion is present.'})
    assert edited.status_code==200 and server.case(cid)['reports'][0]['text']=='Effusion is present.'
    old_name=server.case(cid)['prior']['image']
    image=client.post(f'/api/cases/{cid}/images/prior',headers=POST,data={'revision':3,'confirmed':'true','view':'PA'},
                      files={'image':('replacement.png',png((33,33,33)))})
    assert image.status_code==200
    changed=server.case(cid)
    assert changed['prior']['image'] != old_name and (server.image_folder(cid)/old_name).is_file()


def test_old_run_uses_snapshot_after_reports_added(client):
    item=upload(client); cid=item['id']
    with server.connect() as c:
        c.execute('INSERT INTO runs(id,case_id,status,created,updated) VALUES (?,?,?,?,?)',('old',cid,'complete',1,1))
        c.execute('INSERT INTO run_inputs VALUES (?,?)',('old',json.dumps(item)))
    client.post('/api/cases/'+cid+'/reports',headers=POST,data={'revision':1,'current_report':'No effusion.'})
    current=server.case(cid)
    assert current['last_run'] is None and current['history'][0]['revision']==1
    assert client.get('/api/runs/old').status_code==200


def test_cancelled_worker_denies_calls(tmp_path):
    from analysis_mcp import Worker
    from gemini_direct import ModelError
    path=tmp_path/'manifest.json';path.write_text('{}')
    worker=Worker(path);(tmp_path/'cancelled').touch()
    with pytest.raises(ModelError,match='stopped'):
        asyncio.run(worker.call('read_pair',{}))
