"""Privacy-preserving, concrete support cues for external AI requests (v2.18).

Never transmit original notes, proper names, institution names, school names,
health histories, or arbitrary free text. Local text is inspected ONLY to
select from an audited set of pedagogically useful descriptions.

This is data-minimisation + pseudonymous roles, not legal 匿名加工情報.
Even pseudonymised contextual data may remain personal information.
"""
import json
import re
from catalog import OTHER_KINDS, KIND_GROUP, CATEGORY_FOCUS, CATEGORY_SAFETY, EXTRA_SAFETY

GOAL_TAGS = (
    (r'選択|選ぶ|選べ|決める|自己決定', '活動や手順を自分で選ぶ'),
    (r'意思表示|伝え|気持ち|希望|表現|発信', '意思や希望を伝える'),
    (r'協力|順番|交代|役割|共同|友達|集団', '協同・順番・役割調整'),
    (r'見通し|段取り|予定|手順|切り替え', '見通しをもって活動する'),
    (r'援助要請|助け|相談|お願い|頼る', '援助や休憩を求める'),
    (r'集中|注意|継続|持続|最後まで', '活動への参加を継続する'),
    (r'休憩|疲労|疲れ|自己調整|落ち着', '休憩と自己調整'),
    (r'読字|読む|読み|書字|書く|文字|計算|数|学習|タイピング', '読み書き・数量の基礎活動'),
    (r'運動|姿勢|身体|感覚|手先|指先|動作', '身体の動きや感覚への配慮'),
    (r'生活|身支度|着替え|片付け|自立|準備', '生活や身の回りの活動'),
)
METHOD_TAGS = (
    (r'視覚|絵カード|図|写真|手順表|タイマー|スケジュール', '視覚的な手順提示'),
    (r'短い指示|短く伝|一つずつ|簡潔', '短い段階的な説明'),
    (r'選択肢|二択|2択|自由選択', '選択肢の提示'),
    (r'休憩|休む|退出|無理をさせない', '休憩・途中退出の選択'),
    (r'個別|少人数|ペースに合わせ', '本人のペースへの配慮'),
    (r'意思|表出|伝える|非言語|ジェスチャー', '多様な意思表出方法の尊重'),
)
# Fixed-value fine-grained cues. No matched text or raw number is transmitted.
# These cues reflect staff support methods, not asserted facts about a child.
SPECIFIC_GOALS = (
    (r'(?:2|２|二)\s*択|二つ(?:の)?選択肢', '2択から本人が選ぶ'),
    (r'(?:3|３|三)\s*択|三つ(?:の)?選択肢', '3択から本人が選ぶ'),
    (r'指差し|指さし|指をさし', '指差しで希望を示す'),
    (r'ジェスチャー|身振り|手振り', '身振りによって意思を示す'),
    (r'言葉で伝える|口頭で伝える|口頭で答える', '言葉によって意思を示す'),
    (r'絵カード|イラストカード', '絵カードを使って意思を示す'),
    (r'文字盤|コミュニケーションボード', '文字盤を使って意思を示す'),
    (r'順番を待つ|順番待ち|交代する|順番を守る', '順番を待ち交代する場面を設ける'),
    (r'役割分担|役割を決める|役割を選ぶ', '役割を選択・分担する場面を設ける'),
    (r'困ったとき.*(?:助け|相談|伝え)|助けて.*(?:言う|伝え)', '困ったときに援助を求める'),
    (r'振り返り|感想を伝える|活動を振り返る', '活動の終了時に振り返る'),
    (r'ひらがな|かな入力', 'ひらがな・かな入力を用いた活動'),
    (r'ローマ字|英字入力', 'ローマ字・英字入力を用いた活動'),
    (r'キーボード|タイピング', 'キーボード入力を用いた活動'),
    (r'数量|数える|計算|足し算|引き算', '数量や計算を用いた活動'),
    (r'ひとりで準備|自分で準備|身支度', '自分で準備・身支度する機会を設ける'),
)
SPECIFIC_METHODS = (
    (r'タイマー|タイムタイマー', 'タイマーで時間の見通しを示す'),
    (r'手順表|工程表|スケジュール表', '手順表で工程を見える化する'),
    (r'一つずつ|ひとつずつ|1つずつ|一工程ずつ', '手順を一工程ずつ提示する'),
    (r'写真カード|写真を示す', '写真を手掛かりにして説明する'),
    (r'絵カード|イラストカード', '絵カードで手順や選択肢を示す'),
    (r'選択肢|(?:2|２|二)\s*択|(?:3|３|三)\s*択', '複数の選択肢を提示する'),
    (r'休憩|休む|途中退出', '休憩・途中退出を選べるようにする'),
    (r'雑音|騒音|静かな環境|刺激を減らす', '活動環境の刺激量を調整する'),
    (r'個別|少人数|本人のペース', '本人のペースや活動人数を調整する'),
    (r'視覚的|視覚化|見通し', '視覚的な見通しを提示する'),
)
# Contextual timing retains only one of a small set of activity-interval values.
INTERVALS = (5, 10, 15, 20, 30)
DOMAIN_KEYS = (
    ('domain_health','健康・生活'),
    ('domain_motor','運動・感覚'),
    ('domain_cognition','認知・行動'),
    ('domain_language','言語・コミュニケーション'),
    ('domain_social','人間関係・社会性'),
)
SCHOOL_CONTEXT_VALUES = {'学校の記載なし','学校A（小学校段階）','学校A（中学校段階）',
                         '学校A（高校段階）','学校A（校種非送信）'}
