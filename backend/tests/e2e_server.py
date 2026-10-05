"""Dedicated E2E test server with labelled service doubles and isolated storage."""
from pathlib import Path
from uuid import uuid4
from PIL import Image
from backend.app import create_app
from backend.config import ROOT, Settings
from backend.tests.test_flow import FakeOCR, FakeClassifier, proposal

fixtures = ROOT / '.local/e2e-fixtures'
fixtures.mkdir(parents=True, exist_ok=True)
Image.new('RGB', (400, 550), 'white').save(fixtures / 'invoice.png')
images = [Image.new('RGB', (400, 550), color) for color in ('white', '#eeeeee')]
images[0].save(fixtures / 'two-pages.pdf', format='PDF', save_all=True, append_images=images[1:])
classifier = FakeClassifier()
classifier.result = proposal(mismatch=True)
app = create_app(Settings(data_dir=ROOT / '.local/e2e-runs' / str(uuid4()), openai_key='TEST ONLY'),
                 ocr=FakeOCR(), classifier=classifier)
