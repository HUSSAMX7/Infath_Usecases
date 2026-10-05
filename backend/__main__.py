import os
import uvicorn
from .app import create_app

if __name__ == '__main__':
    # A single process owns the local OCR model and SQLite queue. No --reload.
    uvicorn.run(create_app(), host=os.getenv('APP_HOST', '127.0.0.1'), port=int(os.getenv('APP_PORT', '8000')))
