"""Collect installed runtime license evidence; does not grant legal approval.

Run after installing the hash-pinned runtime in a clean environment. Only
distribution license files are exported, never application/runtime data.
"""
import argparse
import hashlib
from importlib.metadata import distribution
import json
from pathlib import Path, PurePosixPath
import re


def normalized(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def collect(lock, loader=distribution):
    raw = Path(lock).read_bytes()
    pins = re.findall(r'^([A-Za-z0-9_.-]+)==([^\s\\]+)', raw.decode('utf-8'), re.M)
    if not pins or len({normalized(name) for name, _ in pins}) != len(pins):
        raise ValueError('Expected unique exact runtime pins')
    # Do not silently omit a newly added editable, URL or unpinned requirement.
    for line in raw.decode('utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith(('#', '--hash=')) and not re.fullmatch(r'[A-Za-z0-9_.-]+==[^\s\\]+\s*\\?', line):
            raise ValueError('Unsupported runtime requirement')
    packages, notices = [], []
    for name, version in sorted(pins, key=lambda pin: normalized(pin[0])):
        dist = loader(name)
        if dist.version != version or normalized(dist.metadata['Name']) != normalized(name):
            raise ValueError('Installed runtime differs from exact lock')
        files = [PurePosixPath(str(path).replace('\\', '/')) for path in (dist.files or [])]
        roots = {path.parts[0] for path in files if path.parts and path.parts[0].endswith('.dist-info')}
        if len(roots) != 1:
            raise ValueError('Missing unique distribution metadata')
        root = next(iter(roots))
        base = Path(dist.locate_file(root)).resolve()
        selected = {path for path in files if path.parts[0] == root and (
            len(path.parts) > 2 and path.parts[1] == 'licenses' or
            len(path.parts) == 2 and path.name.upper().startswith(('LICENSE', 'LICENCE', 'COPYING', 'NOTICE')))}
        for declared in dist.metadata.get_all('License-File', []):
            relative = PurePosixPath(declared.replace('\\', '/'))
            if relative.is_absolute() or '..' in relative.parts or ':' in declared:
                raise ValueError('License declaration escapes distribution metadata')
            matches = {PurePosixPath(root)/relative, PurePosixPath(root)/'licenses'/relative} & set(files)
            if not matches:
                raise ValueError('Declared license file is missing')
            selected.update(matches)
        if not selected:
            raise ValueError('No installed license evidence')
        evidence = []
        for path in sorted(selected):
            local = Path(dist.locate_file(str(path)))
            if '..' in path.parts or not local.resolve().is_relative_to(base) or not local.is_file():
                raise ValueError('License evidence escapes distribution metadata')
            if local.stat().st_size > 5 * 1024 * 1024:
                raise ValueError('License document exceeds evidence limit')
            content = local.read_bytes()
            text = content.decode('utf-8-sig')
            if not text.strip():
                raise ValueError('Empty license document')
            relative = path.relative_to(root).as_posix()
            evidence.append({'path': relative, 'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content)})
            notices.append(f'===== {name} {version} / {relative} =====\n{text}\n')
        packages.append({'name': name, 'version': version,
                         'declaredExpression': dist.metadata.get('License-Expression'),
                         'declaredClassifiers': dist.metadata.get_all('Classifier', []),
                         'licenseFiles': evidence})
    report = {'schemaVersion': 1, 'scope': 'hash-pinned installed Python runtime distributions',
              'legalApproval': False, 'lockSha256': hashlib.sha256(raw).hexdigest(),
              'excluded': ['OS and Python runtime', 'ffmpeg and native runtime', 'mobile and admin dependencies',
                           'provider SDK terms', 'application images/fonts and other assets'],
              'packages': packages}
    return report, '\n'.join(notices)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lock', type=Path, default=Path('requirements.lock'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report, notices = collect(args.lock)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output/'inventory.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    (args.output/'NOTICES.txt').write_text(notices, encoding='utf-8')
    print('Collected installed license evidence for', len(report['packages']), 'pinned runtime packages; legal approval remains separate.')


if __name__ == '__main__':
    main()
