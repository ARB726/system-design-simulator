"""Create a portable project archive, excluding all credentials and private runs."""
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'node_modules', '.next', '__pycache__', '.venv', '.git', '.local', 'test-results', 'playwright-report'}


def main():
    output = ROOT / '.local/systems-lab-portable.zip'
    output.parent.mkdir(exist_ok=True)
    files = [ROOT / 'Start-SystemsLab.cmd', ROOT / 'tools/run_fullstack.py', ROOT / 'tools/package_fullstack.py', ROOT / 'tests/test_fullstack.py', ROOT / 'data/optima.json']
    for directory in ('fullstack', 'sim'):
        for path in (ROOT / directory).rglob('*'):
            if not path.is_file() or EXCLUDED.intersection(path.relative_to(ROOT).parts):
                continue
            if path.name.startswith('.env') and path.name != '.env.example':
                continue
            if path.name == 'deployment.json' or path.suffix in ('.pyc', '.tsbuildinfo'):
                continue
            files.append(path)
    files = [path for path in files if path.is_file()]
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT))
    print(output)


if __name__ == '__main__':
    main()
