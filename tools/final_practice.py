"""Single-program public practice of the 180-second whole-map competition."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime
from dataclasses import asdict
import fcntl
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid

from tools.final_practice_data import ROOT,PACK,FAMILIES,LABELS,INPUTS,selected,digest
from tools.final_practice_runtime import run
from tools.final_practice_scoring import METHOD,FAILURES,judge_output,summarize
from tools.isolated_runner import EnvironmentUnavailable,delegated_parent
from tools.submit import _candidates,_check_python,SubmissionCheck,SubmissionFile
from tools.submission import MAX_BYTES,MAX_FILES,submission_path

KIND='public-final-practice'


def save(path,value):
    path=Path(path)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,delete=False) as stream:
        temporary=Path(stream.name)
        try:
            json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)
            stream.write('\n');stream.flush();os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True);raise
    try: os.replace(temporary,path)
    finally: temporary.unlink(missing_ok=True)


@contextmanager
def exclusive_host():
    # Shared with the instructor CLI when both repositories use the same OS user.
    path=Path(tempfile.gettempdir())/f'roboroute-day3-{os.getuid()}.lock'
    fd=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as error: raise ValueError('別の180秒測定が実行中です。') from error
        for group in delegated_parent().glob('roboroute-*'):
            suffix=group.name[len('roboroute-'):]
            if len(suffix)!=32 or any(c not in '0123456789abcdef' for c in suffix): continue
            try: populated=dict(line.split() for line in (group/'cgroup.events').read_text().splitlines()).get('populated')
            except FileNotFoundError: continue
            if populated=='1': raise EnvironmentUnavailable('別の隔離実行が動いています。測定を終了してから実行してください。')
        yield
    finally: os.close(fd)


def snapshot(work,destination):
    """Use the existing submission's source selection and static import checks."""
    checks=SubmissionCheck()
    total,seen=0,{}
    candidates=[(path,name) for path,name in _candidates(Path(work)) if name.endswith('.py')]
    if len(candidates)>MAX_FILES: raise ValueError('Pythonソースのファイル数が上限を超えています。')
    for path,name in candidates:
        submission_path(name,seen)
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(fd,'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode): raise ValueError('通常のPythonソースが必要です。')
            content=stream.read(MAX_BYTES+1)
        total+=len(content)
        if total>MAX_BYTES: raise ValueError('Pythonソースの合計が32MiBを超えています。')
        checks.files.append(SubmissionFile(path,name,len(content),content))
    _check_python(checks)
    if not checks.ok: raise ValueError('\n'.join(message for level,message in checks.checks if level=='FAIL'))
    hashes={}
    for file in checks.files:
        target=Path(destination)/file.name
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(file.content)
        hashes[file.name]=hashlib.sha256(file.content).hexdigest()
    return hashes


def base_result(seconds,family,run_id=None,team=None):
    return dict(schema_version=1,kind=KIND,scoring_method=METHOD,official_score=False,
                profile='PUBLIC PRACTICE',run_id=run_id or uuid.uuid4().hex,team_id=team,
                seconds=seconds,family=family,memory_limit_mib=128,status='INCOMPLETE',
                end_reason='PREPARING',elapsed_seconds=0,records=[],**summarize([]))


def measure(program,maps,result,*,checkpoint=lambda result:None,runner=None,clock=None,progress=None):
    """Deadline, points and recovery match day three; maps repeat in public order."""
    if not maps: raise ValueError('測定する地図がありません。')
    runner,clock=runner or run,clock or time.perf_counter
    check_all=result.get('mode')=='all-maps-once'
    started=clock();deadline=None if check_all else started+result['seconds'];last_progress=started
    result['map_count']=len(maps)
    result['end_reason']='RUNNING'
    try:
        checkpoint(result)
        for index,(record,path,expected) in enumerate(maps if check_all else itertools.cycle(maps)):
            if not check_all and clock()>=deadline:
                result.update(status='COMPLETE',end_reason='TIME_LIMIT');break
            map_started=clock()
            execution=runner(program,path,deadline=map_started+result['safety_stop_seconds'] if check_all else deadline)
            state=judge_output(execution.stdout,expected) if execution.status=='OK' else execution.status
            confirmed=clock()
            if (not check_all and confirmed>=deadline) or state=='TIME_LIMIT': state='TIME_LIMIT'
            if state not in FAILURES|{'OK','TIME_LIMIT'}:
                raise EnvironmentUnavailable('想定外の実行状態: '+state)
            result['records'].append(dict(index=index,map_id=record['name'],family=record['family'],
                round=index//len(maps)+1,status=state,points=1 if state=='OK' else -1 if state in FAILURES else 0,
                confirmed_elapsed_seconds=confirmed-started,elapsed_seconds=clock()-map_started,
                memory_peak_mib=execution.memory_peak_mib,returncode=execution.returncode,
                stderr_preview=execution.stderr[:512] if state in FAILURES else ''))
            result.update(summarize(result['records']))
            result['records'][-1]['cumulative_score']=result['score']
            result['elapsed_seconds']=clock()-started
            if state=='TIME_LIMIT' and not check_all:
                result.update(status='COMPLETE',end_reason='TIME_LIMIT');break
            checkpoint(result)  # part of the 180-second budget
            if progress and clock()-last_progress>=10:
                progress(result);last_progress=clock()
        else:
            if check_all: result.update(status='COMPLETE',end_reason='ALL_MAPS_DONE')
    except (KeyboardInterrupt,SystemExit):
        result.update(status='INCOMPLETE',end_reason='OPERATOR_INTERRUPT')
    except (EnvironmentUnavailable,OSError,ValueError,RuntimeError) as error:
        result.update(status='INCOMPLETE',end_reason='ENVIRONMENT_ERROR',error=str(error))
    finally:
        result.update(summarize(result['records']))
        result['elapsed_seconds']=clock()-started
        result['deadline_overshoot_seconds']=0 if check_all else max(0,result['elapsed_seconds']-result['seconds'])
        if check_all: result['all_correct']=result['status']=='COMPLETE' and result['correct']==len(maps)
        result['by_family']={family:summarize([r for r in result['records'] if r['family']==family])
                             for family in FAMILIES if any(record['family']==family for record,_,_ in maps)}
        checkpoint(result)
    return result


def evaluate(work,result,path,*,pack=PACK):
    affinity=os.sched_getaffinity(0)
    with exclusive_host(),tempfile.TemporaryDirectory(prefix='rr-public-final-') as temporary:
        root=Path(temporary)
        result['program_sha256']=snapshot(work,root/'program')
        manifest,maps=selected(pack,result['family'])
        frozen=[]
        for record,source,expected in maps:
            target=root/'inputs'/record['name'];target.mkdir(parents=True)
            for name in INPUTS: shutil.copyfile(source/name,target/name)
            if {name:digest(target/name) for name in INPUTS}!=record['sha256']:
                raise ValueError('入力データが準備中に変更されました。')
            frozen.append((record,target,expected))
        result.update(dataset_id=manifest['dataset_id'],map_cycle=[record['name'] for record,_,_ in frozen],
                      cpu=min(affinity),python=sys.version,repeat_until_deadline=result.get('mode')!='all-maps-once')
        try:
            os.sched_setaffinity(0,{result['cpu']})
            return measure(root/'program',frozen,result,checkpoint=lambda result:save(path,result),
                           progress=lambda result:print(f"  経過{result['elapsed_seconds']:.1f}秒 / 正解{result['correct']} / 失敗{result['incorrect']} / 得点{result['score']}",flush=True))
        finally: os.sched_setaffinity(0,affinity)


def display(result,path):
    print('PUBLIC PRACTICE — 公開データによる練習（公式結果ではありません）')
    if result.get('mode')=='all-maps-once':
        print(f"全地図1回ずつ: {result.get('map_count','?')}枚 / 正解 {result['correct']} / 不正解・失敗 {result['incorrect']} / 安全停止で未確定 {result['unfinished']}")
    else:
        print(f"正解 {result['correct']} / 不正解・失敗 {result['incorrect']} / 得点 {result['score']} / 処理数 {result['processed']} / 時間切れ未確定 {result['unfinished']}")
    print(f"終了: {result['status']} / {result['end_reason']} / 実時間 {result['elapsed_seconds']:.3f}秒 / 最大メモリ {result['memory_peak_mib']:.2f}MiB")
    for family,values in result.get('by_family',{}).items():
        print(f"  {LABELS[family]}: 正解{values['correct']} / 失敗{values['incorrect']} / 得点{values['score']}")
    if result.get('error'): print('ERROR:',result['error'],file=sys.stderr)
    print('結果JSON:',path)
    return result_code(result)


def result_code(result):
    failed=result['incorrect'] or (result.get('mode')=='all-maps-once' and result['unfinished'])
    return 130 if result['end_reason']=='OPERATOR_INTERRUPT' else 2 if result['status']!='COMPLETE' else 1 if failed else 0


def run_command(args,*,worker=False,inside=lambda:False):
    check_all=getattr(args,'command','mock-final')=='check-final'
    if not check_all and (not math.isfinite(args.seconds) or not 0<args.seconds<=180):
        raise ValueError('--seconds は0より大きく180以下にしてください。')
    if check_all and (not math.isfinite(args.safety_stop) or not 0<args.safety_stop<=180):
        raise ValueError('--safety-stop は0より大きく180以下にしてください。')
    work=Path(args.work).absolute()
    if work.is_symlink() or not (work/'main.py').is_file(): raise ValueError('work/main.pyがありません（リンク不可）。')
    command_name='check-final' if check_all else 'mock-final'
    path=Path(args.result).absolute() if args.result else ROOT/'results'/(command_name+'-'+args.family+'-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]+'.json')
    if path==work or work.resolve() in path.resolve().parents: raise ValueError('結果JSONはwork/の外へ保存してください。')
    path.parent.mkdir(parents=True,exist_ok=True)
    result=base_result(args.seconds,args.family,args.run_id,args.team)
    if check_all:
        result.update(kind='public-final-correctness-check',mode='all-maps-once',seconds=None,
                      scoring_method='public-final-correctness-v1',safety_stop_seconds=args.safety_stop)
    else: result['mode']='timed'
    if worker and args.run_id:
        if path.is_symlink(): raise ValueError('結果JSONにリンクは使用できません。')
        pending=json.loads(path.read_text())
        if (pending.get('run_id')!=args.run_id or pending.get('kind')!=result['kind'] or pending.get('end_reason')!='PREPARING'
                or pending.get('records') or pending.get('status')!='INCOMPLETE'):
            raise ValueError('既存の結果は上書きしません。')
    else:
        try:
            with path.open('x',encoding='utf-8') as stream: json.dump(result,stream,ensure_ascii=False,indent=2)
        except FileExistsError as error: raise ValueError('既存の結果は上書きしません。別名を指定してください。') from error
    if not (worker and args.run_id):
        print(f'PUBLIC PRACTICE: 全地図を1回ずつ / {args.family} / 128MiB' if check_all else
              f'PUBLIC PRACTICE: {args.seconds:g}秒 / {args.family} / 128MiB / 地図ごと+1・-1 / 未確定0点',flush=True)
    if not worker and not inside():
        unit='roboroute-public-final-'+uuid.uuid4().hex+'.service'
        command=['systemd-run','--user','--wait','--pipe','--collect','--unit='+unit,'--working-directory='+str(ROOT),
                 sys.executable,'-B',str(ROOT/'rr'),'--_worker',command_name,'--work',str(work),'--family',args.family,
                 '--result',str(path),'--_run-id',result['run_id']]
        command+=['--safety-stop',str(args.safety_stop)] if check_all else ['--seconds',str(args.seconds)]
        if args.team: command+=['--team',args.team]
        try:
            service=subprocess.run(command,stdin=subprocess.DEVNULL)
            saved=json.loads(path.read_text())
            if saved['end_reason'] in ('PREPARING','RUNNING'):
                saved.update(status='INCOMPLETE',end_reason='ENVIRONMENT_ERROR',error=f'隔離ワーカーが終了しました（終了コード{service.returncode}）。')
                save(path,saved)
            return display(saved,path)
        except KeyboardInterrupt:
            subprocess.run(['systemctl','--user','stop',unit],timeout=15)
            saved=json.loads(path.read_text())
            saved.update(status='INCOMPLETE',end_reason='OPERATOR_INTERRUPT');save(path,saved)
            return display(saved,path)
        except (OSError,ValueError) as error:
            result.update(error=str(error),end_reason='ENVIRONMENT_ERROR');save(path,result)
            return display(result,path)
    previous=signal.getsignal(signal.SIGTERM)
    def interrupt(*_): raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,interrupt)
    try:
        try: result=evaluate(work,result,path)
        except KeyboardInterrupt:
            result.update(end_reason='OPERATOR_INTERRUPT');save(path,result)
        except (EnvironmentUnavailable,OSError,ValueError,RuntimeError) as error:
            result.update(end_reason='ENVIRONMENT_ERROR',error=str(error));save(path,result)
        return result_code(result) if worker and args.run_id else display(result,path)
    finally: signal.signal(signal.SIGTERM,previous)
