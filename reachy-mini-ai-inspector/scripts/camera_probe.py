#!/usr/bin/env python3
"""Read-only official SDK remote-stream comparison; never commands a motion."""
import argparse
from pathlib import Path
import time
from PIL import Image
from reachy_mini import ReachyMini
p=argparse.ArgumentParser();p.add_argument('--host',required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
with ReachyMini(host=args.host,connection_mode='network',automatic_body_yaw=False,timeout=6,media_backend='default') as mini:
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        frame=mini.media.get_frame()
        if frame is not None:
            args.output.parent.mkdir(parents=True,exist_ok=True)
            Image.fromarray(frame[:,:,::-1]).save(args.output)
            print(f'Camera frame saved: {frame.shape[1]} x {frame.shape[0]} / {args.output}')
            break
        time.sleep(.1)
    else: raise RuntimeError('Camera frame not received within 15 seconds')
