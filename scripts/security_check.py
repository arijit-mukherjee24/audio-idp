"""Check publishable/index files and optional Git history without printing secrets.

Only the --install option downloads anything: a pinned, checksum-verified official
Gitleaks release into ignored .run/tools. No files or credentials leave this machine.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
VERSION='8.30.1'
ARCHIVES={
    ('Windows','x64'):('zip','d29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e'),
    ('Linux','x64'):('tar.gz','551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb'),
    ('Linux','arm64'):('tar.gz','e4a487ee7ccd7d3a7f7ec08657610aa3606637dab924210b3aee62570fb4b080'),
    ('Darwin','x64'):('tar.gz','dfe101a4db2255fc85120ac7f3d25e4342c3c20cf749f2c20a18081af1952709'),
    ('Darwin','arm64'):('tar.gz','b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5'),
}
PRIVATE_DIRS={'.aws','.azure','.kube','.data','.models','.local','.run','.venv','venv','env',
              '__pycache__','uploads','exports','backups'}
PRIVATE_SUFFIXES={'.pem','.key','.p12','.pfx','.db','.sqlite','.sqlite3','.wav','.mp3','.m4a',
                  '.flac','.ogg','.webm','.mp4','.bin','.safetensors','.onnx','.pt','.pth','.log','.pyc'}
SENSITIVE_NAME=re.compile(r'(secret|password|passwd|token|credential|private.?key|access.?key)',re.I)


class SecurityCheckError(ValueError):
    """An actionable diagnostic that is safe to display without secret contents."""


def git(*args,check=True):
    return subprocess.run(['git','-C',str(ROOT),*args],capture_output=True,check=check)


def private_path(name):
    path=PurePosixPath(name.replace('\\','/'))
    parts=[p.casefold() for p in path.parts]
    filename=parts[-1] if parts else ''
    return (path.is_absolute() or '..' in parts or any(p in PRIVATE_DIRS for p in parts)
            or (filename=='.env' or filename.startswith('.env.') or filename=='.envrc') and filename!='.env.example'
            or filename=='secrets.toml' or filename=='credentials' or filename.startswith('credentials.')
            or filename.startswith(('id_rsa','id_ed25519')) or path.suffix.casefold() in PRIVATE_SUFFIXES
            or '.sqlite3-' in filename or '.db-' in filename)


def environment_secrets(environment):
    # Match actual values as well as Gitleaks patterns, without recording values.
    return {v.encode() for k,v in environment.items() if SENSITIVE_NAME.search(k) and len(v)>=8
            and not v.startswith(('<','YOUR_','your_','REPLACE_'))}


def environment_match(content,values):
    return any(value in content for value in values)


def install_tool(allow_download):
    system=platform.system()
    machine=platform.machine().lower()
    arch={'amd64':'x64','x86_64':'x64','aarch64':'arm64','arm64':'arm64'}.get(machine,machine)
    if (system,arch) not in ARCHIVES:raise SecurityCheckError('No pinned Gitleaks build for this operating system/architecture.')
    extension,checksum=ARCHIVES[system,arch]
    filename=f'gitleaks_{VERSION}_{system.lower()}_{arch}.{extension}'
    folder=ROOT/'.run'/'tools';folder.mkdir(parents=True,exist_ok=True)
    archive=folder/filename
    if not archive.exists():
        if not allow_download:raise SecurityCheckError('Security scanner not installed. Run: python scripts/security_check.py --install')
        url=f'https://github.com/gitleaks/gitleaks/releases/download/v{VERSION}/{filename}'
        print(f'Downloading official Gitleaks {VERSION} (checksum verification required).')
        with urllib.request.urlopen(url,timeout=60) as response:content=response.read(40_000_001)
        if len(content)>40_000_000:raise SecurityCheckError('Scanner archive exceeds expected size.')
        if hashlib.sha256(content).hexdigest()!=checksum:raise SecurityCheckError('Scanner checksum mismatch; download rejected.')
        archive.write_bytes(content)
    content=archive.read_bytes()
    if hashlib.sha256(content).hexdigest()!=checksum:raise SecurityCheckError('Cached scanner checksum mismatch; remove the cached archive and retry --install.')
    executable='gitleaks.exe' if system=='Windows' else 'gitleaks'
    if extension=='zip':
        with zipfile.ZipFile(io.BytesIO(content)) as bundle:binary=bundle.read(executable)
    else:
        with tarfile.open(fileobj=io.BytesIO(content),mode='r:gz') as bundle:
            member=bundle.getmember(executable)
            if not member.isfile():raise SecurityCheckError('Invalid scanner executable in archive.')
            binary=bundle.extractfile(member).read()
    target=folder/executable
    # Verify the cached executable against the verified archive. Avoid rewriting a
    # valid executable: Windows may briefly retain its file lock after another hook.
    if not target.exists() or hashlib.sha256(target.read_bytes()).digest()!=hashlib.sha256(binary).digest():
        target.write_bytes(binary)
    target.chmod(0o700)
    return target


def candidates(mode):
    if mode=='staged':result=git('diff','--cached','--name-only','--diff-filter=ACMR','-z')
    elif mode=='tracked':result=git('ls-files','--cached','-z')
    else:result=git('ls-files','--cached','--others','--exclude-standard','-z')
    return sorted(set(p.decode('utf-8') for p in result.stdout.split(b'\0') if p))


def scan(tool,arguments,report,base=None):
    result=subprocess.run([str(tool),*arguments,'--config',str(ROOT/'.gitleaks.toml'),
        '--redact=100','--no-banner','--report-format','json','--report-path',str(report)],
        cwd=ROOT,capture_output=True)
    if result.returncode not in (0,1):raise SecurityCheckError('Gitleaks could not complete; check scanner installation and Git history access.')
    findings=json.loads(report.read_text(encoding='utf-8')) if report.exists() else []
    for item in findings:
        path=item.get('File','unknown')
        if base:
            try:path=str(Path(path).relative_to(base))
            except ValueError:pass
        print(f"Secret detected: {path}:{item.get('StartLine',0)} [{item.get('RuleID','secret')}] (value hidden)")
    return result.returncode==0 and not findings


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument('--staged',action='store_true',help='Check exact staged/index content before a commit.')
    modes.add_argument('--tracked',action='store_true',help='Check every tracked/index file, including force-added ignored files.')
    parser.add_argument('--install',action='store_true',help='Allow first download of the pinned scanner.')
    parser.add_argument('--history',action='store_true',help='Also scan all reachable Git history with Gitleaks.')
    args=parser.parse_args(argv)
    try:
        repository=git('rev-parse','--show-toplevel',check=False)
        if repository.returncode:
            raise SecurityCheckError('Run git init in this project before the repository security check.')
        if Path(repository.stdout.decode('utf-8').strip()).resolve()!=ROOT.resolve():
            raise SecurityCheckError('Run this check from a standalone project repository, not a parent repository.')
        mode='staged' if args.staged else 'tracked' if args.tracked else 'working'
        names=candidates(mode)
        blocked=[name for name in names if private_path(name)]
        for name in blocked:print(f'Blocked private/runtime file: {name}')
        if blocked:return 1
        values=environment_secrets(os.environ)
        runtime=ROOT/'.run';runtime.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='secret-check-',dir=runtime) as temporary:
            temporary=Path(temporary);snapshot=temporary/'files';snapshot.mkdir()
            for name in names:
                path=ROOT/name
                # Refuse links, including staged links, rather than following them into private files.
                indexed=git('ls-files','--stage','--',name).stdout
                if path.is_symlink() or indexed.startswith(b'120000 '):raise SecurityCheckError(f'Symbolic link requires manual review: {name}')
                if mode=='working' and not path.exists():continue
                content=git('show',':'+name).stdout if mode!='working' else path.read_bytes()
                if environment_match(content,values):raise SecurityCheckError(f'An active environment secret appears in {name} (value hidden).')
                if len(content)>5_000_000:raise SecurityCheckError(f'File exceeds the 5 MB source limit: {name}')
                destination=snapshot/name;destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(content)
            tool=install_tool(args.install)
            if not scan(tool,['dir',str(snapshot)],temporary/'files-report.json',snapshot):return 1
            if args.history and git('rev-parse','--verify','HEAD',check=False).returncode==0:
                if not scan(tool,['git','--log-opts=--all',str(ROOT)],temporary/'history-report.json'):return 1
            print(f'Security check passed: {len(names)} {mode} files; no detected secrets or private/runtime files.')
            if args.history and git('rev-parse','--verify','HEAD',check=False).returncode:
                print('History scan skipped: this repository has no commits yet.')
        return 0
    except SecurityCheckError as exc:
        print(str(exc),file=sys.stderr)
        return 2
    except (OSError,ValueError,subprocess.SubprocessError,zipfile.BadZipFile,tarfile.TarError):
        # Avoid echoing subprocess output, URLs containing credentials, or exception payloads.
        print('Security check failed. Verify Git setup, file policy, scanner availability/checksum, and environment-secret matches.',file=sys.stderr)
        return 2


if __name__=='__main__':sys.exit(main())
