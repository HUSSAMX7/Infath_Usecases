from dataclasses import dataclass, field
from pathlib import Path
import os

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: (ROOT / os.getenv('APP_DATA_DIR', '.local/invoice-app')).resolve())
    model_cache: Path = field(default_factory=lambda: ROOT / '.local/lightonocr')
    openai_key: str = field(default_factory=lambda: os.getenv('OPENAI_API_KEY', ''))
    openai_model: str = field(default_factory=lambda: os.getenv('OPENAI_MODEL', 'gpt-6-luna'))
    reasoning_effort: str = field(default_factory=lambda: os.getenv('OPENAI_REASONING_EFFORT', 'low'))
    max_files: int = field(default_factory=lambda: int(os.getenv('MAX_UPLOAD_FILES', '10')))
    max_file_mb: int = field(default_factory=lambda: int(os.getenv('MAX_FILE_MB', '20')))
    max_pages: int = field(default_factory=lambda: int(os.getenv('MAX_PDF_PAGES', '10')))
    confidence_threshold: float = field(default_factory=lambda: float(os.getenv('CONFIDENCE_THRESHOLD', '.75')))
    ocr_port: int = field(default_factory=lambda: int(os.getenv('LIGHTONOCR_PORT', '18987')))
    ocr_context: int = field(default_factory=lambda: int(os.getenv('LIGHTONOCR_CONTEXT', '8192')))
    ocr_max_tokens: int = field(default_factory=lambda: int(os.getenv('LIGHTONOCR_MAX_TOKENS', '4096')))
    ocr_timeout: int = field(default_factory=lambda: int(os.getenv('LIGHTONOCR_TIMEOUT', '900')))
    ocr_base_url: str = field(default_factory=lambda: os.getenv('LIGHTONOCR_BASE_URL', '').rstrip('/'))
