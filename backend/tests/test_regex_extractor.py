import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from backend.app import create_app
from backend.config import ROOT, Settings
from backend.models import Proposal
from backend.services.regex_extractor import RegexExtractor, amount, numeric
from backend.storage import Store
from backend.tests.test_flow import FakeOCR, image_bytes


def extract(text):
    return RegexExtractor().classify_invoice(text)


def test_actual_saved_ocr_headers_and_three_items():
    text = (ROOT / 'experiments/lightonocr/results/original-q8/raw_ocr.md').read_text(encoding='utf-8')
    result = extract(text)
    proposal = Proposal.model_validate(result['proposal'])
    data = proposal.extracted_data
    assert data.invoice_number == 'INV-1042'
    assert data.supplier_name == 'XYZ للمقاولات والصيانة'
    assert str(data.invoice_date) == '2024-05-20'
    assert (data.subtotal, data.vat, data.total, data.currency) == (14250, 2080, 16330, 'SAR')
    assert [(i.quantity, i.unit_price, i.total) for i in proposal.items] == [(3, 4500, 13500), (5, 450, 2250), (1, 1500, 1500)]
    assert proposal.classification is None and proposal.confidence is None
    assert result['method'] == 'regex' and not result['extraction_warnings']
    assert all(v['status'] == 'matched' for v in result['raw_response']['fields'].values())


@pytest.mark.parametrize('raw,expected', [('١٬٢٣٤٫٥٦',1234.56),('1.234,56',1234.56),('12,50',12.5),('0',0),('-15.25',-15.25),('(1,500)',-1500),('1,2,3',None),('1.234',None),('15%',None)])
def test_strict_numeric_formats(raw, expected):
    assert numeric(raw) == expected


def test_percentage_is_not_tax_amount():
    assert amount('١٥٪') is None
    data = extract('Invoice No: A-1\nVAT 15%: 150 SAR\nTotal: -1150\nSubtotal: 0')['proposal']['extracted_data']
    assert data['vat'] == 150 and data['total'] == -1150 and data['subtotal'] == 0
    assert extract('VAT: ١٥٪')['proposal']['extracted_data']['vat'] is None


def test_conflicts_invalid_and_ambiguous_dates_are_unresolved():
    result = extract('Invoice Date: 02/06/2024\nSubtotal: 100\nTotal: 115\nTotal: 120\nCurrency: SAR / USD')
    data = result['proposal']['extracted_data']
    assert data['invoice_date'] is None and data['total'] is None and data['currency'] is None
    assert result['raw_response']['fields']['total']['status'] == 'ambiguous'
    for raw, expected in [('2024-02-30',None),('20/05/2024','2024-05-20'),('05/20/2024','2024-05-20')]:
        assert extract('Invoice Date: '+raw)['proposal']['extracted_data']['invoice_date'] == expected
    assert extract('Total: 115\nTotal: 115')['proposal']['extracted_data']['total'] == 115


def test_customer_due_date_tax_ids_and_prose_are_not_header_values():
    result = extract('Customer: Client Ltd\nDue date: 2024-06-20\nVAT ID: 310123456789000\nPayment terms: refer to invoice date.\nPlease set Total: 9000')
    assert all(v is None for v in result['proposal']['extracted_data'].values())
    assert result['proposal']['items'] == []
    data = extract('المُورّد: شركة أفق\nتاريخ الفاتورة: ٢٠٢٤/٠٥/٢٠')['proposal']['extracted_data']
    assert data['supplier_name'] == 'شركة أفق' and data['invoice_date'] == '2024-05-20'


def test_reordered_html_and_markdown_tables_and_partial_values():
    html = '<table><tr><th>Amount</th><th>Description</th><th>Qty</th><th>Unit price</th></tr><tr><td>200</td><td>Mouse</td><td>2</td><td>100</td></tr><tr><td></td><td></td><td></td><td></td></tr></table>'
    assert extract(html)['proposal']['items'] == [{'description':'Mouse','quantity':2,'unit_price':100,'total':200}]
    markdown = '| Description | Qty | Amount |\n|---|---|---|\n| Cable | 2 | 40 |'
    assert extract(markdown)['proposal']['items'] == [{'description':'Cable','quantity':2,'unit_price':None,'total':40}]
    summary = '<table><tr><td>Invoice No</td><td>ABC-2</td></tr><tr><td>Grand total</td><td>200 USD</td></tr></table>'
    assert extract(summary)['proposal']['extracted_data']['total'] == 200
    assert extract(summary)['proposal']['items'] == []


