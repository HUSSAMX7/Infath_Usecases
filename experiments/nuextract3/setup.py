"""Download official, pinned NuExtract3 Q4 weights; invoices stay local."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.lightonocr.setup_runtime import download

REPO = 'numind/NuExtract3-GGUF'
REVISION = '28a1aae6288c5d50bdf999ca2e572240966d669b'
NAME = 'NuExtract3-Q4_K_M.gguf'
SHA256 = '7ee3c0ee9e5699a4391624ae758487f583f73b3242aa4e73dc2bb33e508d703e'
SIZE = 2783445984
CACHE = ROOT / '.local/nuextract3'

if __name__ == '__main__':
    download(f'https://huggingface.co/{REPO}/resolve/{REVISION}/{NAME}',
             CACHE / NAME, SHA256, SIZE, workers=12)
