"""Fictional LITALICO-like support-plan transcription and false attribution tests.

Not an official LITALICO sample; no actual child's records in this suite.
"""
import os,sys,re,tempfile
from pathlib import Path
from cryptography.fernet import Fernet
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from text_import import parse_support_text

EXAMPLES = [
('combined labelled', '''個別支援計画書
利用児及び家族の生活に対する意向
本人：マインクラフトで建物を作りたい
保護者：お友達に気持ちを伝えられるようになってほしい
総合的な支援の方針：本人が選べるようにする
アセスメント
教室の予定変更時には声かけが必要
強み:レゴの組み立てが得意
長期目標：友達と活動できる
''', {'child_intentions':'マインクラフトで建物を作りたい','family_intentions':'お友達に気持ちを伝えられるようになってほしい','assessment':'教室の予定変更時には声かけが必要\n強み:レゴの組み立てが得意'}),
('combined one line', '利用児及び家族の生活に対する意向：本人：絵を描きたい　保護者：生活リズムを整えたい\n現状と課題：活動の切替に声かけが必要', {'child_intentions':'絵を描きたい','family_intentions':'生活リズムを整えたい','assessment':'活動の切替に声かけが必要'}),
('two-column table', '利用児及び家族の生活に対する意向\n| 本人の希望 | 保護者の希望 |\n| 音楽がしたい | 順番を守ってほしい |\nアセスメント・現在の状況：タイマーの合図を理解できる',{'child_intentions':'音楽がしたい','family_intentions':'順番を守ってほしい','assessment':'タイマーの合図を理解できる'}),
('explicit display aliases', '本人の希望・意思：一人で絵本を読みたい\n保護者・家族の意向：朝の準備ができるようになってほしい\n得意なこと:パズルを最後まで完成させられる',{'child_intentions':'一人で絵本を読みたい','family_intentions':'朝の準備ができるようになってほしい','assessment':'得意なこと:パズルを最後まで完成させられる'}),
('split headings', '本人の意向\n電車を見に行きたい\n保護者の意向\n身支度を練習してほしい\n現在の様子\n片付けには絵カードを使う',{'child_intentions':'電車を見に行きたい','family_intentions':'身支度を練習してほしい','assessment':'片付けには絵カードを使う'}),
]
for name,source,expected in EXAMPLES:
    fields,count,warnings,names=parse_support_text(source)
    for key,value in expected.items():
        assert fields.get(key)==value,(name,key,fields.get(key),value)
    assert fields['original_text']==source.strip(),name

# Ambiguous combined column: no claim about which speaker said it.
amb='利用児及び家族の生活に対する意向\nみんなで遊べるようになりたい'
f,count,w,_=parse_support_text(amb)
assert 'child_intentions' not in f and 'family_intentions' not in f, f
assert any('発言者' in m for m in w),w
# A parent's support program isn't parent's *intention*. Contextual prose never supplies an opinion.
f,_,_,_=parse_support_text('家族支援：保護者へ連絡帳で連絡する\n本人の状況をまとめた文章です。\n本人支援：感覚に配慮する')
assert 'family_intentions' not in f and 'child_intentions' not in f, f
assert 'assessment' not in f, f
# No inventing assessment from the stated intentions or goals.
f,_,warn,_=parse_support_text('本人の意向：水族館へ行きたい\n保護者の意向：声かけなしで準備してほしい\n長期目標：友達と遊ぶ')
assert 'assessment' not in f and any('アセスメント' in w for w in warn),f

# Staff must explicitly confirm all three separately before saving OCR suggestions.
with tempfile.TemporaryDirectory(prefix='ryoiku_v29_test_') as tmp:
    os.environ['APP_SECRET']='l'*64
    os.environ['DATA_ENCRYPTION_KEY']=Fernet.generate_key().decode()
    os.environ['APP_DB_PATH']=str(Path(tmp)/'db.sqlite3')
    os.environ['APP_LOG_DIR']=str(Path(tmp)/'logs')
    from fastapi.testclient import TestClient
    from app import app
    from storage import create_user,support_history
    def csrf(response):
        m=re.search(r'name="_csrf" value="([^"]+)"',response.text)
        assert m
        return m.group(1)
    with TestClient(app) as client:
        create_user('test_staff29','TestPasswordOnly123!','admin')
        login=client.get('/login')
        assert client.post('/login',data={'_csrf':csrf(login),'username':'test_staff29','password':'TestPasswordOnly123!'},follow_redirects=False).status_code==303
        page=client.get('/children/new')
        assert client.post('/children/new',data={'_csrf':csrf(page),'code':'SYNTH29','name':'架空 児童'},follow_redirects=False).status_code==303
        page=client.get('/children/1/support/new')
        response=client.post('/children/1/support/analyze',data={'_csrf':csrf(page),'source_text':EXAMPLES[0][1]})
        assert response.status_code==200
        for checkbox in ['review_child_intentions','review_family_intentions','review_assessment']:
            assert f'name="{checkbox}"' in response.text
        assert 'レゴの組み立て' in response.text and 'お友達に気持ちを' in response.text
        token=re.search(r'name="ocr_preview_token" value="([^"]+)"',response.text).group(1)
        data={'_csrf':csrf(response),'ocr_preview_token':token,'ocr_verified':'yes','child_intentions':'マインクラフトで建物を作りたい','family_intentions':'お友達に気持ちを伝えられるようになってほしい','assessment':'教室の予定変更時には声かけが必要'}
        assert not support_history(1)
        for key in ['review_child_intentions','review_family_intentions','review_assessment']:
            partial=dict(data)
            for checked in ['review_child_intentions','review_family_intentions','review_assessment']:
                if checked!=key:partial[checked]='yes'
            blocked=client.post('/children/1/support/new',data=partial,follow_redirects=False)
            assert blocked.status_code==200,(key,blocked.status_code)
            assert not support_history(1)
        data.update({k:'yes' for k in ['review_child_intentions','review_family_intentions','review_assessment']})
        saved=client.post('/children/1/support/new',data=data,follow_redirects=False)
        assert saved.status_code==303,saved.text[:100]
        assert len(support_history(1))==1
        for log in Path(tmp,'logs').glob('*.csv'):
            assert 'マインクラフトで建物を作りたい' not in log.read_text(),log
print('PASS: v2.9 combined intentions, separate speaker columns, observation fields, uncertain text, mandatory three-way staff review')
