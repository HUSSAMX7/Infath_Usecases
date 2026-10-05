"""Run the attached image through local LightOnOCR; retain raw output and timing."""
from pathlib import Path
import argparse
import base64
import json
import os
import subprocess
import time

import requests

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / '.local' / 'lightonocr'
RESULTS = Path(__file__).resolve().parent / 'results'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', type=Path, default=CACHE / 'inputs' / 'handwritten-invoice.png')
    parser.add_argument('--name', default='original-q8')
    parser.add_argument('--model', default='LightOnOCR-2-1B-Q8_0.gguf')
    parser.add_argument('--port', type=int, default=18987)
    parser.add_argument('--max-tokens', type=int, default=2048)
    args = parser.parse_args()
    output = RESULTS / args.name
    output.mkdir(parents=True, exist_ok=True)
    binaries = list((CACHE / 'runtime').rglob('llama-server.exe'))
    if not binaries:
        raise SystemExit('Run setup_runtime.py first.')
    exe = binaries[0]
    command = [str(exe), '-m', str(CACHE / 'models' / args.model),
               '--mmproj', str(CACHE / 'models' / 'mmproj-LightOnOCR-2-1B-f16.gguf'),
               '--host', '127.0.0.1', '--port', str(args.port), '-ngl', '0',
               '--no-mmproj-offload', '-t', '4', '-tb', '4', '-c', '4096',
               '--parallel', '1', '--no-webui']
    metadata = {'command': command, 'image': str(args.image.resolve()),
                'request': {'temperature': 0, 'max_tokens': args.max_tokens,
                            'prompt': 'image-only, matching the LightOnOCR model example'},
                'runtime_manifest': json.loads((CACHE / 'manifest.json').read_text(encoding='utf-8')),
                'mode': 'CPU only; no image uploaded to an external service'}
    (output / 'metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    log = (output / 'server.log').open('w', encoding='utf-8')
    started = time.perf_counter()
    server = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    print(f'Server PID {server.pid}; logs: {output / "server.log"}', flush=True)
    base = f'http://127.0.0.1:{args.port}'
    try:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if server.poll() is not None:
                raise RuntimeError(f'Server exited with {server.returncode}; inspect server.log')
            try:
                if requests.get(base + '/health', timeout=2).status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(1)
        else:
            raise RuntimeError('Server did not become healthy within 180 seconds')
        metadata['model_startup_seconds'] = time.perf_counter() - started
        image_url = 'data:image/png;base64,' + base64.b64encode(args.image.read_bytes()).decode('ascii')
        request = {'messages': [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': image_url}}]}],
                   'temperature': 0, 'max_tokens': args.max_tokens, 'stream': True,
                   'stream_options': {'include_usage': True}, 'seed': 42}
        generation_start = time.perf_counter()
        content = ''
        events = []
        first_token = None
        status_at = time.perf_counter()
        with requests.post(base + '/v1/chat/completions', json=request, stream=True, timeout=(30, 900)) as response:
            response.raise_for_status()
            with (output / 'events.jsonl').open('w', encoding='utf-8') as event_file:
                for line in response.iter_lines(chunk_size=1):
                    if not line or not line.startswith(b'data: '):
                        continue
                    data = line[6:].decode('utf-8')
                    if data == '[DONE]':
                        break
                    event = json.loads(data)
                    events.append(event)
                    event_file.write(json.dumps(event, ensure_ascii=False) + '\n')
                    event_file.flush()
                    for choice in event.get('choices', []):
                        token = choice.get('delta', {}).get('content') or ''
                        if token:
                            if first_token is None:
                                first_token = time.perf_counter() - generation_start
                                print(f'First token after {first_token:.1f}s', flush=True)
                            content += token
                            (output / 'raw_ocr.md').write_text(content, encoding='utf-8')
                    if time.perf_counter() - status_at > 20:
                        print(f'Generating: {len(content)} characters, {time.perf_counter() - generation_start:.1f}s', flush=True)
                        status_at = time.perf_counter()
        metadata['generation_seconds'] = time.perf_counter() - generation_start
        metadata['first_token_seconds'] = first_token
        metadata['usage'] = next((e['usage'] for e in reversed(events) if 'usage' in e), None)
        metadata['finish_reason'] = next((c.get('finish_reason') for e in reversed(events) for c in e.get('choices', []) if c.get('finish_reason')), None)
        metadata['timings'] = next((e['timings'] for e in reversed(events) if 'timings' in e), None)
        metadata['output_characters'] = len(content)
        (output / 'raw_ocr.md').write_text(content, encoding='utf-8')
        print(json.dumps({k: v for k, v in metadata.items() if k in ['generation_seconds', 'first_token_seconds', 'usage', 'finish_reason', 'timings', 'output_characters']}, ensure_ascii=False, indent=2), flush=True)
    except Exception as error:
        metadata['error'] = repr(error)
        raise
    finally:
        (output / 'metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
        server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()
        log.close()


if __name__ == '__main__':
    main()
