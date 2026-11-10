"""Public final practice: points, absolute deadlines, family filters and privacy."""
from contextlib import redirect_stdout,redirect_stderr
from copy import deepcopy
import argparse
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import final_practice as final,final_practice_data as data,rr_cli
from tools.final_practice_scoring import judge_output
from tools.isolated_runner import RunResult,EnvironmentUnavailable


class DataTests(unittest.TestCase):
    def test_515_released_maps_cover_103_per_family_with_valid_inputs_and_hashes(self):
        manifest=data.verify()
        self.assertFalse(manifest['official_score'])
        self.assertEqual(len(manifest['maps']),515)
        self.assertEqual(manifest['origin'],'released-contest-inputs')
        self.assertIs(type(manifest['released_seed']),int)
        for family in data.FAMILIES:
            _,maps=data.selected(family=family)
            self.assertEqual(len(maps),103)
            self.assertTrue(all(record['family']==family for record,_,_ in maps))
        self.assertEqual([record['family'] for record in manifest['maps'][:5]],list(data.FAMILIES))
        self.assertTrue(all(type(record['recipe']['seed']) is int for record in manifest['maps']))
        self.assertTrue(all(record['width']<=300 and record['height']<=300 and record['query_count']<=2000 for record in manifest['maps']))
        self.assertTrue(all(record['unreachable']>0 for record in manifest['maps'] if record['family']=='disconnected'))

    def test_byte_reproduction_uses_only_the_published_recipe(self):
        manifest=data.verify()
        for record in manifest['maps']:
            with tempfile.TemporaryDirectory() as temporary:
                path=Path(temporary)/'map'
                data.materialize(path,record['recipe'])
                self.assertEqual({name:data.digest(path/name) for name in data.INPUTS},record['sha256'])

    def test_unknown_family_and_modified_metadata_are_rejected(self):
        with self.assertRaises(ValueError): data.selected(family='private')
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)
            manifest=data.verify();manifest['maps'][0]['family']='different'
            (path/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaises(ValueError): data.verify(path)


class PointTests(unittest.TestCase):
    def maps(self):
        return [(dict(name=name,family=family),Path(name),[0]) for name,family in zip(('one','two'),('open','detour'))]

    def execute(self,states,seconds=.1):
        ticks=[0.0];paths=[];saved=[]
        def runner(program,path,**kwargs):
            self.assertEqual(kwargs['deadline'],seconds)
            paths.append(path.name);ticks[0]+=.04
            state=states[(len(paths)-1)%len(states)]
            return RunResult('OK' if state in ('OK','WRONG','FORMAT') else state,.04,12,10,128,7 if state=='RUNTIME_ERROR' else 0,
                             '0\n' if state=='OK' else '1\n' if state=='WRONG' else 'debug\n','',{})
        result=final.measure(Path('frozen'),self.maps(),final.base_result(seconds,'all'),
            runner=runner,clock=lambda:ticks[0],checkpoint=lambda r:saved.append(deepcopy(r)))
        return result,paths,saved

    def test_whole_map_points_failures_continue_and_last_inflight_map_is_zero(self):
        result,paths,_=self.execute(['OK','RUNTIME_ERROR'])
        self.assertEqual(paths,['one','two','one'])
        self.assertEqual([r['points'] for r in result['records']],[1,-1,0])
        self.assertEqual((result['correct'],result['incorrect'],result['score'],result['unfinished']),(1,1,0,1))
        self.assertEqual(result['status'],'COMPLETE')
        self.assertEqual(result['end_reason'],'TIME_LIMIT')
        self.assertFalse(result['official_score'])

    def test_wrong_format_memory_crash_and_leftover_processes_each_lose_one(self):
        for status in ('WRONG','FORMAT','RUNTIME_ERROR','MEMORY_EXCEEDED','OUTPUT_LIMIT','LEFTOVER_PROCESSES'):
            with self.subTest(status=status):
                result,_,_=self.execute([status])
                self.assertEqual(result['incorrect'],2)
                self.assertEqual(result['score'],-2)
                self.assertEqual(result['unfinished'],1)

    def test_validation_and_checkpoint_gaps_consume_the_deadline(self):
        ticks=[0.0]
        def runner(*args,**kwargs):
            ticks[0]+=.02
            return RunResult('OK',.02,8,8,128,0,'0\n','',{})
        def checkpoint(result):
            if result['records']: ticks[0]+=.03
        result=final.measure(Path('program'),self.maps(),final.base_result(.075,'all'),runner=runner,
                             clock=lambda:ticks[0],checkpoint=checkpoint)
        self.assertEqual([round(r['confirmed_elapsed_seconds'],3) for r in result['records']],[.02,.07])
        self.assertEqual(result['score'],2)
        with patch.object(final,'judge_output',side_effect=lambda *args:(ticks.__setitem__(0,ticks[0]+.2) or 'OK')):
            ticks[0]=0
            result=final.measure(Path('p'),self.maps(),final.base_result(.1,'all'),runner=runner,clock=lambda:ticks[0])
        self.assertEqual((result['score'],result['unfinished']),(0,1))

    def test_environment_and_interrupt_are_incomplete_without_invented_penalties(self):
        for error,reason in ((EnvironmentUnavailable('sandbox unavailable'),'ENVIRONMENT_ERROR'),(KeyboardInterrupt(),'OPERATOR_INTERRUPT')):
            with patch.object(final,'run',side_effect=error):
                result=final.measure(Path('p'),self.maps(),final.base_result(.01,'all'))
            self.assertEqual(result['status'],'INCOMPLETE')
            self.assertEqual(result['end_reason'],reason)
            self.assertEqual((result['score'],result['processed']),(0,0))

    def test_strict_format_and_leading_zero_normalization_match_day_three(self):
        self.assertEqual(judge_output('-000\n0012\n',[0,12]),'OK')
        for output in ('+0\n',' 0\n','0\n\n','debug\n'):
            self.assertEqual(judge_output(output,[0]),'OUTPUT_FORMAT')

    def test_all_map_check_visits_exactly_103_distinct_maps_once(self):
        maps=[(dict(name=f'open-{i:03d}',family='open'),Path(str(i)),[0]) for i in range(103)]
        paths=[];ticks=[0.0]
        def runner(program,path,**kwargs):
            paths.append(path.name);ticks[0]+=.01
            return RunResult('OK',.01,8,8,128,0,'0\n','',{})
        result=final.base_result(None,'open')
        result.update(mode='all-maps-once',safety_stop_seconds=1)
        result=final.measure(Path('p'),maps,result,runner=runner,clock=lambda:ticks[0])
        self.assertEqual(len(paths),103)
        self.assertEqual(len(set(paths)),103)
        self.assertEqual(result['end_reason'],'ALL_MAPS_DONE')
        self.assertEqual(result['correct'],103)
        self.assertTrue(result['all_correct'])
        self.assertEqual(result['map_count'],103)

    def test_all_map_check_reports_each_safety_stop_as_unconfirmed(self):
        result=final.base_result(None,'all');result.update(mode='all-maps-once',safety_stop_seconds=.01)
        execution=RunResult('TIME_LIMIT',.01,8,8,128,0,'','',{})
        result=final.measure(Path('p'),self.maps(),result,runner=lambda *a,**k:execution)
        self.assertEqual(result['end_reason'],'ALL_MAPS_DONE')
        self.assertEqual(result['unfinished'],2)
        self.assertEqual(result['processed'],0)
        self.assertFalse(result['all_correct'])
        self.assertEqual(final.result_code(result),1)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name);self.work=self.root/'work';self.work.mkdir()
        (self.work/'main.py').write_text('print(0)\n')
        self.result=self.root/'result.json'

    def cli(self,args):
        with redirect_stdout(io.StringIO()) as output,redirect_stderr(io.StringIO()): code=rr_cli.main(args)
        return code,output.getvalue()

    def test_default_180_seconds_family_filter_and_json_are_forwarded(self):
        def evaluate(work,result,path):
            self.assertEqual(work,self.work)
            self.assertEqual(result['seconds'],180)
            self.assertEqual(result['family'],'maze')
            result.update(status='COMPLETE',end_reason='TIME_LIMIT');final.save(path,result)
            return result
        with patch.object(final,'evaluate',side_effect=evaluate):
            code,output=self.cli(['--_worker','mock-final','--work',str(self.work),'--family','maze','--result',str(self.result)])
        self.assertEqual(code,0)
        self.assertIn('PUBLIC PRACTICE',output)
        self.assertEqual(json.loads(self.result.read_text())['kind'],final.KIND)

    def test_existing_result_and_work_files_are_never_overwritten(self):
        original=b'original measurement\n';self.result.write_bytes(original)
        code,_=self.cli(['mock-final','--work',str(self.work),'--result',str(self.result)])
        self.assertEqual(code,2);self.assertEqual(self.result.read_bytes(),original)
        source=(self.work/'main.py').read_bytes()
        code,_=self.cli(['mock-final','--work',str(self.work),'--result',str(self.work/'main.py')])
        self.assertEqual(code,2);self.assertEqual((self.work/'main.py').read_bytes(),source)

    def test_invalid_duration_and_unknown_family_do_not_run_code(self):
        for value in ('0','-1','181','nan','inf'):
            code,_=self.cli(['mock-final','--work',str(self.work),'--seconds',value,'--result',str(self.result)])
            self.assertEqual(code,2);self.assertFalse(self.result.exists())
        with self.assertRaises(SystemExit): self.cli(['mock-final','--family','unknown'])

    def test_snapshot_reads_python_only_without_importing_or_changing_work(self):
        (self.work/'main.py').write_text("raise RuntimeError('must not be imported')\n")
        (self.work/'private.txt').write_text('not exposed to program')
        before=(self.work/'main.py').read_bytes()
        frozen=self.root/'snapshot'
        hashes=final.snapshot(self.work,frozen)
        self.assertEqual(set(hashes),{'main.py'})
        self.assertEqual((frozen/'main.py').read_bytes(),before)
        self.assertFalse((frozen/'private.txt').exists())
        self.assertEqual((self.work/'main.py').read_bytes(),before)

    def test_service_interrupt_stops_the_explicit_worker_unit(self):
        args=argparse.Namespace(work=self.work,result=self.result,seconds=3,family='all',run_id=None,team=None)
        with patch.object(final.subprocess,'run',side_effect=[KeyboardInterrupt(),None]) as calls,redirect_stdout(io.StringIO()):
            self.assertEqual(final.run_command(args,inside=lambda:False),130)
        command=calls.call_args_list[0].args[0]
        unit=next(part.split('=',1)[1] for part in command if part.startswith('--unit='))
        self.assertEqual(calls.call_args_list[1].args[0],['systemctl','--user','stop',unit])
        self.assertEqual(json.loads(self.result.read_text())['end_reason'],'OPERATOR_INTERRUPT')


if __name__=='__main__': unittest.main()
