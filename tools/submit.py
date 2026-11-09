"""Read-only submission preflight and packaging in the existing ZIP format.

Student modules are parsed, never imported or executed. The bounded snapshots
checked here are also the bytes written to the archive.
"""
import ast
from dataclasses import dataclass, field
import os
from pathlib import Path
import stat
import sys
import zlib

from tools.submission import (MAX_BYTES, MAX_DIRECTORY_BYTES, MAX_FILES,
                              submission_path, validated_submission)


# Only Python sources, the required report/PDF and optional README are submitted.
# Prune generated/development directories even when they contain Python files.
EXCLUDED_DIRECTORIES = frozenset({
    '__pycache__', 'venv', 'env', 'site-packages', 'node_modules',
    'results', 'logs', 'log', 'data', 'datasets', 'submissions',
    'tests', 'test', 'build', 'dist', 'htmlcov', 'report',
})


@dataclass
class SubmissionFile:
    path: Path
    name: str
    size: int
    content: bytes = b''


@dataclass
class SubmissionCheck:
    files: list = field(default_factory=list)
    checks: list = field(default_factory=list)
    zip_bytes: int = 0

    @property
    def ok(self):
        return not any(level == 'FAIL' for level, _ in self.checks)


def _walk_error(error):
    raise error


def _candidates(work, slides):
    if work.is_symlink() or not work.is_dir():
        raise ValueError(f'{work} がありません（リンク不可）。先に ./rr init を実行してください。')
    if (work / 'report').is_symlink():
        raise ValueError('reportディレクトリのリンクは使用できません。')
    files = [(work / 'main.py', 'main.py')]
    for directory, directories, names in os.walk(work, onerror=_walk_error, followlinks=False):
        directories[:] = sorted(name for name in directories
                                if not name.startswith('.') and name not in EXCLUDED_DIRECTORIES)
        for name in directories:
            if (Path(directory) / name).is_symlink():
                raise ValueError(f'ソースディレクトリのリンクは使用できません: {Path(directory) / name}')
        for name in sorted(names):
            if (not name.endswith('.py') or name.startswith(('.', 'test_'))
                    or name.endswith('_test.py') or name in ('conftest.py', 'tests.py')
                    or name == 'main.py' and Path(directory) == work):
                continue
            path = Path(directory) / name
            files.append((path, path.relative_to(work).as_posix()))
    report = next((work / 'report' / ('experiment_log' + suffix) for suffix in ('.md', '.txt')
                   if (work / 'report' / ('experiment_log' + suffix)).exists()
                   or (work / 'report' / ('experiment_log' + suffix)).is_symlink()),
                  work / 'report/experiment_log.md')
    files += [(report, 'report/' + report.name), (slides, 'slides.pdf')]
    readme = work / 'README.md'
    if readme.exists() or readme.is_symlink():
        files.append((readme, 'README.md'))
    return sorted(files, key=lambda item: item[1])


def _modules(files):
    modules = set()
    for file in files:
        if file.name.endswith('.py'):
            parts = file.name[:-3].split('/')
            if parts[-1] == '__init__':
                parts.pop()
            # Include namespace packages as well as ordinary packages.
            modules.update('.'.join(parts[:index]) for index in range(1, len(parts) + 1))
    return modules


def _check_python(result):
    modules = _modules(result.files)
    roots = {module.split('.')[0] for module in modules}
    stdlib = sys.stdlib_module_names | set(sys.builtin_module_names)
    syntax_errors, dependencies, dynamic = [], [], []

    def dependency(module, location, relative=False):
        root = module.split('.')[0]
        if module in modules or not relative and root not in roots and root in stdlib:
            return
        dependencies.append(f'{location}: {module}（提出内にないモジュール／標準ライブラリ外）')

    for file in result.files:
        if not file.name.endswith('.py'):
            continue
        try:
            tree = compile(file.content, file.name, 'exec', flags=ast.PyCF_ONLY_AST, dont_inherit=True)
            compile(tree, file.name, 'exec', dont_inherit=True)
        except (SyntaxError, ValueError) as error:
            syntax_errors.append(f'{file.name}:{getattr(error, "lineno", None) or 1}: {error}')
            continue
        package = file.name.split('/')[:-1]
        # Recognize the common aliased form: from importlib import import_module as load.
        import_calls = {'__import__'}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == 'importlib' and not node.level:
                import_calls.update(alias.asname or alias.name for alias in node.names
                                    if alias.name == 'import_module')
        for node in ast.walk(tree):
            location = f'{file.name}:{getattr(node, "lineno", 1)}'
            if isinstance(node, ast.Import):
                for alias in node.names:
                    dependency(alias.name, location)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    if node.level > len(package):
                        dependencies.append(f'{location}: パッケージ外への相対import')
                        continue
                    base = package[:len(package) - node.level + 1]
                    module = '.'.join(base + (node.module.split('.') if node.module else []))
                else:
                    module = node.module or ''
                dependency(module, location, relative=bool(node.level))
            elif isinstance(node, ast.Call):
                name = (node.func.id if isinstance(node.func, ast.Name) else
                        node.func.attr if isinstance(node.func, ast.Attribute) else '')
                if name in import_calls or name in ('import_module', 'exec', 'eval', 'exec_module', 'load_module'):
                    dynamic.append(f'{location}: {name}')
                    if name in import_calls or name == 'import_module':
                        if node.args and isinstance(node.args[0], ast.Constant):
                            module = node.args[0].value
                            if isinstance(module, str) and module and not module.startswith('.'):
                                dependency(module, location)
    result.checks.append(('FAIL' if syntax_errors else 'PASS',
                          'Python構文: ' + ('; '.join(syntax_errors) if syntax_errors else '全ソースを検査（実行なし）')))
    result.checks.append(('FAIL' if dependencies else 'PASS',
                          '依存: ' + ('; '.join(sorted(set(dependencies))) if dependencies
                                     else '静的importは標準ライブラリまたは提出内のモジュール')))
    if dynamic:
        result.checks.append(('WARN', '動的import/コード実行は静的に保証できません: ' + '; '.join(dynamic)))


