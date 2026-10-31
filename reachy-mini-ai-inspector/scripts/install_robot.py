#!/usr/bin/env python3
"""Install only this app wheel via the official Wireless SSH development workflow."""
import argparse
import getpass
import os
from pathlib import Path
import secrets
import shlex

import paramiko


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--host',required=True)
    p.add_argument('--user',default='pollen')
    p.add_argument('--known-hosts',type=Path,default=Path.home()/'.ssh/known_hosts')
    p.add_argument('--wheel',type=Path,required=True)
    p.add_argument('--token-file',type=Path,required=True)
    p.add_argument('--factory-password',action='store_true',help='Use only when the owner explicitly authorizes the documented factory credential')
    args=p.parse_args()
    if not args.wheel.is_file() or args.wheel.suffix!='.whl':
        p.error('Built wheel is required')
    client=paramiko.SSHClient()
    client.load_host_keys(str(args.known_hosts.expanduser()))
    password='root' if args.factory_password else getpass.getpass('Reachy SSH password: ')
    client.connect(args.host,username=args.user,password=password,look_for_keys=False,allow_agent=False,timeout=8)
    try:
        def run(command):
            _,out,err=client.exec_command(command,timeout=120)
            stdout=out.read().decode();stderr=err.read().decode()
            code=out.channel.recv_exit_status()
            if code: raise RuntimeError(f'Remote command failed ({code}): {stderr or stdout}')
            return stdout.strip()
        check='import importlib.metadata as m; from PIL import Image; import fastapi, uvicorn; assert m.version("reachy-mini")=="1.12.0"; print("SDK and dependencies verified")'
        print(run('/venvs/apps_venv/bin/python -c '+shlex.quote(check)))
        home=run('pwd')
        remote=home+'/reachy-mini-ai-inspector'
        config=home+'/.config/reachy-mini-ai-inspector'
        run('mkdir -p '+shlex.quote(remote)+' '+shlex.quote(config))
        run('chmod 700 '+shlex.quote(config))
        with client.open_sftp() as sftp:
            remote_token=config+'/token'
            try:
                with sftp.open(remote_token) as f: token=f.read().decode().strip()
            except FileNotFoundError:
                token=secrets.token_urlsafe(32)
                with sftp.open(remote_token,'w') as f: f.write(token+'\n')
                sftp.chmod(remote_token,0o600)
            local=args.token_file.expanduser()
            local.parent.mkdir(parents=True,exist_ok=True)
            if local.exists() and local.read_text().strip()!=token:
                raise RuntimeError('Local token exists and differs; use a different token-file path')
            fd=os.open(local,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
            with os.fdopen(fd,'w') as f: f.write(token+'\n')
            os.chmod(local,0o600)
            target=remote+'/'+args.wheel.name
            sftp.put(str(args.wheel),target)
        # Existing shared SDK/daemon dependencies are left intact.
        print(run('/venvs/apps_venv/bin/python -m pip install --no-index --disable-pip-version-check --no-deps --upgrade --force-reinstall '+shlex.quote(target)))
        ep='from importlib.metadata import entry_points; print([e.name for e in entry_points(group="reachy_mini_apps") if e.name=="reachy_mini_ai_inspector"])'
        print(run('/venvs/apps_venv/bin/python -c '+shlex.quote(ep)))
        print('Installed. Open Reachy Mini Control > Applications to start the app. Motion defaults OFF.')
        print('Pairing token saved locally (contents hidden): '+str(local))
    finally:
        client.close()


if __name__=='__main__':
    main()
