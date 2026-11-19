#!/usr/bin/env bash
# Safe interactive/local-only helper for an Ubuntu Linux Docker host.
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
for tool in ip awk python3 docker; do command -v "$tool" >/dev/null || { echo "Missing: $tool" >&2; exit 1; }; done
docker compose version >/dev/null || { echo 'Docker Compose plugin is required.' >&2; exit 1; }
if [[ -f .env ]]; then
  echo 'The existing .env was not overwritten.'
else
  netif="$(ip -4 route show default | awk 'NR==1{for(i=1;i<=NF;i++)if($i=="dev")print $(i+1)}')"
  [[ -n "$netif" ]] || { echo 'No default IPv4 interface detected. Configure .env manually.' >&2; exit 1; }
  ipcidr="$(ip -o -4 addr show dev "$netif" scope global | awk 'NR==1{print $4}')"
  [[ -n "$ipcidr" ]] || { echo 'No IPv4 on LAN interface. Configure .env manually.' >&2; exit 1; }
  LAN_BIND_IP="${ipcidr%/*}" LAN_NET="${ipcidr}" python3 - <<'PY'
import os,ipaddress,sys
ip=ipaddress.ip_address(os.environ['LAN_BIND_IP']); net=ipaddress.ip_interface(os.environ['LAN_NET']).network
rfc=[ipaddress.ip_network(x) for x in ['10.0.0.0/8','172.16.0.0/12','192.168.0.0/16']]
if not any(net.subnet_of(n) for n in rfc) or net.prefixlen < 16:
    print('Detected network is not safe private IPv4; set a narrower local CIDR manually.',file=sys.stderr);sys.exit(1)
with open('.env','x',encoding='utf-8') as f:
    f.write(f'LAN_BIND_IP={ip}\nLAN_ALLOWED_CIDR={net}\nRYOIKU_PORT=18080\n')
print(f'LAN_BIND_IP={ip} / LAN_ALLOWED_CIDR={net}')
PY
  chmod 600 .env
fi
python3 - <<'PY'
from pathlib import Path
import ipaddress,re
vals={k:v for line in Path('.env').read_text().splitlines() if '=' in line and not line.startswith('#') for k,v in [line.split('=',1)]}
ip=ipaddress.IPv4Address(vals.get('LAN_BIND_IP',''))
net=ipaddress.ip_network(vals.get('LAN_ALLOWED_CIDR',''),strict=True)
rfc=[ipaddress.ip_network(x) for x in ['10.0.0.0/8','172.16.0.0/12','192.168.0.0/16']]
assert net.prefixlen>=16 and ip in net and any(net.subnet_of(x) for x in rfc), 'Invalid private LAN scope'
assert 1024 <= int(vals.get('RYOIKU_PORT','18080')) <= 65535
print(f'Binding only to {ip}:{vals.get("RYOIKU_PORT","18080")}, allowed sources {net}')
PY
echo 'Building the v2.20 Docker image before removing anything...'
docker compose build
printf '\nKnown Ryoiku container removal candidates:\n'
./remove-old-ryoiku.sh --check
printf '\nRemoving only verified old Ryoiku application containers...\n'
./remove-old-ryoiku.sh --remove
echo 'Starting the isolated LAN-only test service...'
docker compose up -d --no-build
bind_ip="$(sed -n 's/^LAN_BIND_IP=//p' .env | head -1)"
port="$(sed -n 's/^RYOIKU_PORT=//p' .env | head -1)";port="${port:-18080}"
echo "Test URL: http://${bind_ip}:${port}/first-setup"
echo 'First registration code (show only in a private terminal):'
echo '  docker compose exec -T ryoiku cat /data/INITIAL_ADMIN_CODE.txt'
echo 'Do not port-forward this host port on your router, and do not enter real child data on HTTP.'