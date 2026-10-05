"""Download a portable CPU runtime and pinned LightOnOCR weights for this experiment."""
from pathlib import Path
import concurrent.futures
import hashlib
import json
import shutil
import time
import zipfile

import requests

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / '.local' / 'lightonocr'
REPO = 'ggml-org/LightOnOCR-2-1B-GGUF'
REVISION = '7d4daf70c2856a155b1413def00f4ae59843a9cf'
RELEASE = 'b11387'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def download(url, path, expected_sha=None, expected_size=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and (expected_size is None or path.stat().st_size == expected_size):
        if expected_sha is None or digest(path) == expected_sha:
            print(f'Cached: {path.name}', flush=True)
            return str(path)
    partial = path.with_suffix(path.suffix + '.partial')
    started = time.perf_counter()
    if expected_size and expected_size > 256 * 1024 * 1024:
        # Resume completed bytes and use separate range files to avoid a slow single connection.
        prefix_size = partial.stat().st_size if partial.exists() else 0
        head = requests.head(url, allow_redirects=True, timeout=30)
        head.raise_for_status()
        resolved_url = head.url
        chunk_bytes = 64 * 1024 * 1024
        ranges = [(start, min(start + chunk_bytes, expected_size) - 1)
                  for start in range(prefix_size, expected_size, chunk_bytes)]

        def get_range(bounds):
            start, end = bounds
            chunk_path = path.with_suffix(path.suffix + f'.chunk-{start}')
            failures = 0
            while True:
                present = chunk_path.stat().st_size if chunk_path.exists() else 0
                if present == end - start + 1:
                    return chunk_path
                actual_start = start + present
                request_end = min(actual_start + 4 * 1024 * 1024 - 1, end)
                try:
                    with requests.get(resolved_url, headers={'Range': f'bytes={actual_start}-{request_end}'},
                                      stream=True, timeout=(30, 120)) as response:
                        response.raise_for_status()
                        if response.status_code != 206 or not response.headers.get('Content-Range', '').startswith(f'bytes {actual_start}-'):
                            raise RuntimeError('The download server did not honor the byte range')
                        with chunk_path.open('ab') as stream:
                            for chunk in response.iter_content(256 * 1024):
                                stream.write(chunk)
                    failures = 0
                    if chunk_path.stat().st_size == end - start + 1:
                        break
                except requests.RequestException:
                    failures += 1
                    if failures == 6:
                        raise
                    print(f'{path.name}: retry range {start // 1000000} MB, preserving received bytes', flush=True)
                    time.sleep(1)
            if chunk_path.stat().st_size != end - start + 1:
                raise RuntimeError(f'Incomplete range for {path.name}')
            print(f'{path.name}: completed range {start // 1000000}-{end // 1000000} MB', flush=True)
            return chunk_path

        print(f'{path.name}: resume at {prefix_size / 1e6:.0f} MB; four range connections', flush=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            chunks = list(executor.map(get_range, ranges))
        assembled = path.with_suffix(path.suffix + '.assembled')
        with assembled.open('wb') as output:
            if prefix_size:
                with partial.open('rb') as source:
                    shutil.copyfileobj(source, output, 8 * 1024 * 1024)
            for chunk_path in chunks:
                with chunk_path.open('rb') as source:
                    shutil.copyfileobj(source, output, 8 * 1024 * 1024)
        if assembled.stat().st_size != expected_size or (expected_sha and digest(assembled) != expected_sha):
            raise RuntimeError(f'Integrity check failed: {path.name}')
        assembled.replace(path)
        for chunk_path in chunks:
            chunk_path.unlink()
        if partial.exists():
            partial.unlink()
        print(f'Downloaded and verified {path.name} in {time.perf_counter() - started:.1f}s', flush=True)
        return str(path)
    with requests.get(url, stream=True, timeout=(30, 120)) as response:
        response.raise_for_status()
        size = int(response.headers.get('content-length', 0))
        received = 0
        announced = time.perf_counter()
        with partial.open('wb') as output:
            for chunk in response.iter_content(4 * 1024 * 1024):
                if chunk:
                    output.write(chunk)
                    received += len(chunk)
                if time.perf_counter() - announced > 15:
                    print(f'{path.name}: {received / 1e6:.0f} MB / {size / 1e6:.0f} MB', flush=True)
                    announced = time.perf_counter()
    if expected_size is not None and partial.stat().st_size != expected_size:
        raise RuntimeError(f'Incomplete download: {path.name}')
    if expected_sha and digest(partial) != expected_sha:
        raise RuntimeError(f'SHA256 mismatch: {path.name}')
    partial.replace(path)
    print(f'Downloaded and verified {path.name} in {time.perf_counter() - started:.1f}s', flush=True)
    return str(path)


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    release = requests.get(f'https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/{RELEASE}', timeout=30)
    release.raise_for_status()
    release = release.json()
    asset = next(a for a in release['assets'] if a['name'] == f'llama-{RELEASE}-bin-win-cpu-x64.zip')
    tree = requests.get(f'https://huggingface.co/api/models/{REPO}/tree/{REVISION}?recursive=true&expand=true', timeout=30)
    tree.raise_for_status()
    entries = {item['path']: item for item in tree.json()}
    files = ['LightOnOCR-2-1B-Q8_0.gguf', 'mmproj-LightOnOCR-2-1B-f16.gguf']
    specs = [(asset['browser_download_url'], CACHE / asset['name'], asset['digest'].split(':')[-1], asset['size'])]
    for name in files:
        item = entries[name]
        specs.append((f'https://huggingface.co/{REPO}/resolve/{REVISION}/{name}', CACHE / 'models' / name, item.get('lfs', {}).get('oid'), item['size']))
    # These downloads are independent; generation runs sequentially later.
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        list(executor.map(lambda spec: download(*spec), specs))
    runtime = CACHE / 'runtime' / RELEASE
    runtime.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(CACHE / asset['name']) as archive:
        for entry in archive.infolist():
            target = (runtime / entry.filename).resolve()
            if not target.is_relative_to(runtime.resolve()):
                raise RuntimeError('Unexpected archive path')
        archive.extractall(runtime)
    original = Path(r'C:\Users\hosam\AppData\Local\Temp\codex-clipboard-378dc451-e0a4-46d8-a683-4553ddfb9a1b.png')
    image = CACHE / 'inputs' / 'handwritten-invoice.png'
    image.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(original, image)
    manifest = {
        'model_source': 'lightonai/LightOnOCR-2-1B',
        'gguf_repo': REPO, 'gguf_revision': REVISION, 'llama_cpp_release': RELEASE,
        'text_weights': files[0], 'vision_weights': files[1],
        'image_path': str(image), 'image_sha256': digest(image),
        'files': [{'name': path.name, 'size': path.stat().st_size, 'sha256': digest(path)} for _, path, _, _ in specs],
    }
    (CACHE / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'runtime': str(runtime), 'manifest': str(CACHE / 'manifest.json')}, indent=2), flush=True)


if __name__ == '__main__':
    main()
