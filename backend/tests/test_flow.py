"""Deterministic test doubles are used only here, never in the application."""
import io
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
import httpx
from openai import OpenAI
from PIL import Image
import pytest

from backend.app import create_app
from backend.config import Settings
from backend.models import Proposal
from backend.services.errors import StageError
from backend.services.invoice_classifier import InvoiceClassifier, SYSTEM_PROMPT
from backend.storage import Store


def proposal(category='computers', confidence=.96, *, mismatch=False):
    return {'extracted_data': {'invoice_number': 'INV-1', 'supplier_name': 'المورد', 'invoice_date': '2024-06-02',
                              'subtotal': 100, 'vat': 15, 'total': 999 if mismatch else 115, 'currency': 'SAR'},
            'items': [{'description': 'Dell Laptop', 'quantity': 1, 'unit_price': 100, 'total': 100}],
            'classification': category, 'confidence': confidence, 'reason': 'المحتوى الأساسي أجهزة كمبيوتر.'}


class FakeOCR:
    model_name = 'TEST ONLY OCR'
    state = 'ready'
    def __init__(self): self.calls = []; self.fail_page = None
    def available(self): return True
    def close(self): pass
    def read(self, image, on_text=None):
        self.calls.append(image.name)
        if image.name == self.fail_page:
            if on_text: on_text('partial TEST ONLY')
            raise StageError('test_page_failure', 'test failure')
        text = f'# TEST ONLY {image.name}\nDell Laptop'
        if on_text: on_text(text)
        return {'text': text, 'seconds': .1, 'finish_reason': 'stop', 'usage': {}}


class FakeClassifier:
    def __init__(self): self.calls=[]; self.result=proposal(); self.error=None
    def classify_invoice(self,text):
        self.calls.append(text)
        if self.error: raise self.error
        return {'proposal': self.result, 'raw_response': {'test_double': True}, 'seconds': .1, 'model': 'TEST ONLY', 'usage': {}}


@pytest.fixture
def env(tmp_path):
    settings = Settings(data_dir=tmp_path, openrouter_key='')
    ocr, classifier = FakeOCR(), FakeClassifier()
    app = create_app(settings, ocr=ocr, classifier=classifier, start_worker=False)
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, app=app, ocr=ocr, classifier=classifier, settings=settings)


def image_bytes():
    output=io.BytesIO()
    Image.new('RGB',(100,150),'white').save(output,format='PNG')
    return output.getvalue()


def upload(env, content=None, name='invoice.png'):
    response=env.client.post('/api/invoices',files={'files':(name,content or image_bytes())})
    assert response.status_code==202
    assert not response.json()['errors']
    return response.json()['invoices'][0]['id']


def process(env):
    document=env.app.state.store.claim_next()
    assert document is not None
    env.app.state.worker.process(document)
    return env.client.get('/api/invoices/'+document['id']).json()


@pytest.mark.parametrize('items,category',[
    ('Dell Laptop; Lenovo Monitor','computers'), ('iPhone; Samsung Galaxy','mobile_devices'),
    ('HP Printer; Canon Scanner','printers_office'), ('Logitech Mouse; Mechanical Keyboard','tech_accessories'),
    ('Desktop PC 8000; HDMI Cable 50','computers'),
])
def test_classifier_structured_contract(items,category,tmp_path):
    # Fixtures verify transport, enum/schema and prompt, not real-model accuracy.
    calls=[]
    def respond(request):
        calls.append(request)
        return httpx.Response(200,json=completion(proposal(category)))
    with OpenAI(api_key='TEST ONLY',base_url='https://openrouter.ai/api/v1',
                http_client=httpx.Client(transport=httpx.MockTransport(respond))) as client:
        classifier=InvoiceClassifier(Settings(data_dir=tmp_path,openrouter_key=''),client)
        result=classifier.classify_invoice(items)
    payload=json.loads(calls[0].content)
    assert result['proposal']['classification']==category
    assert str(calls[0].url)=='https://openrouter.ai/api/v1/chat/completions'
    assert payload['model']=='qwen/qwen3.8-27b'
    assert payload['response_format']['json_schema']['schema']==Proposal.model_json_schema()
    assert payload['response_format']['json_schema']['strict'] is True
    assert payload['provider']['require_parameters'] is True
    assert items in payload['messages'][1]['content']
    assert 'input' not in payload and 'store' not in payload
    assert 'monetary contribution' in SYSTEM_PROMPT


