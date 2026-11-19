"""Conservative mapping for common Japanese individual-support-plan layouts.

Maps explicitly marked child / guardian statements and assessment observations to
canonical headings understood by support_analyzer. Never invents text, translates
an unlabelled combined-intention statement into a blank, or contacts a cloud API.
Actual proprietary LITALICO PDF layouts must be validated against real redacted
samples: this is a pattern adapter, not an official format specification.
"""
import re
from unicodedata import normalize

# Normalized separators and role qualifiers for an explicit speaker.
DIVIDER = re.compile(r'\s*[|｜│┃]\s*|\t+')
BULLET = re.compile(r'^\s*(?:[・●○◯■◆□◇]|\d{1,2}[).、])\s*')
COMBINED = re.compile(
    r'^(?:(?:利用児|児童|子ども|こども|本人)(?:及び|および|と|・|／|/|ならびに|並びに)(?:その)?(?:家族|保護者)|'
    r'(?:本人|利用児)(?:及び|および|と)(?:家族|保護者))'
    r'(?:の生活に対する|の生活への|の)?(?:意向|希望|思い|意思|ニーズ)(?:等)?\s*[:：]?',
)
CHILD = re.compile(
    r'^(?:【|\[|\(|（)?(?:本人|児童本人|利用児|利用児童|子ども|こども|お子さま|お子様)'
    r'(?:】|\]|\)|）)?\s*(?:(?:の)?(?:希望|意向|意思|思い|ニーズ))?\s*(?:[:：]|\s+|$)'
)
FAMILY = re.compile(
    r'^(?:【|\[|\(|（)?(?:保護者|ご家族|家族|父親|母親|父|母|親御さん)'
    r'(?:】|\]|\)|）)?\s*(?:(?:の)?(?:希望|意向|意思|思い|ニーズ))?\s*(?:[:：]|\s+|$)'
)
# A speaker heading without colon or with wrapping parentheses is common in forms.
SPEAKER = re.compile(
    r'(?P<label>(?:【|\[|\(|（)?(?:本人|児童本人|利用児|利用児童|子ども|こども|お子さま|お子様|保護者|ご家族|家族|父親|母親|父|母)'
    r'(?:】|\]|\)|）)?\s*(?:(?:の)?(?:希望|意向|意思|思い|ニーズ))?)\s*[:：]'
)
OBSERVATIONS = re.compile(
    r'^(?P<head>アセスメント(?:結果|内容)?|現在の状況|現在の様子|現状と課題|本人の現状|'
    r'本人の状況|児童の状況|子どもの様子|日常生活の状況|生活の状況|生活状況|'
    r'観察結果|行動観察|発達状況|発達の状況|本人の強み|強み|得意なこと|できていること|'
    r'困りごと|困っていること|課題と支援ニーズ|支援ニーズ|解決すべき課題)(?=\s|[:：|｜]|$)\s*[:：|｜]?\s*(.*)$'
)
ASSESS_SUB = frozenset({'強み','得意なこと','できていること','困りごと','困っていること','観察結果','行動観察','発達状況','発達の状況','支援ニーズ','生活状況','生活の状況','日常生活の状況'})


def _norm(s):
    return normalize('NFKC', s).replace('：', ':').strip()


def _speaker(piece, *, broad=False):
    """Explicit *labels*, never determine a speaker by guessing from text content."""
    s = _norm(BULLET.sub('', piece)).strip('【】[]() ')
    # Display-label variants used by the app and by common Japanese forms.
    aliases = (
        (r'^本人の希望[・･/／]意思\s*[:：]?', '本人の意向'),
        (r'^本人の希望[・･/／]意向\s*[:：]?', '本人の意向'),
        (r'^保護者[・･/／]家族の(?:意向|希望)\s*[:：]?', '保護者の意向'),
        (r'^家族[・･/／]保護者の(?:意向|希望)\s*[:：]?', '保護者の意向'),
    )
    for pattern,heading in aliases:
        match = re.match(pattern, s)
        if match:
            return heading,s[match.end():].strip(' :')
    for pattern, field in ((CHILD,'本人の意向'),(FAMILY,'保護者の意向')):
        match = pattern.match(s)
        if match:
            tail = s[match.end():].strip(' :')
            return field, tail
    if broad:
        # Bracketed headings, e.g. (本人) 本文; only inside confirmed combined section.
        m = re.match(r'^\s*(?:本人|利用児童|子ども|こども)は\s*',s)
        if m: return '本人の意向',s
        m = re.match(r'^\s*(?:保護者|家族|母|父)は\s*',s)
        if m: return '保護者の意向',s
    return None


