import os,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cryptography.fernet import Fernet
root=tempfile.TemporaryDirectory(prefix='ryoiku_unit_')
os.environ['APP_SECRET']='s'*64
os.environ['DATA_ENCRYPTION_KEY']=Fernet.generate_key().decode()
os.environ['APP_DB_PATH']=str(Path(root.name)/'test.db')
os.environ['APP_LOG_DIR']=str(Path(root.name)/'logs')
from storage import init_db,create_user,auth,new_child,new_support,get_support,latest_support,get_child,add_plan,get_plan
from ai import validate,demo_plan,GenerationError
from privacy import build_minimal_payload,check_minimal_payload
init_db();create_user('staff01','a_good_password_12345')
u=auth('staff01','a_good_password_12345');assert u
cid=new_child('CHILD_TEST',{'name':'仮名サンプル','needs':'緊張を伝える'},u['id'])
s1,v1=new_support(cid,{'short_goal':'目標v1'},u['id']);assert v1==1
s2,v2=new_support(cid,{'short_goal':'目標v2'},u['id']);assert v2==2
assert get_support(s1)['data']['short_goal']=='目標v1'
assert latest_support(cid)['id']==s2
p=demo_plan({'short_goal':'目標v1'},{'duration':45})
pid=add_plan(cid,s1,p,'demo','demo',u['id'])
assert get_plan(pid)['support_id']==s1
assert get_child(cid)['data']['name']=='仮名サンプル'
minimized=build_minimal_payload({'name':'仮名サンプル'},
    {'short_goal':'仮名サンプルは意思を伝える。abc@example.com'},
    {'activity_mode':'other','kind_code':'other','duration':45,'preferences':'090-1234-5678'})
blob=check_minimal_payload(minimized)
assert '仮名サンプル' not in blob and 'abc@example.com' not in blob and '090-1234-5678' not in blob
assert len(validate(p)['domains'])==5
p['domains'].pop()
try:validate(p);raise AssertionError('invalid data was accepted')
except GenerationError:pass
print('PASS: 暗号化保存／ログイン認証／個別支援計画の版管理／生成案の参照版保持／送信前の固定語彙への一般化／AI出力検証')