def completion(data=None, *, finish_reason='stop', refusal=None, content=None):
    return {'id':'test-completion','object':'chat.completion','created':0,'model':'qwen/qwen3.8-27b',
            'choices':[{'index':0,'finish_reason':finish_reason,'message':{
                'role':'assistant','content':json.dumps(data) if data is not None else content,'refusal':refusal}}],
            'usage':{'prompt_tokens':10,'completion_tokens':20,'total_tokens':30}}


def test_full_review_retains_ai_and_persists(env):
    invoice_id=upload(env)
    doc=process(env)
    assert doc['status']=='classified'
    assert doc['pages'][0]['status']=='complete'
    assert 'file_path' not in doc and 'preview_path' not in doc['pages'][0]
    assert env.client.get(doc['pages'][0]['preview_url']).status_code==200
    assert env.client.get(doc['file_url']).status_code==200
    payload={'extracted_data':doc['ai_proposal']['extracted_data'],'items':doc['ai_proposal']['items'], 'final_classification':'tech_accessories','acknowledge_warnings':False}
    payload['extracted_data']['supplier_name']='المورد المصحح'
    result=env.client.post(f'/api/invoices/{invoice_id}/review',json=payload)
    assert result.status_code==200
    final=result.json()
    assert final['ai_proposal']['classification']=='computers'
    assert final['ai_proposal']['extracted_data']['supplier_name']=='المورد'
    assert final['final_classification']=='tech_accessories'
    assert final['extracted_data']['supplier_name']=='المورد المصحح'
    assert final['reviewed_by_user'] and final['reviewed_at']
    assert Store(env.settings.data_dir).get(invoice_id)['status']=='reviewed'
    assert env.client.post(f'/api/invoices/{invoice_id}/retry').status_code==409


def test_warning_acknowledgement_and_corrected_data(env):
    env.classifier.result=proposal(mismatch=True)
    invoice_id=upload(env); doc=process(env)
    assert doc['status']=='needs_review'
    payload={'extracted_data':doc['ai_proposal']['extracted_data'],'items':doc['ai_proposal']['items'], 'final_classification':'computers'}
    assert env.client.post(f'/api/invoices/{invoice_id}/review',json=payload).status_code==422
    payload['acknowledge_warnings']=True
    assert env.client.post(f'/api/invoices/{invoice_id}/review',json=payload).json()['warnings_acknowledged']
    payload['extracted_data']['total']=115; payload['acknowledge_warnings']=False
    final=env.client.post(f'/api/invoices/{invoice_id}/review',json=payload).json()
    assert final['warnings']==[]
    assert final['ai_proposal']['extracted_data']['total']==999


def test_outside_scope_and_low_confidence(env):
    env.classifier.result=proposal(None,None)
    invoice_id=upload(env);doc=process(env)
    assert doc['status']=='needs_review'
    result=env.client.post(f'/api/invoices/{invoice_id}/review',json={'extracted_data':doc['extracted_data'],'items':doc['ai_proposal']['items'],'final_classification':None})
    assert result.json()['status']=='reviewed'
    assert result.json()['final_classification'] is None
    env.classifier.result=proposal(confidence=.61)
    upload(env);assert process(env)['status']=='needs_review'


def test_missing_fields_never_become_zero(env):
    env.classifier.result['extracted_data']['vat']=None
    upload(env);doc=process(env)
    assert doc['extracted_data']['vat'] is None
    assert any(w['code']=='missing_vat' for w in doc['warnings'])


def test_analysis_retry_reuses_ocr(env):
    env.classifier.error=StageError('openrouter_not_configured','no key')
    invoice_id=upload(env);doc=process(env)
    assert doc['status']=='failed' and doc['stage']=='analysis'
    assert doc['ocr_text'] and doc['pages'][0]['text']
    assert env.client.post(f'/api/invoices/{invoice_id}/review',json={'extracted_data':proposal()['extracted_data'],'items':[],'final_classification':None}).status_code==409
    env.classifier.error=None
    assert env.client.post(f'/api/invoices/{invoice_id}/retry').status_code==202
    assert env.client.post(f'/api/invoices/{invoice_id}/retry').status_code==409
    assert process(env)['status']=='classified'
    assert len(env.ocr.calls)==1


def test_pdf_failure_retry_and_page_order(env):
    buffer=io.BytesIO(); images=[Image.new('RGB',(100,150),'white'),Image.new('RGB',(100,150),'gray')]
    images[0].save(buffer,format='PDF',save_all=True,append_images=images[1:])
    env.ocr.fail_page='page-2.png'
    invoice_id=upload(env,buffer.getvalue(),'two-pages.pdf');doc=process(env)
    assert doc['status']=='failed' and doc['stage']=='ocr'
    assert doc['pages'][0]['status']=='complete' and doc['pages'][1]['status']=='failed'
    assert not env.classifier.calls
    env.ocr.fail_page=None
    env.client.post(f'/api/invoices/{invoice_id}/retry');doc=process(env)
    assert doc['status']=='classified'
    assert env.ocr.calls.count('page-1.png')==1
    assert env.classifier.calls[0].index('PAGE 1')<env.classifier.calls[0].index('PAGE 2')


