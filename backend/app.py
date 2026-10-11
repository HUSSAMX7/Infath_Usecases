import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .config import Settings
from .models import LABELS, ReviewRequest
from .services.documents import DocumentError, prepare_pages
from .services.invoice_classifier import InvoiceClassifier
from .services.lightonocr import LightOnOCR
from .services.regex_extractor import RegexExtractor
from .storage import Store, now
from .validation import validate_invoice
from .worker import InvoiceWorker

EXTENSIONS = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.pdf': 'application/pdf'}


def create_app(settings: Settings | None = None, *, ocr=None, classifier=None, start_worker=True) -> FastAPI:
    settings = settings or Settings()
    store = Store(settings.data_dir)
    ocr = ocr or LightOnOCR(settings)
    classifier = classifier or (RegexExtractor() if settings.extraction_method == 'regex' else InvoiceClassifier(settings))
    worker = InvoiceWorker(store, ocr, classifier, settings.confidence_threshold)

    @asynccontextmanager
    async def lifespan(app):
        if start_worker:
            worker.start()
        yield
        if start_worker:
            worker.close()

    app = FastAPI(title='Invoice Studio', lifespan=lifespan)
    app.state.store, app.state.worker = store, worker

    def find(invoice_id: UUID) -> dict:
        document = store.get(str(invoice_id))
        if document is None:
            raise HTTPException(404, 'الوثيقة غير موجودة.')
        return document

    def public(document: dict, summary=False):
        # Return an independent object, and never expose local filesystem paths.
        result = json.loads(json.dumps(document))
        result.pop('file_path', None)
        result['invoice_id'] = result['id']
        result['file_url'] = f'/api/invoices/{result["id"]}/file'
        proposal = result['ai_proposal']
        result['extracted_data'] = result['final_data'] if result['reviewed_by_user'] else (proposal['extracted_data'] if proposal else None)
        key = proposal['classification'] if proposal else None
        result['classification'] = {'key': key, 'label': LABELS.get(key) if key else None, 'confidence': proposal['confidence'] if proposal else None}
        if summary:
            for name in ('pages', 'ocr_text', 'llm_input', 'analysis_input', 'analysis', 'regex_result', 'regex_history', 'failure_details', 'ai_proposal', 'final_data', 'final_items'):
                result.pop(name, None)
        else:
            for page in result['pages']:
                page.pop('preview_path', None)
                page['preview_url'] = f'/api/invoices/{result["id"]}/pages/{page["number"]}'
        return result

    @app.get('/api/health')
    def health():
        return {'status': 'ok', 'ocr': {'available': ocr.available(), 'state': ocr.state, 'model': ocr.model_name},
                'openai': {'configured': bool(settings.openai_key), 'model': settings.openai_model},
                'extraction': {'method': settings.extraction_method, 'local': settings.extraction_method == 'regex'},
                'limits': {'max_files': settings.max_files, 'max_file_mb': settings.max_file_mb, 'max_pages': settings.max_pages},
                'categories': [{'key': key.value, 'label': label} for key, label in LABELS.items()],
                'confidence_threshold': settings.confidence_threshold}

    @app.post('/api/invoices', status_code=202)
    async def upload(files: list[UploadFile] = File(...)):
        if not 1 <= len(files) <= settings.max_files:
            raise HTTPException(400, f'ارفع من 1 إلى {settings.max_files} ملفات في الدفعة.')
        invoices, errors = [], []
        for upload_file in files:
            name = Path((upload_file.filename or 'document').replace('\\', '/')).name
            suffix = Path(name).suffix.lower()
            folder = None
            try:
                if suffix not in EXTENSIONS:
                    raise DocumentError('الصيغ المدعومة: PDF وPNG وJPEG وWEBP.')
                invoice_id = str(uuid4())
                folder = settings.data_dir / 'documents' / invoice_id
                folder.mkdir(parents=True)
                original = folder / ('original' + suffix)
                size = 0
                with original.open('wb') as stream:
                    while chunk := await upload_file.read(1024 * 1024):
                        size += len(chunk)
                        if size > settings.max_file_mb * 1024 * 1024:
                            raise DocumentError(f'حجم الملف يتجاوز {settings.max_file_mb}MB.')
                        stream.write(chunk)
                if not size:
                    raise DocumentError('الملف فارغ.')
                pages = await asyncio.to_thread(prepare_pages, original, folder, settings.max_pages)
                document = {'id': invoice_id, 'filename': name, 'file_path': str(original), 'media_type': EXTENSIONS[suffix],
                            'size_bytes': size, 'page_count': len(pages), 'pages': pages,
                            'status': 'queued', 'stage': 'ocr', 'current_page': None,
                            'created_at': now(), 'updated_at': now(), 'reviewed_at': None,
                            'ai_proposal': None, 'analysis': None, 'ocr_text': '', 'llm_input': None,
                            'regex_result': None, 'review_source': None,
                            'final_data': None, 'final_items': None, 'final_classification': None,
                            'reviewed_by_user': False, 'warnings_acknowledged': False,
                            'warnings': [], 'error': None, 'failure_details': None, 'attempt_seconds': None,
                            'ocr_model': ocr.model_name, 'retry_count': 0}
                store.add(document)
                invoices.append(public(document, summary=True))
            except DocumentError as error:
                errors.append({'filename': name, 'message': str(error)})
                if folder:
                    # This request owns this newly generated UUID directory, containing only files.
                    if not folder.resolve().is_relative_to((settings.data_dir / 'documents').resolve()):
                        raise RuntimeError('Unexpected upload directory')
                    for path in folder.iterdir():
                        if path.is_file():
                            path.unlink()
                    folder.rmdir()
            finally:
                await upload_file.close()
        return {'invoices': invoices, 'errors': errors}

    @app.get('/api/invoices')
    def list_invoices():
        return {'invoices': [public(doc, summary=True) for doc in store.list()]}

    @app.get('/api/invoices/{invoice_id}')
    def get_invoice(invoice_id: UUID):
        return public(find(invoice_id))

    @app.get('/api/invoices/{invoice_id}/file')
    def original_file(invoice_id: UUID):
        document = find(invoice_id)
        path = Path(document['file_path'])
        if not path.is_file():
            raise HTTPException(404, 'الملف الأصلي غير موجود على القرص.')
        return FileResponse(path, media_type=document['media_type'], filename=document['filename'], content_disposition_type='inline')

    @app.get('/api/invoices/{invoice_id}/pages/{number}')
    def preview(invoice_id: UUID, number: int):
        document = find(invoice_id)
        if not 1 <= number <= len(document['pages']):
            raise HTTPException(404, 'الصفحة غير موجودة.')
        return FileResponse(document['pages'][number - 1]['preview_path'], media_type='image/png')

    def review_result(document, source):
        if source == 'regex':
            result = document.get('regex_result')
            if not result:
                raise HTTPException(409, 'استخرج نتيجة Regex أولًا.')
            return result
        if not document.get('ai_proposal'):
            raise HTTPException(409, 'أكمل الاستخراج أولًا قبل اعتماد المراجعة.')
        return document.get('analysis') or {}

    def review_warnings(document, request):
        result = review_result(document, request.source)
        if request.source == 'regex' and request.regex_revision and request.regex_revision != result.get('revision'):
            raise HTTPException(409, 'تغيّرت نتيجة الاستخراج؛ حدّث الوثيقة وراجع النتيجة الجديدة قبل الاعتماد.')
        return [w.model_dump() for w in validate_invoice(request.extracted_data, request.items)] + result.get('extraction_warnings', [])

    @app.post('/api/invoices/{invoice_id}/extract-regex')
    def extract_regex(invoice_id: UUID, refresh: bool = False):
        document = find(invoice_id)
        if document['status'] in ('queued', 'processing') or not document['pages'] or any(p['status'] != 'complete' for p in document['pages']):
            raise HTTPException(409, 'أكمل قراءة كل الصفحات قبل استخراج الحقول بالقواعد.')
        # Reuse exactly the saved OCR, preserving the original AI result/review.
        result = document.get('regex_result')
        if result is None or refresh:
            text = '\n\n'.join(f'--- PAGE {p["number"]} ---\n{p["text"]}' for p in document['pages'])
            refreshed = RegexExtractor().classify_invoice(text)
            history = list(document.get('regex_history', []))
            if result and result.get('revision') != refreshed['revision']:
                history.append(result)
            document = store.update(str(invoice_id), {'regex_result': refreshed, 'regex_history': history}, ('classified', 'needs_review', 'reviewed', 'failed'))
            if document is None:
                raise HTTPException(409, 'تغيّرت حالة الوثيقة؛ حدّث الصفحة.')
        return public(document)

    @app.post('/api/invoices/{invoice_id}/review/validate')
    def review_validation(invoice_id: UUID, request: ReviewRequest):
        return {'warnings': review_warnings(find(invoice_id), request)}

    @app.post('/api/invoices/{invoice_id}/review')
    def review(invoice_id: UUID, request: ReviewRequest):
        document = find(invoice_id)
        allowed = ('classified', 'needs_review', 'reviewed', 'failed') if request.source == 'regex' else ('classified', 'needs_review', 'reviewed')
        if document['status'] not in allowed:
            raise HTTPException(409, 'أكمل التحليل أولًا قبل اعتماد المراجعة.')
        warnings = review_warnings(document, request)
        if warnings and not request.acknowledge_warnings:
            raise HTTPException(422, {'message': 'أقرّ بالتنبيهات قبل الاعتماد.', 'warnings': warnings})
        updated = store.update(str(invoice_id), {'status': 'reviewed', 'stage': None, 'error': None,
                               'final_data': request.extracted_data.model_dump(mode='json'),
                               'final_items': [item.model_dump(mode='json') for item in request.items],
                               'final_classification': request.final_classification.value if request.final_classification else None,
                               'reviewed_by_user': True, 'reviewed_at': now(), 'warnings': warnings,
                               'review_regex_revision': review_result(document, 'regex').get('revision') if request.source == 'regex' else None,
                               'review_source': request.source, 'warnings_acknowledged': request.acknowledge_warnings}, allowed)
        if updated is None:
            raise HTTPException(409, 'تغيّرت حالة الوثيقة؛ حدّث الصفحة.')
        return public(updated)

    @app.post('/api/invoices/{invoice_id}/retry', status_code=202)
    def retry(invoice_id: UUID):
        document = find(invoice_id)
        updated = store.update(str(invoice_id), {'status': 'queued', 'error': None, 'failure_details': None,
                                                 'retry_count': document['retry_count'] + 1}, ('failed',))
        if updated is None:
            raise HTTPException(409, 'إعادة المحاولة متاحة للمرحلة الفاشلة فقط.')
        return public(updated)

    return app
