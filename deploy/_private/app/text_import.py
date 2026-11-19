"""Plain-text individual-support-plan analyzer; no OCR or network access."""
from support_analyzer import analyze_support_text

class TextImportError(Exception):
    def __init__(self,message,code='TEXT_INPUT'):
        self.message,self.code=message,code
        super().__init__(code)

def parse_support_text(raw):
    try:
        return analyze_support_text(raw)
    except ValueError as exc:
        raise TextImportError('文章が空欄か読み取れません。原文を確認して再試行してください。', 'TEXT_EMPTY') from exc
