#!/usr/bin/env python3
"""Synthetic regression ONLY. Never evidence of real LEGO accuracy."""
from collections import Counter
import json
from pathlib import Path
from reachy_mini_ai_inspector.providers import demo_image, encode, decode
from reachy_mini_ai_inspector.settings import Settings
from reachy_mini_ai_inspector.vision import extract, AnomalyModel
s=Settings();refs=[]
for seed in range(100,112):
    image=decode(encode(demo_image('red24',seed)))
    f,_,_=extract(image,s);refs.append({'features':f.tolist()})
model=AnomalyModel(refs,s.profile());summary={}
for scene,expected in [('red24','OK'),('blue24','NG'),('red28','NG'),('empty','REVIEW'),('blur','REVIEW')]:
    results=[model.predict(decode(encode(demo_image(scene,seed))),s) for seed in range(1000,1030)]
    summary[scene]={'expected':expected,'count':30,'counts':dict(Counter(r['verdict'] for r in results)),
                    'ai_executed':sum(r['ai_executed'] for r in results)}
report={'dataset':'SYNTHETIC ONLY - not real hardware validation','training':12,'test':150,'results':summary}
path=Path(__file__).resolve().parents[1]/'doc'/'synthetic-evaluation.json'
path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2))
assert all(v['counts'].get(v['expected'])==30 for v in summary.values())
