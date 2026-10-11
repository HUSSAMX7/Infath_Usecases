import logging
from pathlib import Path
from threading import Event, Thread
import time

from .models import Proposal
from .services.errors import StageError
from .storage import Store
from .validation import validate_invoice

logger = logging.getLogger(__name__)


class InvoiceWorker:
    def __init__(self, store: Store, ocr, classifier, threshold: float):
        self.store, self.ocr, self.classifier = store, ocr, classifier
        self.threshold = threshold
        self.stopped = Event()
        self.thread = None

    def start(self):
        self.store.recover()
        self.thread = Thread(target=self.run, name='invoice-worker', daemon=True)
        self.thread.start()

    def run(self):
        while not self.stopped.is_set():
            document = self.store.claim_next()
            if document:
                self.process(document)
            else:
                self.stopped.wait(.5)

    def process(self, document: dict):
        invoice_id = document['id']
        pages = document['pages']
        stage = 'ocr'
        active_page = None
        started = time.perf_counter()
        try:
            for page in pages:
                if page['status'] == 'complete':
                    continue
                if self.stopped.is_set():
                    raise StageError('interrupted', 'توقفت المعالجة. يمكنك إعادة المحاولة.')
                active_page = page
                page.update(status='reading', error=None)
                self.store.update(invoice_id, {'stage': 'ocr', 'current_page': page['number'], 'pages': pages})

                def progress(text):
                    page['text'] = text
                    Path(page['preview_path']).with_suffix('.ocr.md').write_text(text, encoding='utf-8')
                    self.store.update(invoice_id, {'pages': pages})

                result = self.ocr.read(Path(page['preview_path']), on_text=progress)
                page.update(result, status='complete', error=None)
                self.store.update(invoice_id, {'pages': pages})
            active_page = None
            stage = 'analysis'
            text = '\n\n'.join(f'--- PAGE {p["number"]} ---\n{p["text"]}' for p in pages)
            self.store.update(invoice_id, {'stage': stage, 'ocr_text': text, 'current_page': None, 'analysis_input': text})
            if self.stopped.is_set():
                raise StageError('interrupted', 'توقفت المعالجة قبل التحليل. يمكنك إعادة المحاولة.')
            result = self.classifier.classify_invoice(text)
            proposal = Proposal.model_validate(result['proposal'])
            warnings = [w.model_dump() for w in validate_invoice(proposal.extracted_data, proposal.items)] + result.get('extraction_warnings', [])
            method = result.get('method', 'openai')
            status = 'needs_review' if (method == 'regex' or warnings or proposal.classification is None or proposal.confidence < self.threshold) else 'classified'
            self.store.update(invoice_id, {'status': status, 'stage': None, 'ai_proposal': result['proposal'],
                                          'analysis': {**{k: v for k, v in result.items() if k != 'proposal'}, 'method': method},
                                          'llm_input': text if method == 'openai' else None,
                                          'warnings': warnings, 'error': None, 'attempt_seconds': time.perf_counter() - started})
        except StageError as error:
            if active_page:
                active_page.update(status='failed', error=error.message, **error.details)
            self.store.update(invoice_id, {'status': 'failed', 'stage': stage, 'pages': pages,
                                          'error': {'code': error.code, 'message': error.message, 'stage': stage},
                                          'failure_details': error.details, 'attempt_seconds': time.perf_counter() - started})
        except Exception:
            logger.exception('Invoice processing failed: %s', invoice_id)
            if active_page:
                active_page.update(status='failed', error='تعذّر إكمال القراءة.')
            self.store.update(invoice_id, {'status': 'failed', 'stage': stage, 'pages': pages,
                                          'error': {'code': 'processing_error', 'message': 'تعذّر إكمال هذه المرحلة. راجع سجل التطبيق ثم أعد المحاولة.', 'stage': stage}})

    def close(self):
        self.stopped.set()
        self.ocr.close()
        if self.thread:
            self.thread.join(timeout=15)
