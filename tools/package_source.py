"""Build a source-only handoff ZIP with an explicit allowlist."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent.parent
TOP_LEVEL = ('README.md', '.gitignore', 'requirements.txt', 'requirements-dev.txt', 'run.py', 'manage.py')
TREES = {'app': {'.py'}, 'static': {'.html', '.css', '.js', '.svg'},
         'tests': {'.py'}, 'tools': {'.py'}, '.github/workflows': {'.yml'}}


def main():
    paths = [ROOT / name for name in TOP_LEVEL]
    for folder, extensions in TREES.items():
        paths.extend(p for p in (ROOT / folder).rglob('*')
                     if p.is_file() and p.suffix in extensions and '__pycache__' not in p.parts)
    output = ROOT / 'dist' / 'quickcart-mvp.zip'
    output.parent.mkdir(exist_ok=True)
    with ZipFile(output, 'w', compression=ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            archive.write(path, Path('QuickCart') / path.relative_to(ROOT))
    with ZipFile(output) as archive:
        assert archive.testzip() is None
        assert not any(any(part in {'data', '.venv', '__pycache__', '.git'} for part in Path(name).parts)
                       for name in archive.namelist())
        print(f'Packaged {len(archive.namelist())} source files: {output}')


if __name__ == '__main__':
    main()