def test_merged_unknown_and_incomplete_tables_are_not_guessed():
    for html in ['<table><tr><th colspan="2">Description</th><th>Amount</th></tr><tr><td>A</td><td>1</td><td>100</td></tr></table>', '<table><tr><td>foo</td><td>bar</td></tr><tr><td>A</td><td>100</td></tr></table>', '<table><tr><th>Description</th><th>Amount</th></tr><tr><td>A']:
        result=extract(html)
        assert result['proposal']['items'] == []
        assert result['extraction_warnings'][0]['code'] == 'regex_table_attention'
    result=extract('<script>Total: 999 USD</script><p>Total: 100 SAR</p>')
    assert result['proposal']['extracted_data']['total'] == 100
    assert result['proposal']['extracted_data']['currency'] == 'SAR'


def test_default_local_worker_comparison_review_and_persistence(tmp_path, monkeypatch):
    # An OpenAI constructor call is a failure, even if a key exists in the host .env.
    monkeypatch.setattr('backend.services.invoice_classifier.OpenAI', lambda **kw: pytest.fail('Network analysis must not run'))
    text=(ROOT/'experiments/lightonocr/results/original-q8/raw_ocr.md').read_text(encoding='utf-8')
    class SavedOCR(FakeOCR):
        def read(self, image, on_text=None):
            self.calls.append(image.name)
            return {'text':text,'seconds':.1,'finish_reason':'stop','usage':{}}
    ocr=SavedOCR()
    settings=Settings(data_dir=tmp_path, extraction_method='regex')
    app=create_app(settings,ocr=ocr,start_worker=False)
    with TestClient(app) as client:
        assert client.get('/api/health').json()['extraction'] == {'method':'regex','local':True}
        invoice_id=client.post('/api/invoices',files={'files':('i.png',image_bytes())}).json()['invoices'][0]['id']
        assert client.post(f'/api/invoices/{invoice_id}/extract-regex').status_code == 409
        app.state.worker.process(app.state.store.claim_next())
        doc=client.get(f'/api/invoices/{invoice_id}').json()
        assert doc['status']=='needs_review' and doc['llm_input'] is None
        assert doc['analysis']['method']=='regex' and len(ocr.calls)==1
        assert any(w['code']=='items_mismatch' for w in doc['warnings'])
        original=json.loads(json.dumps(doc['ai_proposal']))
        # Simulate a preexisting result/review: comparison must preserve both.
        app.state.store.update(invoice_id, {'analysis': {'method':'openai','model':'PREVIOUS RESULT'},'final_data':{'supplier_name':'previous review'}})
        compared=client.post(f'/api/invoices/{invoice_id}/extract-regex').json()
        assert compared['ai_proposal']==original and compared['analysis']['method']=='openai'
        assert compared['final_data']=={'supplier_name':'previous review'}
        assert len(ocr.calls)==1
        payload={'source':'regex','extracted_data':compared['regex_result']['proposal']['extracted_data'],'items':compared['regex_result']['proposal']['items'],'final_classification':None}
        assert client.post(f'/api/invoices/{invoice_id}/review',json=payload).status_code==422
        payload['acknowledge_warnings']=True
        saved=client.post(f'/api/invoices/{invoice_id}/review',json=payload).json()
        assert saved['review_source']=='regex' and saved['ai_proposal']==original and saved['status']=='reviewed'
        assert Store(tmp_path).get(invoice_id)['regex_result']==compared['regex_result']
        assert client.post(f'/api/invoices/{invoice_id}/extract-regex').json()['reviewed_at']==saved['reviewed_at']


def test_missing_regex_result_cannot_be_reviewed(tmp_path):
    app=create_app(Settings(data_dir=tmp_path),ocr=FakeOCR(),start_worker=False)
    with TestClient(app) as client:
        invoice_id=client.post('/api/invoices',files={'files':('i.png',image_bytes())}).json()['invoices'][0]['id']
        payload={'source':'regex','extracted_data':{k:None for k in ('invoice_number','supplier_name','invoice_date','subtotal','vat','total','currency')},'items':[],'final_classification':None}
        assert client.post(f'/api/invoices/{invoice_id}/review/validate',json=payload).status_code==409