ROLE_CONTEXT = (
    (r'担任|教員|先生', '学校職員Aとの連携・やり取り'),
    (r'同級生|級友|友達|友だち', '同年代の仲間とのやり取り'),
    (r'保護者|母親|父親|家族', '保護者Aとの連絡・調整'),
)
SUPPORT_FIELDS_TO_EXTRACT = (
    'child_intentions','long_goal','short_goal','support_policy',
    'domain_health','domain_motor','domain_cognition','domain_language','domain_social',
    'accommodation',
)
ALLOW_DOMAINS = {label for _, label in DOMAIN_KEYS}
CLASS_SIZE_VALUES = {'個別活動','小集団活動','形態は現場で確認'}
ALLOWED = {
    'generic_objective_tags': {label for _,label in GOAL_TAGS},
    'generic_support_methods': {label for _,label in METHOD_TAGS},
    'relevant_domains': ALLOW_DOMAINS,
    'concrete_goal_cues': {label for _,label in SPECIFIC_GOALS},
    'concrete_support_cues': {label for _,label in SPECIFIC_METHODS} |
        {f'{i}分程度で区切り、活動の見通しを示す' for i in INTERVALS},
    'interaction_context': {label for _,label in ROLE_CONTEXT},
}


def _matched(source, rule):
    return [label for pattern, label in rule if re.search(pattern,source,re.I)]


def _school_context(source):
    """School names are never sent; only school-stage placeholders are emitted."""
    if not re.search(r'学校|在籍校|学園|高校|高等部|小学生|中学生',source):
        return '学校の記載なし'
    if re.search(r'特別支援|養護学校',source):
        return '学校A（校種非送信）'
    # Mixed school levels (e.g. in transition history) are not disambiguated.
    level = [
        (r'小学校|小学生|小学[一二三四五六1-6１-６]年', '学校A（小学校段階）'),
        (r'中学校|中学生|中学[一二三1-3１-３]年', '学校A（中学校段階）'),
        (r'高等学校|高校|高等部|高校生', '学校A（高校段階）'),
    ]
    found=[label for pattern,label in level if re.search(pattern,source)]
    return found[0] if len(found)==1 else '学校A（校種非送信）'


def _safe_intervals(source):
    # Only explicit descriptions about the timing of an activity are considered.
    # Never infer intervals from dates, school grade, addresses or age.
    found=[]
    for n in INTERVALS:
        p=rf'(?<!\d){n}分(?:ごと|おき|単位|程度|毎|間隔|ずつ|で区切|で切り替|で活動)'
        if re.search(p,source):
            found.append(f'{n}分程度で区切り、活動の見通しを示す')
    return found


def _extract_source(support):
    return '\n'.join(str(support.get(k,'') or '') for k in SUPPORT_FIELDS_TO_EXTRACT)


