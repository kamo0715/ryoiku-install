"""Extract selectable text from a PDF. No OCR and no outbound API requests."""
from io import BytesIO
from pypdf import PdfReader
from text_import import TextImportError

MAX_PDF_BYTES = 8 * 1024 * 1024
MAX_PAGES = 12
MAX_TEXT_CHARS = 18_000

def extract_support_pdf(raw):
    if not raw or len(raw) > MAX_PDF_BYTES:
        raise TextImportError('PDFは8MB以下にしてください。', 'PDF_TOO_LARGE')
    if not raw.lstrip().startswith(b'%PDF-'):
        raise TextImportError('PDFファイルを読み込めません。', 'PDF_FORMAT')
    try:
        reader = PdfReader(BytesIO(raw), strict=True)
        if reader.is_encrypted:
            raise TextImportError('パスワード付きPDFは読み取れません。', 'PDF_ENCRYPTED')
        if not 1 <= len(reader.pages) <= MAX_PAGES:
            raise TextImportError(f'PDFは1〜{MAX_PAGES}ページまでにしてください。', 'PDF_PAGES')
        page_text=[]
        for page in reader.pages:
            text = (page.extract_text() or '').strip()
            page_text.append(text)
        joined='\n'.join(page_text).strip()
    except TextImportError:
        raise
    except Exception as exc:
        raise TextImportError('PDFから文字情報を抽出できませんでした。PDFを確認してください。', 'PDF_READ') from exc
    if not joined:
        raise TextImportError('このPDFは画像だけの可能性があります。ロリポップ版はOCR非対応です。文字選択できるPDFか、コピーした文章を使用してください。', 'PDF_NO_TEXT')
    warnings=[]
    if any(not t for t in page_text):
        warnings.append('一部のページに文字情報がありません。画像化された部分は転記されていません。')
    if len(joined)>MAX_TEXT_CHARS:
        warnings.append('PDFの文章が長いため18,000文字で切り詰めました。原文と照合してください。')
        joined=joined[:MAX_TEXT_CHARS]
    return joined, 0, warnings