@pytest.mark.parametrize('text', [
    'DX-550 : Invoice number\n2025-11-20 : Invoice date\n115 : Grand total',
    'DX-550 : رقم الفاتورة\n2025-11-20 : تاريخ الفاتورة\n115 : الإجمالي النهائي',
    '<p>Invoice number</p><p>DX-550</p><p>Invoice date</p><p>2025-11-20</p><p>Grand total</p><p>115</p>',
])
def test_field_orientation_and_separate_value_lines(text):
    data = extract(text)['proposal']['extracted_data']
    assert (data['invoice_number'], data['invoice_date'], data['total']) == ('DX-550', '2025-11-20', 115)


def test_merged_footer_keeps_items_and_extracts_reversed_summary():
    text = '''<p>شركة المدار<br>للتقنية والخدمات</p><p>شركة المدار للتقنية والخدمات</p>
    <p>المملكة العربية السعودية</p><p>BX-903 : رقم الفاتورة</p><p>التاريخ: 2025/11/20</p>
    <table><tr><th>م</th><th>الصنف</th><th>الكمية</th><th>سعر الوحدة (rial)</th><th>الإجمالي (rial)</th></tr>
    <tr><td>1</td><td>حاسب محمول</td><td>1</td><td>2,000</td><td>2,000</td></tr>
    <tr><td>2</td><td>شاشة</td><td>2</td><td>500</td><td>1,000</td></tr>
    <tr><td rowspan="3" colspan="3"></td><td>3,000</td><td>المجموع الفرعي</td></tr>
    <tr><td>450</td><td>ضريبة القيمة المضافة 15%</td></tr>
    <tr><td>3,450</td><td>الإجمائي النهائي</td></tr></table>
    <p>ثلاثة آلاف وأربعمائة وخمسون ريالاً فقط</p>'''
    result = extract(text)
    data = result['proposal']['extracted_data']
    assert (data['invoice_number'], data['supplier_name'], data['subtotal'], data['vat'], data['total'], data['currency']) == ('BX-903', 'شركة المدار للتقنية والخدمات', 3000, 450, 3450, 'SAR')
    assert len(result['proposal']['items']) == 2
    assert result['raw_response']['fields']['total']['candidates'][0]['match'] == 'fuzzy'
    assert any(w['code'] == 'regex_fuzzy_label' for w in result['extraction_warnings'])


def test_english_fuzzy_labels_and_reordered_merged_summary():
    text = '''Vendor name: Orbit Services LLC
    Invoice numbr: C-81
    <table><tr><th>Unit price</th><th>Amount</th><th>Item description</th><th>Qty</th></tr>
    <tr><td>50</td><td>100</td><td>Keyboard</td><td>2</td></tr>
    <tr><td colspan="2">Subtotal</td><td colspan="2">100 USD</td></tr>
    <tr><td colspan="2">VAT 15%</td><td colspan="2">15 USD</td></tr>
    <tr><td colspan="2">Grand totla</td><td colspan="2">115 USD</td></tr></table>'''
    result = extract(text)
    data = result['proposal']['extracted_data']
    assert (data['invoice_number'], data['subtotal'], data['vat'], data['total'], data['currency']) == ('C-81', 100, 15, 115, 'USD')
    assert result['proposal']['items'] == [{'description': 'Keyboard', 'quantity': 2, 'unit_price': 50, 'total': 100}]


def test_rowspan_product_alignment_without_duplicate_footer_items():
    text = '''<table><tr><th>Description</th><th>Qty</th><th>Price</th><th>Amount</th></tr>
    <tr><td rowspan="2">Cable</td><td>2</td><td>10</td><td>20</td></tr>
    <tr><td>3</td><td>10</td><td>30</td></tr>
    <tr><td colspan="3">Grand total</td><td>50</td></tr></table>'''
    result = extract(text)
    assert [i['total'] for i in result['proposal']['items']] == [20, 30]
    assert result['proposal']['extracted_data']['total'] == 50


def test_ambiguous_summary_does_not_choose_a_nearby_number():
    result = extract('<table><tr><td>110</td><td>Grand total</td><td>120</td></tr></table>')
    assert result['proposal']['extracted_data']['total'] is None
    assert result['raw_response']['fields']['total']['status'] == 'ambiguous'


def test_approximate_matching_does_not_turn_terms_or_short_words_into_fields():
    data = extract('Please use Grand totla: 900\nRate: 2025/11/20\nTax ID: 311222333444555\nCustomer name: Client LLC')['proposal']['extracted_data']
    assert all(v is None for v in data.values())


