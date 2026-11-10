"""The instructor explicitly released these 515 inputs and seeds for practice."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import random
import shutil
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from roboroute.dataset import load_dataset,write_dataset
from roboroute.generator import generate_map,generate_queries
from tools.reference_solver import solve_dataset
from tools.stress_dataset import flat_answers,components

FAMILIES=('open','detour','maze','disconnected','mixed')
LABELS=dict(open='開放型',detour='迂回型',maze='迷路・部屋型',disconnected='分断型',mixed='混合型')
PACK=ROOT/'datasets/final_practice'
INPUTS=('map.csv','queries.csv','metadata.json')
PROFILE='public-final-practice'


def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identity(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def save(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def build(recipe):
    """Same input generator, with the released per-map reproducible recipe."""
    rng=random.Random(recipe['seed'])
    family,w,h,n=(recipe[k] for k in ('family','width','height','queries'))
    if family=='detour':
        grid=[[0]*w for _ in range(h)]
        walls=rng.randint(2,5)
        for i in range(1,walls+1):
            x=w*i//(walls+1)+rng.randint(-2,2)
            gap=rng.randint(2,max(3,h//8))
            for y in range(gap if i%2 else 0,h if i%2 else h-gap): grid[y][x]=1
        if rng.random()<.5: grid.reverse()
    else:
        kind={'open':'open','labyrinth':rng.choice(('maze','rooms')),
              'disconnected':'open','mixed':rng.choice(('random','rooms','open'))}[family]
        grid=generate_map(w,h,kind,rng)
        if family=='open':
            for _ in range(rng.randrange(max(1,w*h//25))): grid[rng.randrange(h)][rng.randrange(w)]=1
        if family=='disconnected':
            x=rng.randrange(w//3,w*2//3)
            for row in grid: row[x]=1
            if rng.random()<.5: grid[rng.randrange(h//3,h*2//3)]=[1]*w
    kind=rng.choice(('random','repeated_goal','repeated_start','mixed'))
    queries=generate_queries(grid,n,kind,rng)
    _,groups=components(grid)
    groups=sorted(groups,key=len,reverse=True)
    free=[point for group in groups for point in group]
    start=rng.choice(free);queries[0]=(*start,*start)
    if family=='disconnected' and len(groups)>1:
        for index in range(1,max(2,n*2//5)):
            a,b=rng.sample(groups[:min(4,len(groups))],2)
            queries[index]=(*rng.choice(a),*rng.choice(b))
    return grid,queries


def materialize(path,recipe):
    grid,queries=build(recipe)
    write_dataset(path,grid,queries,recipe['seed'])
    metadata=json.loads((path/'metadata.json').read_text());metadata.pop('seed')
    save(path/'metadata.json',metadata)
    return load_dataset(path)


def verify(pack=PACK,*,full=False):
    pack=Path(pack)
    manifest=json.loads((pack/'manifest.json').read_text())
    if (manifest.get('schema_version')!=2 or manifest.get('profile')!=PROFILE or manifest.get('official_score') is not False
            or manifest.get('dataset_id')!=identity({k:v for k,v in manifest.items() if k!='dataset_id'})
            or manifest.get('maps_per_family')!=103 or manifest.get('origin')!='released-contest-inputs'
            or type(manifest.get('released_seed')) is not int):
        raise ValueError('公開済み515枚のmanifestが不正です。')
    records=manifest.get('maps')
    if not isinstance(records,list) or len(records)!=515 or any(not isinstance(r,dict) for r in records):
        raise ValueError('公開済み515枚の構成が不正です。')
    names=[r.get('name') for r in records]
    expected=[family+('' if index==0 else f'-{index:03d}') for index in range(103) for family in FAMILIES]
    if (names!=expected or manifest.get('schedule')!=expected or
            any(sum(r.get('family')==family for r in records)!=103 for family in FAMILIES)):
        raise ValueError('各種類103枚の構成または公開練習用の巡回順が不正です。')
    for record in records:
        recipe=record.get('recipe')
        if (not isinstance(recipe,dict) or set(recipe)!={'family','width','height','queries','seed'}
                or type(recipe['seed']) is not int
                or ('maze' if recipe['family']=='labyrinth' else recipe['family'])!=record['family']):
            raise ValueError('再生成用の公開設定が不正です。')
        path=pack/record['name']
        if path.is_symlink() or any((path/name).is_symlink() for name in (*INPUTS,'answers.json')):
            raise ValueError('練習データにリンクは使用できません。')
        if ({name:digest(path/name) for name in INPUTS}!=record['sha256'] or digest(path/'answers.json')!=record['answers_sha256']):
            raise ValueError('入力または正解のハッシュが一致しません: '+record['name'])
        dataset=load_dataset(path)
        answers=json.loads((path/'answers.json').read_text())
        if (not isinstance(answers,list) or len(answers)!=len(dataset.queries)
                or any(type(v) is not int or not -1<=v<dataset.width*dataset.height for v in answers)):
            raise ValueError('公開練習用の正解が不正です。')
        if full:
            if answers!=solve_dataset(dataset) or answers!=flat_answers(dataset):
                raise ValueError('独立した2種類の正解計算が一致しません。')
            with tempfile.TemporaryDirectory(prefix='rr-final-rebuild-') as temporary:
                rebuilt=Path(temporary)/'map';materialize(rebuilt,recipe)
                if {name:digest(rebuilt/name) for name in INPUTS}!=record['sha256']:
                    raise ValueError('公開seed・設定によるbyte一致再生成に失敗しました。')
    return manifest


def selected(pack=PACK,family='all'):
    if family not in ('all',*FAMILIES): raise ValueError('不正な地図の種類です。')
    manifest=verify(pack)
    records=[r for r in manifest['maps'] if family=='all' or r['family']==family]
    return manifest,[(r,Path(pack)/r['name'],json.loads((Path(pack)/r['name']/'answers.json').read_text())) for r in records]


def generate(output):
    """Rebuild the released inputs using their recipes, retaining verified answers."""
    manifest=verify(PACK)
    output=Path(output).absolute();output.mkdir(parents=True)
    for record in manifest['maps']:
        path=output/record['name'];materialize(path,record['recipe'])
        if {name:digest(path/name) for name in INPUTS}!=record['sha256']:
            raise ValueError('公開済みデータと再生成データが一致しません。')
        shutil.copyfile(PACK/record['name']/'answers.json',path/'answers.json')
    save(output/'manifest.json',manifest)
    verify(output)
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    creator=commands.add_parser('generate');creator.add_argument('--output',type=Path,required=True)
    validator=commands.add_parser('verify');validator.add_argument('--dataset',type=Path,default=PACK)
    validator.add_argument('--full',action='store_true',help='全515枚を独立正解計算とbyte一致再生成でも検証')
    args=parser.parse_args()
    try:
        result=generate(args.output) if args.command=='generate' else verify(args.dataset,full=args.full)
        print('PUBLIC PRACTICE:',len(result['maps']),'maps / 103 per family / official_score=false')
        return 0
    except (OSError,ValueError) as error:
        print('ERROR:',error,file=sys.stderr);return 2


if __name__=='__main__': raise SystemExit(main())