def test_corrupt_limits_and_recovery(env):
    response=env.client.post('/api/invoices',files={'files':('bad.pdf',b'broken')})
    assert response.json()['errors'] and not response.json()['invoices']
    response=env.client.post('/api/invoices',files=[('files',('i.png',image_bytes()))]*11)
    assert response.status_code==400
    env.settings.max_file_mb=0
    assert env.client.post('/api/invoices',files={'files':('i.png',image_bytes())}).json()['errors']
    env.settings.max_file_mb=20
    invoice_id=upload(env)
    env.app.state.store.claim_next();env.app.state.store.recover()
    doc=env.client.get(f'/api/invoices/{invoice_id}').json()
    assert doc['status']=='failed' and doc['error']['code']=='interrupted'
    assert env.client.get('/api/invoices/not-a-uuid').status_code==422


def test_invalid_category_and_nonfinite_money_rejected():
    with pytest.raises(ValueError): Proposal.model_validate(proposal('made_up'))
    invalid=proposal();invalid['extracted_data']['total']=float('nan')
    with pytest.raises(ValueError): Proposal.model_validate(invalid)


def test_missing_openrouter_key(tmp_path):
    with pytest.raises(StageError,match='OPENROUTER_API_KEY'):
        InvoiceClassifier(Settings(data_dir=tmp_path,openrouter_key='')).classify_invoice('text')


@pytest.mark.parametrize('body,code',[
    (completion(refusal='Cannot process'),'openrouter_refusal'),
    (completion(finish_reason='content_filter'),'openrouter_refusal'),
    (completion(proposal(),finish_reason='length'),'openrouter_incomplete'),
    (completion(),'openrouter_incomplete'),
    ({**completion(),'choices':[]},'openrouter_incomplete'),
    (completion(content='not JSON'),'openrouter_invalid_output'),
    (completion({'classification':'made_up'}),'openrouter_invalid_output'),
])
def test_openrouter_rejects_unusable_output(tmp_path,body,code):
    with OpenAI(api_key='TEST ONLY',base_url='https://openrouter.ai/api/v1',
                http_client=httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,json=body)))) as client:
        with pytest.raises(StageError) as caught:
            InvoiceClassifier(Settings(data_dir=tmp_path),client).classify_invoice('OCR')
        assert caught.value.code==code


@pytest.mark.parametrize('status,code',[
    (401,'openrouter_authentication'),(403,'openrouter_authentication'),
    (402,'openrouter_insufficient_credit'),(429,'openrouter_rate_limit'),
    (400,'openrouter_invalid_request'),(503,'openrouter_service_error'),
])
def test_openrouter_api_errors(tmp_path,status,code):
    with OpenAI(api_key='TEST ONLY',base_url='https://openrouter.ai/api/v1',max_retries=0,
                http_client=httpx.Client(transport=httpx.MockTransport(
                    lambda request:httpx.Response(status,json={'error':{'message':'test error','code':status}})))) as client:
        with pytest.raises(StageError) as caught:
            InvoiceClassifier(Settings(data_dir=tmp_path),client).classify_invoice('OCR')
        assert caught.value.code==code


def test_default_client_uses_openrouter(tmp_path,monkeypatch):
    from backend.services import invoice_classifier
    calls=[]
    def respond(request):
        calls.append(request)
        return httpx.Response(200,json=completion(proposal()))
    with httpx.Client(transport=httpx.MockTransport(respond)) as http_client:
        monkeypatch.setattr(invoice_classifier,'OpenAI',lambda **kwargs:OpenAI(**kwargs,http_client=http_client))
        settings=Settings(data_dir=tmp_path,openrouter_key='TEST OPENROUTER KEY',reasoning_effort='low')
        result=InvoiceClassifier(settings).classify_invoice('OCR')
    assert str(calls[0].url)=='https://openrouter.ai/api/v1/chat/completions'
    assert calls[0].headers['authorization']=='Bearer TEST OPENROUTER KEY'
    assert json.loads(calls[0].content)['reasoning']=={'effort':'low'}
    assert result['usage']['total_tokens']==30


def test_health_reports_openrouter_configuration(env):
    health=env.client.get('/api/health').json()
    assert health['openrouter']=={'configured':False,'model':'qwen/qwen3.8-27b'}
