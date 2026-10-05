from pathlib import Path
from contextlib import closing
import warnings

from PIL import Image, ImageOps
import pypdfium2 as pdfium


class DocumentError(ValueError):
    pass


def prepare_pages(original: Path, folder: Path, max_pages: int) -> list[dict]:
    """Validate bytes, then create bounded-size previews/inputs one page at a time."""
    pages = []
    try:
        if original.suffix == '.pdf':
            with closing(pdfium.PdfDocument(original)) as pdf:
                if not 0 < len(pdf) <= max_pages:
                    raise DocumentError(f'الحد الأقصى {max_pages} صفحات لكل فاتورة.')
                for index in range(len(pdf)):
                    page = pdf[index]
                    try:
                        scale = min(200 / 72, 1540 / max(page.get_size()))
                        bitmap = page.render(scale=scale)
                        try:
                            image = bitmap.to_pil().convert('RGB')
                            preview = folder / f'page-{index + 1}.png'
                            image.save(preview)
                            image.close()
                        finally:
                            bitmap.close()
                    finally:
                        page.close()
                    pages.append(page_record(index + 1, preview))
        else:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(original) as source:
                    if source.format not in {'PNG', 'JPEG', 'WEBP'}:
                        raise DocumentError('صيغة الصورة غير مدعومة.')
                    if source.width * source.height > 25_000_000:
                        raise DocumentError('الصورة أكبر من 25 مليون بكسل.')
                    image = ImageOps.exif_transpose(source)
                    if image.mode in ('RGBA', 'LA') or 'transparency' in image.info:
                        rgba = image.convert('RGBA')
                        background = Image.new('RGBA', rgba.size, 'white')
                        image = Image.alpha_composite(background, rgba).convert('RGB')
                        rgba.close()
                        background.close()
                    else:
                        image = image.convert('RGB')
                    image.thumbnail((1540, 1540))
                    preview = folder / 'page-1.png'
                    image.save(preview)
                    image.close()
                pages.append(page_record(1, preview))
    except DocumentError:
        raise
    except Exception as error:
        raise DocumentError('تعذّر فتح الملف. تحقّق أنه صورة أو PDF صالح وغير محمي بكلمة مرور.') from error
    return pages


def page_record(number: int, preview: Path) -> dict:
    return {'number': number, 'preview_path': str(preview), 'status': 'pending',
            'text': '', 'seconds': None, 'finish_reason': None, 'usage': None, 'error': None}
