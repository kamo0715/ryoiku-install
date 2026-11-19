"""Check the application rejects out-of-LAN clients and forged HTTP Host headers."""
import asyncio,os,tempfile,subprocess,sys,socket,ipaddress,pathlib
ROOT=pathlib.Path(__file__).resolve().parents[1]
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.connect(('192.0.2.1',9));local=s.getsockname()[0];s.close()
env={**os.environ,'LAN_BIND_IP':local,'LAN_ALLOWED_CIDR':str(ipaddress.ip_network(local+'/24',strict=False)),
     'RYOIKU_PORT':'19172','RYOIKU_DATA_DIR':'','PYTHONPATH':os.pathsep.join([str(ROOT/'docker'),str(ROOT/'upload_to_domain_root/_private/app'),str(ROOT/'upload_to_domain_root/_private/vendor')])}

with tempfile.TemporaryDirectory() as temp:
    env['RYOIKU_DATA_DIR']=temp
    test='''import asyncio,server,sys
async def req(source,host):
  out=[]
  async def recv(): return {'type':'http.request','body':b'','more_body':False}
  async def send(event):out.append(event)
  scope={'type':'http','method':'GET','path':'/healthz','headers':[(b'host',host.encode())], 'client':(source,12345)}
  await server.application(scope,recv,send)
  return out[0]['status']
async def main():
 assert await req('8.8.8.8',f'{server.BIND_IP}:{server.PORT}')==403
 assert await req('127.0.0.1',f'{server.BIND_IP}:{server.PORT}')==403
 assert await req(str(server.BIND_IP),'evil.com')==400
 assert await req(str(server.BIND_IP),f'{server.BIND_IP}:{server.PORT}')==200
 print('PASS LAN access guard and Host restriction')
asyncio.run(main())
'''
    result=subprocess.run([sys.executable,'-c',test],env=env,text=True,capture_output=True)
    print(result.stdout.strip())
    if result.returncode:
        print(result.stderr,file=sys.stderr)
    assert result.returncode==0