"""Copied to the delivery root; each mode checks the exact source inventory."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

def inventory_hash(root):return hashlib.sha256((root/'SOURCE_INVENTORY.json').read_bytes()).hexdigest()

def verify_inventory(root):
    root=Path(root)
    expected=json.loads((root/'SOURCE_INVENTORY.json').read_text(encoding='utf-8'))['files']
    actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()
        and 'runs' not in p.relative_to(root).parts and '__pycache__' not in p.relative_to(root).parts
        and p.name!='SOURCE_INVENTORY.json'}
    if actual!=set(expected):raise ValueError('Bundle source inventory differs')
    for name,sha in expected.items():
        p=root/name
        if p.is_symlink() or not p.resolve().is_relative_to(root.resolve()) or hashlib.sha256(p.read_bytes()).hexdigest()!=sha:
            raise ValueError('Changed bundled source')

def write_qualification(root):
    target=root/'runs/offline_qualified.json';target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps({'result':'PASS','source_inventory_sha256':inventory_hash(root),
        'python_executable':str(Path(sys.executable).resolve()),'python_version':list(sys.version_info[:3])},indent=2)+'\n')

def require_qualification(root):
    try:
        saved=json.loads((root/'runs/offline_qualified.json').read_text(encoding='utf-8'))
        if (saved['result']!='PASS' or saved['source_inventory_sha256']!=inventory_hash(root)
                or saved['python_executable']!=str(Path(sys.executable).resolve())
                or saved['python_version']!=list(sys.version_info[:3])):raise ValueError()
    except Exception:raise ValueError('Run command 39 successfully in this package and environment before command 40') from None

def main(root=None):
    root=Path(__file__).resolve().parent if root is None else Path(root)
    try:
        verify_inventory(root)
        if len(sys.argv)==2 and sys.argv[1]=='offline':
            (root/'runs/offline_qualified.json').unlink(missing_ok=True)
            print('OFFLINE installed-client probe qualification. Synthetic credentials/SDK only; no API or password.',flush=True)
            result=subprocess.call([sys.executable,'-I','-B',str(root/'coordinator/experiments/installed_startup_20261023/verify.py'),
                '--output-root',str(root/'runs/offline')])
            if result:return result
            verify_inventory(root);write_qualification(root)
            print('Command 39 PASS. Command 40 may now inspect the installed client and request one SPY quote.',flush=True)
            return 0
        if len(sys.argv)==3 and sys.argv[1]=='installed':
            require_qualification(root)
            return subprocess.call([sys.executable,'-I','-B',str(root/'coordinator/experiments/installed_startup_20261023/probe.py'),
                '--ecfg',sys.argv[2],'--output-root',str(root/'runs/installed_client')])
        raise ValueError('Use command 39 or command 40 with an explicit encrypted-config path')
    except KeyboardInterrupt:return 130
    except Exception as error:
        # Messages here are fixed local guard text, never SDK exception bodies.
        if isinstance(error,ValueError) and str(error).startswith(('Bundle source','Changed bundled','Run command','Use command')):
            print(str(error))
        else:print('Launcher failed; inspect package inputs. No provider error text retained.')
        return 64

if __name__=='__main__':raise SystemExit(main())
