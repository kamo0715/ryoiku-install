"""Conservative local parsing of pre-recognized Japanese individual support plans.

No LLM/API, no network, no invented statements. Recognition output is untrusted:
return only explicitly labelled text and keep the original text intact for review.
"""
import re
from datetime import date
from unicodedata import normalize

MAX_TEXT_CHARS = 18_000
MAX_FIELD_CHARS = 8_000

# Each pattern must identify a *label*, not just a topic that appears in a sentence.
FIELD_LABELS = {
    'child_intentions': ('本人の希望', '本人希望', '本人の意向', '本人意向', '本人の意思', '本人のニーズ', 'こどもの希望', '子どもの希望', '児童の希望', '本人の思い'),
    'family_intentions': ('保護者の意向', '保護者の希望', '保護者のニーズ', '家族の意向', '家族の希望', '家庭の意向', '保護者意向'),
    'assessment': ('総合アセスメント', 'アセスメント結果', 'アセスメント', '現状と課題', '現在の状況', '現在の様子', '本人の現状', '支援の必要性'),
    'long_goal': ('長期支援目標', '長期的な目標', '長期目標', '長期の目標'),
    'short_goal': ('短期支援目標', '短期的な目標', '短期目標', '短期の目標'),
    'support_policy': ('総合的な支援の方針', '総合的支援の方針', '総合支援方針', '支援の基本方針', '基本的な支援方針', '支援方針'),
    'domain_health': ('健康・生活', '健康と生活', '健康/生活'),
    'domain_motor': ('運動・感覚', '運動と感覚', '運動/感覚'),
    'domain_cognition': ('認知・行動', '認知と行動', '認知/行動'),
    'domain_language': ('言語・コミュニケーション', '言語とコミュニケーション', '言語/コミュニケーション'),
    'domain_social': ('人間関係・社会性', '人間関係と社会性', '人間関係/社会性'),
    'accommodation': ('合理的配慮', '安全上の配慮', '安全面の配慮', '配慮事項', '支援上の留意事項', '留意事項'),
    'family_support': ('家族支援の方針', '家族支援の内容', '家族支援'),
    'transition_support': ('移行支援の方針', '移行支援の内容', '移行支援'),
    'community_support': ('地域支援・地域連携', '地域支援/地域連携', '地域支援', '地域連携の内容', '地域連携'),
    'other_notes': ('その他の職員間共有事項', 'その他の特記事項', '職員間共有事項', 'その他特記事項'),
    'period_start': ('計画の開始日', '計画開始日', '適用開始日', '支援開始日'),
    'period_end': ('計画の終了日', '計画終了日', '適用終了日', '支援終了日'),
}
DOMAIN_KEYS = frozenset(k for k in FIELD_LABELS if k.startswith('domain_'))
LABEL_VARIANTS = sorted(
    ((normalize('NFKC', label), key) for key, labels in FIELD_LABELS.items() for label in labels),
    key=lambda row: len(row[0]), reverse=True,
)
# Omit document metadata rather than appending it to the previous goal by accident.
META_HEADINGS = re.compile(
    r'^(?:個別支援計画(?:書)?|作成年月日|作成日|作成者|担当者|事業所(?:名)?|'
    r'児童氏名|利用者氏名|対象児童(?:名)?|氏名|お名前|生年月日|住所|電話番号|'
    r'提供時間|サービス提供時間|モニタリング|署名|確認者|管理者|'
    r'優先順位|支援内容の詳細|別表|備考欄|支援プログラム)(?=\s|[:：|｜]|$)'
)
TABLE_HEADERS = frozenset({'項目', '区分', '分類', '領域', '支援領域', '具体的な支援内容',
                           '支援内容', '支援目標', '達成目標', '本人支援', '内容', '具体的な目標',
                           '達成時期', '提供形態', '評価', '項目名', '具体的支援内容', '目標',
                           '長期・短期', '番号', '支援の方向性', '支援上の留意点'})
COLUMN_SPLITTER = re.compile(r'\s*[|｜│┃]\s*|\t+|[ 　]{3,}')
BULLET = re.compile(r'^\s*(?:[■●◆□◇◎◯○・]|\d{1,2}[.)、])\s*')
PERSON = re.compile(r'^\s*(?:児童氏名|利用者氏名|対象児童名|氏名|お名前)\s*[:：|｜\t　 ]\s*(\S.*?)\s*$')
DATE_RE = re.compile(r'(?<!\d)(20\d{2})\s*[年/.\-]\s*(\d{1,2})\s*[月/.\-]\s*(\d{1,2})\s*日?')


def _date(value):
    m = DATE_RE.search(normalize('NFKC', value))
    if not m:
        return ''
    try:
        return date(*(int(x) for x in m.groups())).isoformat()
    except ValueError:
        return ''


