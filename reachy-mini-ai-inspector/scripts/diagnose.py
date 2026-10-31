#!/usr/bin/env python3
"""Read-only daemon identification. Never treats the Mac IP as the robot."""
import argparse
import json
import socket
import httpx
p=argparse.ArgumentParser();p.add_argument('--host',required=True);args=p.parse_args()
try:
    with httpx.Client(trust_env=False,timeout=4) as c:
        r=c.get(f'http://{args.host}:8000/api/daemon/status');r.raise_for_status();s=r.json()
        output={k:s.get(k) for k in ('state','wireless_version','simulation_enabled','version','wlan_ip')}
        output['robot_confirmed']=s.get('wireless_version') is True and s.get('simulation_enabled') is False
        print(json.dumps(output,ensure_ascii=False,indent=2))
        raise SystemExit(0 if output['robot_confirmed'] else 2)
except (httpx.HTTPError,ValueError) as e:
    print('Reachy確認に失敗:',str(e));raise SystemExit(1)