def build_minimal_payload(child, support, options):
    """Keep concrete safe support cues but never insert raw text into the payload.

    The caller's child, support and options are untrusted, potentially sensitive.
    The output is assembled exclusively from fixed strings and public catalog text.
    """
    if not isinstance(child,dict) or not isinstance(support,dict) or not isinstance(options,dict):
        raise ValueError('AI data mapping unavailable')
    mode=str(options.get('activity_mode',''))
    if mode not in ('minecraft','other'):
        raise ValueError('Invalid activity mode')
    try:
        duration=int(options.get('duration'))
    except (TypeError,ValueError):
        raise ValueError('Invalid activity duration')
    if not (15<=duration<=180):
        raise ValueError('Invalid activity duration')
    kind_code='minecraft' if mode=='minecraft' else str(options.get('kind_code',''))
    if mode=='other' and kind_code not in OTHER_KINDS:
        raise ValueError('Invalid public catalog code')
    label='Minecraft' if mode=='minecraft' else (OTHER_KINDS[kind_code] if kind_code!='other' else '自由活動（詳細は職員が確認）')
    group='デジタル創作・遊び' if mode=='minecraft' else KIND_GROUP[kind_code]
    focus='本人の意思・役割選択・協力を観察する' if mode=='minecraft' else CATEGORY_FOCUS[group]
    safe='既知でない相手とのオンライン接続を避ける' if mode=='minecraft' else (CATEGORY_SAFETY[group]+' '+EXTRA_SAFETY.get(kind_code,'')).strip()

    # Names, locations and raw notes are not copied into ANY outbound field.
    # Specific actions are selected only from closed, audited vocabularies.
    source=_extract_source(support)
    # School stage and interaction roles are derived, with all identities discarded.
    context='\n'.join([source,*[str(child.get(k,'') or '') for k in
                            ('grade','interests','strengths','needs','participation_notes')]])
    school=_school_context(context)
    form=str(options.get('group_size','') or '')
    group_form='個別活動' if re.search('個別',form) else ('小集団活動' if re.search('集団|グループ|複数',form) else '形態は現場で確認')

    return {
        'request_type':'contextual_activity_draft',
        'privacy_version':'controlled-context-2',
        'profile':{
            'subject':'児童A',
            'school_context':school,
            'identities':'本人・家族・職員の実名は非送信',
        },
        'support_context':{
            'has_registered_plan':bool(support),
            'generic_objective_tags':_matched(source,GOAL_TAGS),
            'generic_support_methods':_matched(source,METHOD_TAGS),
            'concrete_goal_cues':_matched(source,SPECIFIC_GOALS),
            'concrete_support_cues':_matched(source,SPECIFIC_METHODS)+_safe_intervals(source),
            'interaction_context':_matched(source,ROLE_CONTEXT),
            'relevant_domains':[label for key,label in DOMAIN_KEYS if str(support.get(key,'') or '').strip()],
            'verbatim_private_records':'非送信・職員が原文で照合',
        },
        'activity':{
            'activity_mode':mode,
            'kind_code':kind_code,
            'catalog_label':label,
            'catalog_group':group,
            'catalog_focus':focus,
            'catalog_safety':safe,
            'duration_minutes':duration,
            'group_form':group_form,
            'user_free_text':'非送信・職員がローカルで確認',
        },
    }


def check_minimal_payload(payload):
    """Fail closed: reject extra keys and any non-approved AI-bound text."""
    if not isinstance(payload,dict) or set(payload)!={'request_type','privacy_version','profile','support_context','activity'}:
        raise ValueError('AI payload schema mismatch')
    if (payload['request_type'],payload['privacy_version'])!=('contextual_activity_draft','controlled-context-2'):
        raise ValueError('AI payload version mismatch')
    profile=payload['profile']
    if not isinstance(profile,dict) or set(profile)!={'subject','school_context','identities'}:
        raise ValueError('Unexpected personal profile')
    if profile['subject']!='児童A' or profile['identities']!='本人・家族・職員の実名は非送信' or profile['school_context'] not in SCHOOL_CONTEXT_VALUES:
        raise ValueError('Personal identification risk')
    sup=payload['support_context']
    required={'has_registered_plan','generic_objective_tags','generic_support_methods',
              'concrete_goal_cues','concrete_support_cues','interaction_context',
              'relevant_domains','verbatim_private_records'}
    if not isinstance(sup,dict) or set(sup)!=required or type(sup['has_registered_plan']) is not bool or sup['verbatim_private_records']!='非送信・職員が原文で照合':
        raise ValueError('Raw support plan forbidden')
    for key,allow in ALLOWED.items():
        a=sup[key]
        if (not isinstance(a,list) or len(a)>25 or len(a)!=len(set(a)) or
            any(type(x) is not str or x not in allow for x in a)):
            raise ValueError('Unknown or duplicated support detail blocked: '+key)
    act=payload['activity']
    required_act={'activity_mode','kind_code','catalog_label','catalog_group','catalog_focus','catalog_safety',
                  'duration_minutes','group_form','user_free_text'}
    if not isinstance(act,dict) or set(act)!=required_act or type(act['duration_minutes']) is not int or not 15<=act['duration_minutes']<=180 or act['group_form'] not in CLASS_SIZE_VALUES or act['user_free_text']!='非送信・職員がローカルで確認':
        raise ValueError('Activity schema mismatch')
    control=build_minimal_payload({}, {}, {'activity_mode':act['activity_mode'],'kind_code':act['kind_code'],'duration':act['duration_minutes']})
    for key in ('activity_mode','kind_code','catalog_label','catalog_group','catalog_focus','catalog_safety'):
        if act[key]!=control['activity'][key]:
            raise ValueError('Unapproved activity label blocked')
    result=json.dumps(payload,ensure_ascii=False,separators=(',',':'))
    if len(result)>16000:
        raise ValueError('Unexpected payload size')
    return result
