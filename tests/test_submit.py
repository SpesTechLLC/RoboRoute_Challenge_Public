"""Submission preflight, public CLI, and the existing ZIP consumer contract."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import rr_cli
from tools import submit as submission
from tools.submission import MAX_BYTES, MAX_FILES, extract_submission


def snapshot(root):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file()}


class SubmitTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.work = rr_cli.init_work(self.root / 'work')
        self.slides = self.root / 'slides.pdf'
        self.slides.write_bytes(b'%PDF-1.4\n%%EOF\n')

    def write(self, name, content='pass\n'):
        path = self.work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return path

    def cli(self, *arguments):
        with patch.object(rr_cli, 'ROOT', self.root), redirect_stdout(io.StringIO()) as out, \
                redirect_stderr(io.StringIO()) as err:
            code = rr_cli.main(['submit', *map(str, arguments)])
        return code, out.getvalue(), err.getvalue()

    def check(self):
        return submission.check_submission(self.work, self.slides)

    def test_no_argument_submit_generates_existing_format_and_preserves_sources(self):
        self.write('README.md', '説明\n')
        self.write('helper.py', 'from collections import deque\n')
        before = snapshot(self.work)
        slides_before = self.slides.read_bytes()
        with patch('tools.submission.extract_submission', wraps=extract_submission) as validator:
            code, output, error = self.cli()
        self.assertEqual((code, error), (0, ''))
        validator.assert_called_once()
        archives = list((self.root / 'submissions').glob('submission-*.zip'))
        self.assertEqual(len(archives), 1)
        self.assertIn(str(archives[0]), output)
        self.assertIn('ZIP生成後の形式検査', output)
        with zipfile.ZipFile(archives[0]) as zipped:
            expected = {'main.py', 'helper.py', 'README.md', 'slides.pdf', 'report/experiment_log.md',
                        'roboroute/__init__.py', 'roboroute/dataset.py', 'roboroute/generator.py',
                        'roboroute/solver.py', 'roboroute/visualization.py'}
            self.assertEqual(set(zipped.namelist()), expected)
            for name in expected - {'slides.pdf'}:
                self.assertEqual(zipped.read(name), (self.work / name).read_bytes())
            self.assertEqual(zipped.read('slides.pdf'), slides_before)
        extracted = extract_submission(archives[0], self.root / 'extracted')
        self.assertTrue((extracted / 'main.py').is_file())
        self.assertEqual(snapshot(self.work), before)
        self.assertEqual(self.slides.read_bytes(), slides_before)

    def test_check_creates_nothing_even_with_explicit_output(self):
        existing = self.root / 'existing.zip'
        existing.write_bytes(b'keep existing archive')
        before = snapshot(self.root)
        directories = {str(path) for path in self.root.rglob('*')}
        with patch('tools.submission.zipfile.ZipFile', side_effect=AssertionError('ZIP created')), \
                patch('tools.submission.tempfile.TemporaryDirectory', side_effect=AssertionError('temporary file')):
            code, output, error = self.cli('--check', '--output', existing)
        self.assertEqual((code, error), (0, ''))
        self.assertIn('[PASS]', output)
        self.assertIn('roboroute/solver.py', output)
        self.assertIn('ZIP容量', output)
        self.assertEqual(snapshot(self.root), before)
        self.assertEqual({str(path) for path in self.root.rglob('*')}, directories)

    def test_each_missing_required_file_fails_without_output(self):
        for path in (self.work / 'main.py', self.work / 'report/experiment_log.md', self.slides):
            with self.subTest(path=path):
                content = path.read_bytes()
                path.unlink()
                try:
                    for arguments in ((), ('--check',)):
                        code, output, _ = self.cli(*arguments)
                        self.assertEqual(code, 1)
                        self.assertIn('[FAIL]', output)
                        self.assertIn(path.name, output)
                        self.assertFalse((self.root / 'submissions').exists())
                finally:
                    path.write_bytes(content)

    def test_missing_work_has_init_guidance(self):
        code, output, _ = self.cli('--check', '--work', self.root / 'missing')
        self.assertEqual(code, 1)
        self.assertIn('./rr init', output)

    def test_txt_report_is_accepted(self):
        (self.work / 'report/experiment_log.md').rename(self.work / 'report/experiment_log.txt')
        self.assertTrue(self.check().ok)
        code, _, _ = self.cli()
        self.assertEqual(code, 0)
        with zipfile.ZipFile(next((self.root / 'submissions').glob('*.zip'))) as zipped:
            self.assertIn('report/experiment_log.txt', zipped.namelist())

    def test_syntax_errors_in_entry_or_helpers_fail(self):
        for name, content in [('main.py', 'def broken(:\n'), ('helper.py', 'return 1\n')]:
            with self.subTest(name=name):
                path = self.work / name
                original = path.read_bytes() if path.exists() else None
                self.write(name, content)
                try:
                    code, output, _ = self.cli()
                    self.assertEqual(code, 1)
                    self.assertIn('[FAIL] Python構文', output)
                    self.assertIn(name, output)
                    self.assertFalse((self.root / 'submissions').exists())
                finally:
                    if original is None:
                        path.unlink()
                    else:
                        path.write_bytes(original)

    def test_external_and_missing_local_imports_fail_without_importing(self):
        for code in ('import numpy\n', 'from requests.sessions import Session\n',
                     'import missing_helper\n', 'import roboroute.missing\n',
                     '__import__("numpy")\n',
                     'from importlib import import_module as load\nload("numpy")\n'):
            with self.subTest(code=code):
                self.write('main.py', code)
                result = self.check()
                self.assertFalse(result.ok)
                self.assertTrue(any(level == 'FAIL' and message.startswith('依存:')
                                    for level, message in result.checks))

    def test_local_packages_namespace_packages_and_relative_imports(self):
        self.write('main.py', 'import helpers.solver\nfrom package import solver\n')
        self.write('helpers/solver.py', 'import heapq\n')
        self.write('package/__init__.py', 'from .solver import solve\n')
        self.write('package/solver.py', 'from ..helpers import solver\n')
        self.assertFalse(self.check().ok, 'relative import cannot escape top-level package')
        self.write('package/solver.py', 'from . import support\ndef solve(): pass\n')
        self.write('package/support.py', 'from collections import deque\n')
        self.assertTrue(self.check().ok)

    def test_dynamic_import_warns_and_never_runs_student_code(self):
        marker = self.root / 'should-not-exist'
        self.write('main.py', f'from pathlib import Path\nimport importlib\n'
                   f'Path({str(marker)!r}).write_text("executed")\n'
                   'name = input()\nimportlib.import_module(name)\n')
        code, output, _ = self.cli('--check')
        self.assertEqual(code, 0)
        self.assertIn('[WARN]', output)
        self.assertFalse(marker.exists())

    def test_generated_files_environments_tests_and_datasets_are_excluded(self):
        unwanted = ['.hidden.py', '__pycache__/cache.py', 'nested/__pycache__/cache.py',
                    '.venv/lib/python.py', 'venv/lib/python.py', 'env/activate.py',
                    'site-packages/external.py', 'node_modules/dependency.py',
                    'results/test.py', 'results/output.json', 'logs/debug.py', 'debug.log',
                    'data/loader.py', 'datasets/generate.py', 'submissions/old.py',
                    'tests/test_code.py', 'test_main.py', 'solver_test.py', 'conftest.py',
                    'build/generated.py', 'dist/main.py', 'report/scratch.py',
                    'report/extra.md', 'map.csv', 'big.bin']
        for name in unwanted:
            self.write(name, 'invalid python!')
        self.write('nested/main.py')
        result = self.check()
        self.assertTrue(result.ok, result.checks)
        archive = submission.submit(result, self.root / 'clean.zip')
        with zipfile.ZipFile(archive) as zipped:
            self.assertFalse(set(unwanted) & set(zipped.namelist()))
            self.assertIn('nested/main.py', zipped.namelist())

    def test_symlinks_in_submission_are_rejected_and_excluded_links_ignored(self):
        link = self.work / 'linked.py'
        link.symlink_to(self.work / 'main.py')
        self.assertFalse(self.check().ok)
        link.unlink()
        (self.work / 'linked').symlink_to(self.root, target_is_directory=True)
        self.assertFalse(self.check().ok)
        (self.work / 'linked').unlink()
        (self.work / '.venv').symlink_to(self.root, target_is_directory=True)
        self.assertTrue(self.check().ok)

    def test_unsafe_duplicate_and_file_directory_collisions_fail_preflight(self):
        for name in ('MAIN.py', 'bad:name.py', 'slides.pdf/helper.py'):
            with self.subTest(name=name):
                path = self.write(name)
                try:
                    result = self.check()
                    self.assertFalse(result.ok)
                    self.assertTrue(any(level == 'FAIL' and message.startswith('提出形式:')
                                        for level, message in result.checks))
                finally:
                    path.unlink()

    def test_expanded_size_limit_is_checked_before_reading(self):
        with (self.work / 'report/experiment_log.md').open('wb') as file:
            file.truncate(MAX_BYTES + 1)
        code, output, _ = self.cli('--check')
        self.assertEqual(code, 1)
        self.assertIn('[FAIL] 容量', output)
        self.assertFalse((self.root / 'submissions').exists())

    def test_file_count_limit(self):
        for index in range(MAX_FILES):
            self.write(f'helper_{index}.py', '')
        result = self.check()
        self.assertFalse(result.ok)
        self.assertTrue(any(level == 'FAIL' and message.startswith('容量:')
                            for level, message in result.checks))

    def test_compressed_size_limit_includes_zip_overhead(self):
        self.work = self.root / 'minimal'
        self.write('main.py', '')
        self.write('report/experiment_log.md', '')
        self.slides.write_bytes(os.urandom(1024))
        total = sum(file.size for file in self.check().files)
        with patch.object(submission, 'MAX_BYTES', total + 1):
            result = self.check()
        self.assertFalse(result.ok)
        self.assertTrue(any(level == 'FAIL' and message.startswith('ZIP容量:')
                            for level, message in result.checks))

    def test_zip_directory_size_limit(self):
        with patch.object(submission, 'MAX_DIRECTORY_BYTES', 10):
            result = self.check()
        self.assertFalse(result.ok)
        self.assertTrue(any('256KiB' in message for _, message in result.checks))

    def test_zip_size_projection_matches_real_archive_with_unicode_names(self):
        self.write('ヘルパー.py', '# 日本語\nvalue = 1\n')
        result = self.check()
        self.assertTrue(result.ok)
        archive = submission.submit(result, self.root / 'unicode.zip')
        self.assertEqual(archive.stat().st_size, result.zip_bytes)

    def test_invalid_generated_zip_is_not_published(self):
        def corrupt(archive, destination):
            archive.write_bytes(b'invalid ZIP')
            return extract_submission(archive, destination)

        with patch('tools.submission.extract_submission', side_effect=corrupt):
            code, _, error = self.cli()
        self.assertEqual(code, 2)
        self.assertIn('[FAIL]', error)
        self.assertEqual(list((self.root / 'submissions').iterdir()), [])

    def test_existing_and_racing_outputs_are_preserved(self):
        output = self.root / 'existing.zip'
        output.write_bytes(b'original')
        code, _, error = self.cli('--output', output)
        self.assertEqual(code, 2)
        self.assertIn('既に存在', error)
        self.assertEqual(output.read_bytes(), b'original')
        output.unlink()

        def race(archive, destination):
            validated = extract_submission(archive, destination)
            output.write_bytes(b'racing writer')
            return validated

        with patch('tools.submission.extract_submission', side_effect=race):
            code, _, _ = self.cli('--output', output)
        self.assertEqual(code, 2)
        self.assertEqual(output.read_bytes(), b'racing writer')
        self.assertFalse(list(self.root.glob('.rr-pack-*')))

    def test_broken_symlink_output_is_not_overwritten(self):
        output = self.root / 'linked.zip'
        output.symlink_to(self.root / 'absent')
        code, _, _ = self.cli('--output', output)
        self.assertEqual(code, 2)
        self.assertTrue(output.is_symlink())
        self.assertFalse((self.root / 'absent').exists())

    def test_repeated_submissions_and_optional_team_work_output_slides(self):
        for _ in range(2):
            code, _, _ = self.cli('--team', 'team01')
            self.assertEqual(code, 0)
        self.assertEqual(len(list((self.root / 'submissions').glob('team01-*.zip'))), 2)
        alternative = self.root / 'alternative'
        self.work.rename(alternative)
        pdf = self.root / 'presentation.pdf'
        self.slides.rename(pdf)
        output = self.root / 'custom/team01.zip'
        code, _, _ = self.cli('--work', alternative, '--slides', pdf, '--output', output)
        self.assertEqual(code, 0)
        self.assertTrue(output.is_file())
        code, _, error = self.cli('--team', '../unsafe', '--check')
        self.assertEqual(code, 2)
        self.assertIn('チーム名', error)

    def test_existing_pack_and_new_submit_have_the_same_layout(self):
        self.write('helper.py')
        old = rr_cli.pack_submission(self.work, 'team01', self.slides, self.root / 'old.zip')
        new = submission.submit(self.check(), self.root / 'new.zip')
        with zipfile.ZipFile(old) as previous, zipfile.ZipFile(new) as current:
            self.assertEqual(set(previous.namelist()), set(current.namelist()))
            for name in previous.namelist():
                self.assertEqual(previous.read(name), current.read(name))

    def test_pack_entry_point_and_existing_init_still_work(self):
        output = self.root / 'packed.zip'
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = rr_cli.main(['pack', '--work', str(self.work), '--team', 'team01',
                                '--slides', str(self.slides), '--output', str(output)])
        self.assertEqual(code, 0)
        with self.assertRaises(ValueError):
            rr_cli.init_work(self.work)

    def test_actual_entry_point_is_independent_of_cwd_and_isolation(self):
        command = [sys.executable, '-B', str(rr_cli.ROOT / 'rr'), 'submit', '--check',
                   '--work', str(self.work), '--slides', str(self.slides)]
        before = snapshot(self.root)
        result = subprocess.run(command, cwd=self.root, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('[PASS] 提出事前検査完了', result.stdout)
        self.assertEqual(snapshot(self.root), before)


class ExistingExtractorTests(unittest.TestCase):
    def test_explicit_directories_are_still_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / 'old.zip'
            with zipfile.ZipFile(archive, 'w') as zipped:
                for name, content in [('main.py', 'pass'), ('slides.pdf', '%PDF'),
                                      ('report/', ''), ('report/experiment_log.txt', 'report')]:
                    zipped.writestr(name, content)
            self.assertTrue(extract_submission(archive, root / 'extracted').is_dir())


if __name__ == '__main__':
    unittest.main()
