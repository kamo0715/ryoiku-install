"""Local non-Docker smoke test, uses a synthetic RFC1918 network and throwaway DB."""
import os,sys,tempfile,pathlib,subprocess,time,socket,urllib.request,urllib.parse,http.cookiejar,re,sqlite3
from contextlib import suppress
ROOT=pathlib.Path(__file__).resolve().parents[1]
APP=ROOT/'upload_to_domain_root/_private/app'
VENDOR=ROOT/'upload_to_domain_root/_private/vendor'
RUNTIME=ROOT/'docker'
# Detect one host-private test IPv4; no outbound network request.
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.connect(('192.0.2.1',9));IP=s.getsockname()[0];s.close()
assert IP.startswith(('10.','172.','192.168.'))
port=19171
env={**os.environ,'LAN_BIND_IP':IP,'LAN_ALLOWED_CIDR':str(__import__('ipaddress').ip_network(IP+'/24',strict=False)),'RYOIKU_PORT':str(port),'PYTHONPATH':os.pathsep.join(map(str,(APP,VENDOR,RUNTIME))),'RYOIKU_DATA_DIR':''}
with tempfile.TemporaryDirectory() as td:
    env['RYOIKU_DATA_DIR']=td
    p=subprocess.Popen([sys.executable,str(RUNTIME/'server.py')],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    try:
        base=f'http://{IP}:{port}'
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        for i in range(80):
            try:
                with opener.open(base+'/healthz',timeout=1) as r:
                    assert r.status==200
                    break
            except Exception:
                if p.poll() is not None:raise RuntimeError('Process terminated: '+p.stdout.read())
                time.sleep(.1)
        else: raise RuntimeError('Server did not start')
        with opener.open(base+'/first-setup') as r:
            html=r.read().decode('utf-8');assert '初回管理者登録' in html
        code=(pathlib.Path(td)/'INITIAL_ADMIN_CODE.txt').read_text().strip()
        assert len(code)>48
        data=urllib.parse.urlencode({'token':code,'username':'test_admin','password':'strongTestPass2026*','confirm':'strongTestPass2026*'}).encode()
        with opener.open(base+'/first-setup',data=data,timeout=10) as r:
            assert r.url.endswith('/login'),r.url
            assert 'ryoiku_session' in r.headers.get('set-cookie','') or r.status==200
        assert not (pathlib.Path(td)/'INITIAL_ADMIN_CODE.txt').exists()
        with sqlite3.connect(pathlib.Path(td)/'ryoiku.sqlite3') as c:
            assert c.execute('select count(*) from users').fetchone()[0]==1
        with opener.open(base+'/login') as r:
            page=r.read().decode('utf-8'); assert 'ログイン' in page
            csrf_match=re.search(r'name="_csrf"\s+value="([^"]+)"',page)
            if not csrf_match:
                csrf_match=re.search(r'value="([^"]+)"\s+name="_csrf"',page)
            assert csrf_match,'csrf field not found'
            data=urllib.parse.urlencode({'username':'test_admin','password':'strongTestPass2026*','_csrf':csrf_match.group(1)}).encode()
        with opener.open(base+'/login',data=data,timeout=15) as r:
            assert r.status==200
            page=r.read().decode('utf-8');assert '利用者' in page or '支援' in page
        with opener.open(base+'/static/day_flow_multi.js') as r:assert r.status==200 and len(r.read())>500
        with opener.open(base+'/healthz') as r:assert r.status==200
        # Request with a forged forward header must not override the actual source IP.
        req=urllib.request.Request(base+'/healthz',headers={'X-Forwarded-For':'8.8.8.8'})
        with opener.open(req) as r:assert r.status==200
        print('PASS smoke: server, local network, bootstrap, login, assets, persistence files')
    finally:
        p.terminate()
        try:p.communicate(timeout=5)
        except subprocess.TimeoutExpired:p.kill();p.communicate()