"""v2.8 field attribution tests: fictional text only and temporary encrypted DB."""
import os
import re
import sys
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from text_import import parse_support_text

source = '''個別支援計画書
児童氏名：架空 花子
事業所名：架空デイサービス
本人の意向：友達と遊びたい
保護者の希望：自分で準備ができるようになってほしい
現在の状況：集団場面では声かけが必要
総合的な支援の方針
安心できる環境で本人の選択を尊重する
長期目標（6か月）：友達と協力して活動する
長期目標：友達と協力して活動する
短期目標
順番を守って気持ちを伝える
作成日：2026年11月17日
| 区分 | 領域 | 具体的な支援内容 |
| 本人支援 | 健康・生活 | 活動前に手洗いをする |
| 本人支援 | 運動・感覚 | 姿勢を調整する |
| 本人支援 | 認知・行動 | 手順カードで見通しを持つ |
| 本人支援 | 言語・コミュニケーション | 希望を言葉で伝える |
| 本人支援 | 人間関係・社会性 | 友達と順番を守る |
合理的配慮：静かな場所で休憩できるようにする
家族支援
家庭と連絡帳で情報を共有する
移行支援：進学に向けて関係者と相談する
地域支援・地域連携：地域活動に参加する
計画開始日：2026年11月1日
計画終了日：2027/4/30
'''
f, count, warnings, names = parse_support_text(source)
assert names == ['架空 花子']
assert f['long_goal'] == '友達と協力して活動する', f['long_goal']
assert f['short_goal'] == '順番を守って気持ちを伝える', f['short_goal']
assert f['child_intentions'] == '友達と遊びたい'
assert f['family_intentions'] == '自分で準備ができるようになってほしい'
assert f['support_policy'] == '安心できる環境で本人の選択を尊重する'
assert f['domain_health'] == '活動前に手洗いをする', f['domain_health']
assert f['domain_motor'] == '姿勢を調整する'
assert f['domain_cognition'] == '手順カードで見通しを持つ'
assert f['domain_language'] == '希望を言葉で伝える'
assert f['domain_social'] == '友達と順番を守る'
assert f['family_support'] == '家庭と連絡帳で情報を共有する'
assert f['transition_support'] == '進学に向けて関係者と相談する'
assert f['community_support'] == '地域活動に参加する'
assert f['period_start'] == '2026-11-01'
assert f['period_end'] == '2027-04-30'
assert '作成日' not in f['short_goal']
assert '事業所名' not in f['child_intentions']
assert f['original_text'] == source.strip()
assert count >= 16

# Do not infer fields from unlabeled prose; don't merge metadata into the previous field.
unlabelled = 'みんなで活動しながら長期目標を考えています。\n本人の状況をまとめた文章です。'
empty, n, _, _ = parse_support_text(unlabelled)
assert n == 0 and empty == {'original_text':unlabelled}
separate, _, _, _ = parse_support_text('長期目標：協力する\n担当者：架空A\n次回面談：調整中\n短期目標：挨拶する')
assert separate['long_goal'] == '協力する', separate
assert separate['short_goal'] == '挨拶する', separate
bad_date, _, warn, _ = parse_support_text('計画開始日：2026年15月90日')
assert 'period_start' not in bad_date and any('日付' in w for w in warn)

with tempfile.TemporaryDirectory(prefix='ryoiku_v28_parser_test_') as temp:
    os.environ['APP_SECRET'] = 's' * 64
    os.environ['DATA_ENCRYPTION_KEY'] = Fernet.generate_key().decode()
    os.environ['APP_DB_PATH'] = str(Path(temp) / 'data.sqlite3')
    os.environ['APP_LOG_DIR'] = str(Path(temp) / 'logs')
    from fastapi.testclient import TestClient
    from app import app
    from storage import create_user, support_history

    def csrf(page):
        match = re.search(r'name="_csrf" value="([^\"]+)"', page.text)
        assert match, page.text[:450]
        return match.group(1)

    with TestClient(app) as client:
        create_user('demo_staff', 'TempPassword123456!', 'admin')
        not_logged_in = client.get('/children/1/support/new', follow_redirects=False)
        assert not_logged_in.status_code == 303
        login = client.get('/login')
        assert client.post('/login', data={'_csrf':csrf(login),'username':'demo_staff',
            'password':'TempPassword123456!'}, follow_redirects=False).status_code == 303
        page = client.get('/children/new')
        assert client.post('/children/new', data={'_csrf':csrf(page),'code':'DEMO28',
            'name':'架空 花子'}, follow_redirects=False).status_code == 303
        form = client.get('/children/1/support/new')
        assert '/children/1/support/analyze' in form.text
        bad = client.post('/children/1/support/analyze', data={'_csrf':'bad','source_text':source})
        assert bad.status_code == 403
        oversized = client.post('/children/1/support/analyze',data={'_csrf':csrf(form),'source_text':'あ'*18001})
        assert oversized.status_code == 200 and '18,000文字以下' in oversized.text
        before = support_history(1)
        preview = client.post('/children/1/support/analyze',
            data={'_csrf':csrf(form),'source_text':source})
        assert preview.status_code == 200, preview.text[:400]
        assert '原文からの転記候補' in preview.text
        assert '友達と協力して活動する' in preview.text
        assert '活動前に手洗いをする' in preview.text
        assert support_history(1) == before
        token_match = re.search(r'name="ocr_preview_token" value="([^\"]+)"',preview.text)
        assert token_match
        pending_token = token_match.group(1)
        fields = {'_csrf':csrf(preview),'ocr_preview_token':pending_token,
                  'long_goal':f['long_goal'],'short_goal':f['short_goal'],
                  'original_text':source}
        no_verification = client.post('/children/1/support/new',data=fields)
        assert no_verification.status_code == 200
        assert support_history(1) == before
        fields['ocr_verified'] = 'yes'
        missing_review = client.post('/children/1/support/new',data=fields)
        assert missing_review.status_code == 200 and '照合' in missing_review.text
        fields.update({'review_child_intentions':'yes','review_family_intentions':'yes','review_assessment':'yes'})
        saved = client.post('/children/1/support/new',data=fields,follow_redirects=False)
        assert saved.status_code == 303
        assert len(support_history(1)) == 1
        db = Path(os.environ['APP_DB_PATH']).read_bytes()
        assert '友達と協力して活動する'.encode() not in db
        assert '本人の意向'.encode() not in db
        for log in Path(temp,'logs').glob('*.csv'):
            logtext = log.read_text(encoding='utf-8')
            assert '架空 花子' not in logtext and '友達と協力' not in logtext
print('PASS: v2.8 Japanese text field attribution, 5 domains, table rows, safety and UI review')
