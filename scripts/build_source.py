"""Package only maintainable source/resources/docs, never private runtime data."""
from pathlib import Path
import zipfile
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from classroom.version import VERSION
output = root / 'dist' / ('v' + VERSION) / ('ClassroomAssistant-v' + VERSION + '-Source.zip')
output.parent.mkdir(parents=True, exist_ok=True)
files = [root / name for name in ('AGENTS.md', 'CHANGELOG.md', 'README.md', 'requirements.txt', 'requirements-dev.txt', 'pytest.ini', '.gitignore', '.gitattributes', 'launcher.py', '分组座位表.xlsx')]
for directory in ('classroom', 'resources', 'scripts', 'tests', 'docs'):
    files.extend(p for p in (root / directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc' and (directory != 'docs' or p.suffix.lower() in ('.md','.html','.svg','.png')))
with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
    for path in files:
        archive.write(path, str(Path('ClassroomAssistant-Source') / path.relative_to(root)))
print(output)