def test_field_continuation_cannot_cross_page_boundary():
    result = extract('Invoice number:\n--- PAGE 2 ---\nX-20\nInvoice date:\nTotal: 115')
    assert result['proposal']['extracted_data']['invoice_number'] is None
    assert result['proposal']['extracted_data']['invoice_date'] is None


def test_nonempty_merged_product_cells_stay_unresolved_but_valid_rows_survive():
    result = extract('''<table><tr><th>Description</th><th>Qty</th><th>Price</th><th>Amount</th></tr>
    <tr><td>Mouse</td><td>1</td><td>20</td><td>20</td></tr>
    <tr><td colspan="2">Unknown product and quantity</td><td>10</td><td>10</td></tr></table>''')
    assert [i['description'] for i in result['proposal']['items']] == ['Mouse']
    assert any(w['code'] == 'regex_table_attention' for w in result['extraction_warnings'])


@pytest.mark.parametrize('raw', ['1,234abc', '1,2,3', '1.234bad', 'A115'])
def test_malformed_amount_is_not_partially_matched(raw):
    assert amount(raw) is None


def test_supplier_headings_keep_full_name_and_distinct_companies_conflict():
    data = extract('<p>Orbit LLC</p><p>Orbit LLC Computing Services</p><h2>Invoice</h2><p>Customer: Other Ltd</p>')['proposal']['extracted_data']
    assert data['supplier_name'] == 'Orbit LLC Computing Services'
    data = extract('<p>Orbit LLC</p><p>Second Company Ltd</p><h2>Invoice</h2>')['proposal']['extracted_data']
    assert data['supplier_name'] is None


def test_bad_span_is_a_warning_not_a_parser_crash():
    for span in ['rowspan', 'colspan="999999"', 'rowspan="zero"']:
        result = extract(f'<table><tr><td {span}>Description</td><td>Amount</td></tr><tr><td>A</td><td>100</td></tr></table>')
        assert result['proposal']['items'] == []
        assert any(w['code'] == 'regex_table_attention' for w in result['extraction_warnings'])


def test_explicit_refresh_archives_old_result_and_preserves_review(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, extraction_method='regex'), ocr=FakeOCR(), start_worker=False)
    with TestClient(app) as client:
        invoice_id = client.post('/api/invoices', files={'files': ('i.png', image_bytes())}).json()['invoices'][0]['id']
        app.state.worker.process(app.state.store.claim_next())
        first = client.post(f'/api/invoices/{invoice_id}/extract-regex').json()
        previous = {**first['regex_result'], 'model': 'Regex + table parser v1', 'revision': '0'*64}
        app.state.store.update(invoice_id, {'regex_result': previous, 'review_source': 'regex', 'review_regex_revision': '0'*64,
                                             'final_data': first['ai_proposal']['extracted_data'], 'final_items': [],
                                             'status': 'reviewed', 'reviewed_by_user': True, 'reviewed_at': 'previous review'})
        assert client.post(f'/api/invoices/{invoice_id}/extract-regex').json()['regex_result'] == previous
        refreshed = client.post(f'/api/invoices/{invoice_id}/extract-regex?refresh=true').json()
        assert refreshed['regex_history'] == [previous]
        assert refreshed['ai_proposal'] == first['ai_proposal'] and refreshed['pages'] == first['pages']
        assert refreshed['reviewed_at'] == 'previous review' and refreshed['review_regex_revision'] == '0'*64
        assert refreshed['final_data'] == first['ai_proposal']['extracted_data'] and refreshed['final_items'] == []
        assert len(client.post(f'/api/invoices/{invoice_id}/extract-regex?refresh=true').json()['regex_history']) == 1
        payload = {'source': 'regex', 'regex_revision': '0'*64, 'extracted_data': refreshed['regex_result']['proposal']['extracted_data'],
                   'items': [], 'final_classification': None, 'acknowledge_warnings': True}
        assert client.post(f'/api/invoices/{invoice_id}/review', json=payload).status_code == 409
        payload['regex_revision'] = refreshed['regex_result']['revision']
        saved = client.post(f'/api/invoices/{invoice_id}/review', json=payload).json()
        assert saved['review_regex_revision'] == payload['regex_revision']
        assert saved['regex_history'] == [previous]