def check_submission(work, slides):
    """Check without writing a ZIP, extracting files, or running student code."""
    result = SubmissionCheck()
    try:
        candidates = _candidates(Path(work), Path(slides))
    except (OSError, ValueError) as error:
        result.checks.append(('FAIL', f'提出ディレクトリ: {error}'))
        return result
    for path, name in candidates:
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise ValueError('通常ファイルが必要です（リンク不可）')
            result.files.append(SubmissionFile(path, name, info.st_size))
        except (OSError, ValueError) as error:
            result.checks.append(('FAIL', f'提出ファイル {name}: {path}: {error}'))
    if result.ok:
        result.checks.append(('PASS', '必須ファイル: main.py、report/experiment_log.md または .txt、slides.pdf'))
    directory_bytes, seen = 0, {}
    valid_names = True
    try:
        for file in result.files:
            submission_path(file.name, seen)
            encoded = file.name.encode('utf-8')
            if len(encoded) > 65535:
                raise ValueError(f'ZIPファイル名が長すぎます: {file.name}')
            directory_bytes += 46 + len(encoded)
        if directory_bytes > MAX_DIRECTORY_BYTES:
            raise ValueError('ZIPディレクトリは256KiB以内にしてください。')
        result.checks.append(('PASS', '提出形式: 既存ZIPと同じ直下構造・パス規則（外側のwork/なし）'))
    except (ValueError, UnicodeError) as error:
        valid_names = False
        result.checks.append(('FAIL', f'提出形式: {error}'))
    total = sum(file.size for file in result.files)
    within_limits = len(result.files) <= MAX_FILES and total <= MAX_BYTES
    result.checks.append(('PASS' if within_limits else 'FAIL',
                          f'容量: {len(result.files)}/{MAX_FILES}ファイル、展開後{total}/{MAX_BYTES} bytes'
                          '（個別ファイルの追加上限なし）'))
    if not within_limits:
        return result
    actual_total = 0
    try:
        for file in result.files:
            with file.path.open('rb') as source:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    raise ValueError(f'通常ファイルが必要です: {file.name}')
                content = source.read(MAX_BYTES + 1)
            actual_total += len(content)
            if len(content) != file.size or actual_total > MAX_BYTES:
                raise ValueError(f'検査中にサイズが変化しました。編集を終えて再実行してください: {file.name}')
            file.content = content
    except (OSError, ValueError) as error:
        result.checks.append(('FAIL', f'ファイル読み取り: {error}'))
        return result
    _check_python(result)
    # Measure raw DEFLATE streams plus the exact headers written by ZipFile.
    # No archive or temporary file is generated during preflight.
    if not valid_names:
        return result
    result.zip_bytes = 22
    for file in result.files:
        compressor = zlib.compressobj(wbits=-15)
        compressed = len(compressor.compress(file.content)) + len(compressor.flush())
        result.zip_bytes += 76 + 2 * len(file.name.encode('utf-8')) + compressed
    result.checks.append(('PASS' if result.zip_bytes <= MAX_BYTES else 'FAIL',
                          f'ZIP容量: {result.zip_bytes}/{MAX_BYTES} bytes（圧縮とヘッダーから計算、ZIP生成なし）'))
    return result


def display_submission_check(result):
    for level, message in result.checks:
        print(f'[{level}] {message}')
    print('ZIPに含めるファイル（ZIP内の相対パス）:')
    for file in result.files:
        print(f'  {file.name} ({file.size} bytes)')
    print('[PASS] 提出事前検査完了' if result.ok else '[FAIL] 提出できません。上の項目を修正してください。')


def submit(result, output):
    if not result.ok:
        raise ValueError('提出検査に失敗したためZIPを作成しません。')
    with validated_submission(output) as zipped:
        for file in result.files:
            zipped.writestr(file.name, file.content)
    return Path(output)