def _match_label(piece):
    """Return (field, remainder) only for anchored labels with a clear boundary."""
    normalized = normalize('NFKC', BULLET.sub('', piece.strip()))
    normalized = normalized.lstrip(' 【[〈<').strip()
    for label, field in LABEL_VARIANTS:
        if not normalized.startswith(label):
            continue
        tail = normalized[len(label):]
        # Handle a bounded qualifier such as 長期目標（6か月）.
        qualifier = re.match(r'^\s*\([^()]{1,24}\)', tail)
        if qualifier:
            tail = tail[qualifier.end():]
        if tail and not (tail[0].isspace() or tail[0] in ':：|｜】]>–—=-'):
            continue
        return field, tail.strip(' \t:：|｜】]>–—=-')
    return None


def _generic(piece):
    return normalize('NFKC', BULLET.sub('', piece.strip())).strip(' :：|｜') in TABLE_HEADERS


def _parse_row(line):
    """Process a single line, handling multi-column support-plan table rows."""
    columns = [part.strip() for part in COLUMN_SPLITTER.split(line) if part.strip()]
    if len(columns) > 1:
        matches = [(i, _match_label(piece)) for i, piece in enumerate(columns)]
        matches = [(i, item) for i, item in matches if item]
        if matches:
            # Explicit goal/family intention labels take priority over domain header cells.
            i, (field, rem) = matches[0]
            # Prefix column such as 本人支援 | 健康・生活 is a contextual table category.
            other = [c for c in columns[i+1:] if not _generic(c)]
            parts = ([rem] if rem else []) + other
            return 'field', field, ' / '.join(p for p in parts if p)
        if all(_generic(c) for c in columns):
            return 'heading', None, ''
        if _generic(columns[0]):
            return 'continuation', None, ' / '.join(c for c in columns[1:] if not _generic(c))
    matched = _match_label(line)
    if matched:
        return 'field', matched[0], matched[1]
    if _generic(line) or META_HEADINGS.match(normalize('NFKC', BULLET.sub('', line.strip()))):
        return 'heading', None, ''
    if len(columns) > 1 and _generic(columns[0]):
        return 'continuation', None, ' / '.join(columns[1:])
    if len(columns) > 1 and _generic(columns[1]):
        return 'continuation', None, ' / '.join(columns[2:]) if len(columns) > 2 else ''
    # Explicit unknown metadata labels stop a preceding field from swallowing later rows.
    if re.match(r'^.{1,18}[:：]\s*\S',line) and not re.match(r'^[・●◆■]',line):
        return 'unknown', None, ''
    return 'continuation', None, line.strip()


def analyze_support_text(raw):
    """Return (fields, count, warnings, names) with original source preserved.

    No field is filled by guessing from prose alone. No external requests or logging.
    """
    source = raw.strip()[:MAX_TEXT_CHARS]
    if not source:
        raise ValueError('empty support plan text')
    fields = {'original_text': source}
    bucket = {}
    current = None
    names = []
    unassigned = 0
    ignored_headers = 0
    for source_line in source.splitlines():
        line = source_line.strip()
        if not line:
            continue
        name_match = PERSON.match(line)
        if name_match:
            names.append(name_match.group(1).strip(' :：　|｜'))
            current = None
            continue
        kind, key, value = _parse_row(line)
        if kind == 'field':
            current = key
            bucket.setdefault(current, [])
            if value:
                bucket[current].append(value)
        elif kind == 'heading':
            ignored_headers += 1
            # Generic subheaders within a domain table should not terminate it.
            if not (current in DOMAIN_KEYS and _generic(line)):
                current = None
        elif kind == 'unknown':
            current = None
            unassigned += 1
        elif current and value:
            bucket.setdefault(current, []).append(value)
        elif value:
            unassigned += 1
    invalid_dates = []
    for key, values in bucket.items():
        # Retain separate lines and remove exact duplicates from repeated table headers/pages.
        values = list(dict.fromkeys(v.strip() for v in values if v.strip()))
        entry = '\n'.join(values).strip()
        if key.startswith('period_'):
            parsed = _date(entry)
            if entry and not parsed:
                invalid_dates.append(key)
            entry = parsed
        if entry:
            fields[key] = entry[:MAX_FIELD_CHARS]
    count = len(fields) - 1
    warnings = []
    if not count:
        warnings.append('項目の見出しを確実に判定できませんでした。原文から手動転記してください。')
    elif count < 3:
        warnings.append('自動転記できた項目が少なめです。未入力の欄を原文で確認してください。')
    if unassigned:
        warnings.append('見出しのない文章や判定できない箇所があります。原文を見ながら必要な項目を補ってください。')
    if invalid_dates:
        warnings.append('日付を正しく判定できない箇所があります。原本で開始日と終了日を確認してください。')
    warnings.append('自動転記の候補です。氏名・目標・5領域・日付を原本と照合してから保存してください。')
    return fields, count, warnings, names