def _body(s):
    return s.strip(' :|｜\t')


def prepare_support_text(raw):
    """(normalized_parser_text, warnings): explicit-attribution transformations.

    The displayed/persisted original is kept byte-for-byte by the caller.
    """
    out=[]
    combined=False
    colmap=None
    unresolved=0
    observed_subheading=False
    for original in raw.splitlines():
        line=_norm(original)
        if not line:
            out.append('')
            continue
        # A combined heading does NOT mean its whole following text belongs to the child.
        m=COMBINED.match(line)
        if m:
            combined=True
            colmap=None
            out.append('備考欄')  # stop inheriting previous single-speaker field
            tail=_body(line[m.end():])
            if not tail:
                continue
            line=tail
        # Table with two speaker-specific columns: heading row followed by values row.
        if '|' in line or '｜' in line or '\t' in line:
            cells=[_body(t) for t in DIVIDER.split(line)]
            labelled=[_speaker(c) for c in cells]
            role_cols={i:role[0] for i,role in enumerate(labelled) if role and not role[1]}
            if len(set(role_cols.values()))==2:
                colmap=role_cols
                combined=False
                out.append('備考欄')
                continue
            if colmap and len(cells)>max(colmap):
                found=0
                for i,heading in colmap.items():
                    text=_body(cells[i])
                    if text and text not in {'－','-','なし','未記入','空欄'}:
                        out.append(f'{heading}：{text}')
                        found+=1
                if found: continue
            if len(cells)>1:
                # e.g. 利用児及び家族の生活に対する意向|本人:...|保護者:...
                pair=[_speaker(c) for c in cells]
                pair=[x for x in pair if x]
                if pair and all(x[1] or len(cells)==2 for x in pair):
                    for head,tail in pair:
                        out.append(f'{head}：{tail}' if tail else head)
                    if len(pair)>=2: combined=False
                    continue
        else:
            colmap=None
        # Combined intent with inline speakers on one line.
        # Only split at clear colon-separated role labels; no arbitrary sentence splitting.
        markers=list(SPEAKER.finditer(line))
        if markers:
            parts=[]
            for idx, match in enumerate(markers):
                value=line[match.end():markers[idx+1].start() if idx+1<len(markers) else len(line)].strip(' 　|｜;；、')
                role=_speaker(match.group('label')+':')
                if role:
                    parts.append((role[0],value))
            if parts and (len(parts)>1 or markers[0].start()==0):
                for head,value in parts:
                    out.append(f'{head}：{value}' if value else head)
                combined=False
                continue
        role=_speaker(line,broad=combined)
        if role:
            out.append(f'{role[0]}：{role[1]}' if role[1] else role[0]);combined=False;continue
        # Composite display label, often copied from a staff review screen.
        compound=re.match(r'^アセスメント[・･/／]現在の状況\s*[:：]?\s*(.*)$',line)
        if compound:
            out.append('アセスメント：'+compound.group(1))
            combined=False
            continue
        observe=OBSERVATIONS.match(line)
        if observe:
            head=observe.group('head')
            content=observe.group(2).strip(' :')
            observed_subheading=head in ASSESS_SUB
            out.append('アセスメント：'+(head+'：' if observed_subheading else '')+content)
            combined=False
            continue
        if combined:
            # Without speaker evidence, do not fill either intention field.
            if re.match(r'^(?:備考|総合的な支援|長期目標|短期目標|計画開始日|本人支援|家族支援|移行支援)',line):
                combined=False
                out.append(line)
            else:
                unresolved+=1
                out.append('備考欄')
        else:
            out.append(line)
    warnings=[]
    if unresolved:
        warnings.append('本人と家族の意向が同じ欄にあり、発言者を判定できない文章があります。原文から本人・保護者の意向を分けて確認してください。')
    return '\n'.join(out),warnings
