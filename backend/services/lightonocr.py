"""One warm, locally owned llama.cpp process; one invoice worker calls it."""
import base64
import json
import os
from pathlib import Path
import subprocess
import time

import requests

from ..config import Settings
from .errors import StageError


class LightOnOCR:
    model_name = 'LightOnOCR-2-1B · Q8_0 / F16'

    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.ocr_base_url or f'http://127.0.0.1:{settings.ocr_port}'
        self.process = None
        self.log = None
        self.state = 'not_loaded'
        self.error = None

    def available(self) -> bool:
        cache = self.settings.model_cache
        return bool(self.settings.ocr_base_url or (
            list((cache / 'runtime').rglob('llama-server.exe'))
            and (cache / 'models/LightOnOCR-2-1B-Q8_0.gguf').is_file()
            and (cache / 'models/mmproj-LightOnOCR-2-1B-f16.gguf').is_file()))

    def ensure_ready(self):
        if self.state == 'ready':
            try:
                if requests.get(self.base_url + '/health', timeout=2).status_code == 200:
                    return
            except requests.RequestException:
                pass
            self.close()
        if not self.available():
            raise StageError('ocr_not_installed', 'أوزان LightOnOCR أو llama.cpp غير موجودة. راجع تعليمات الإعداد.')
        self.state = 'starting'
        if not self.settings.ocr_base_url:
            cache = self.settings.model_cache
            exe = next((cache / 'runtime').rglob('llama-server.exe'))
            # Refuse to silently attach to an unrelated process on the configured port.
            try:
                requests.get(self.base_url + '/health', timeout=1)
            except requests.ConnectionError:
                pass
            except requests.RequestException:
                raise StageError('ocr_port_in_use', 'منفذ OCR مشغول؛ غيّر LIGHTONOCR_PORT أو حدّد عنوان خدمة OCR الموجودة.')
            else:
                raise StageError('ocr_port_in_use', 'منفذ OCR مشغول؛ غيّر LIGHTONOCR_PORT أو حدّد عنوان خدمة OCR الموجودة.')
            command = [str(exe), '-m', str(cache / 'models/LightOnOCR-2-1B-Q8_0.gguf'),
                       '--mmproj', str(cache / 'models/mmproj-LightOnOCR-2-1B-f16.gguf'),
                       '--host', '127.0.0.1', '--port', str(self.settings.ocr_port),
                       '-ngl', '0', '--no-mmproj-offload', '-t', '4', '-tb', '4',
                       '-c', str(self.settings.ocr_context), '--parallel', '1', '--no-webui']
            self.log = (self.settings.data_dir / 'lightonocr-server.log').open('a', encoding='utf-8')
            self.process = subprocess.Popen(command, stdout=self.log, stderr=subprocess.STDOUT,
                                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if self.process and self.process.poll() is not None:
                self.state = 'error'
                self.close()
                raise StageError('ocr_start_failed', 'تعذّر تشغيل LightOnOCR. راجع سجل الخدمة المحلي وإعداد المنفذ.')
            try:
                if requests.get(self.base_url + '/health', timeout=2).status_code == 200:
                    self.state = 'ready'
                    self.error = None
                    return
            except requests.RequestException:
                pass
            time.sleep(.5)
        self.state = 'error'
        self.close()
        raise StageError('ocr_start_timeout', 'انتهت مهلة تحميل LightOnOCR. يمكنك إعادة المحاولة.')

    def read(self, image: Path, on_text=None) -> dict:
        self.ensure_ready()
        image_url = 'data:image/png;base64,' + base64.b64encode(image.read_bytes()).decode('ascii')
        request = {'messages': [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': image_url}}]}],
                   'temperature': 0, 'seed': 42, 'max_tokens': self.settings.ocr_max_tokens,
                   'stream': True, 'stream_options': {'include_usage': True}}
        started = time.perf_counter()
        text = ''
        usage = None
        finish = None
        last_saved = started
        try:
            with requests.post(self.base_url + '/v1/chat/completions', json=request, stream=True,
                               timeout=(30, self.settings.ocr_timeout)) as response:
                response.raise_for_status()
                for line in response.iter_lines(chunk_size=1):
                    if time.perf_counter() - started > self.settings.ocr_timeout:
                        raise StageError('ocr_timeout', 'انتهت مهلة قراءة الصفحة؛ القراءة الجزئية محفوظة.')
                    if not line.startswith(b'data: '):
                        continue
                    body = line[6:].decode('utf-8')
                    if body == '[DONE]':
                        break
                    event = json.loads(body)
                    if event.get('error'):
                        raise StageError('ocr_response_error', 'أعادت خدمة OCR خطأ أثناء القراءة.')
                    usage = event.get('usage') or usage
                    for choice in event.get('choices', []):
                        text += choice.get('delta', {}).get('content') or ''
                        finish = choice.get('finish_reason') or finish
                    if on_text and time.perf_counter() - last_saved >= 1:
                        on_text(text)
                        last_saved = time.perf_counter()
            if on_text:
                on_text(text)
            if finish != 'stop':
                raise StageError('ocr_incomplete', 'قراءة الصفحة لم تكتمل. تحقّق من حد الرموز قبل إعادة المحاولة.', {'finish_reason': finish, 'seconds': time.perf_counter() - started, 'usage': usage})
            if not text.strip():
                raise StageError('ocr_empty', 'لم يعثر LightOnOCR على نص في هذه الصفحة.')
            return {'text': text, 'seconds': time.perf_counter() - started, 'usage': usage, 'finish_reason': finish}
        except (requests.RequestException, ValueError) as error:
            if on_text:
                on_text(text)
            raise StageError('ocr_connection_error', 'تعذّر إكمال الاتصال بـLightOnOCR؛ القراءة الجزئية محفوظة.') from error

    def close(self):
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.process = None
        if self.log:
            self.log.close()
            self.log = None
        self.state = 'not_loaded'
