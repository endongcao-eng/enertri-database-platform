"""Consistent PostgreSQL + uploads backup, offline verify, isolated restore drill.
Run at project root. Never restores into an existing database. Requires Docker for
backup/drill; verify works offline. Plaintext output is private (0700 directory).
"""
import argparse,csv,fcntl,hashlib,io,json,os,subprocess,tarfile,tempfile,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def run(args,**kwargs):
    return subprocess.run(args,cwd=ROOT,check=True,**kwargs)

def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def verify(folder):
    folder=Path(folder).resolve()
    manifest=json.loads((folder/'manifest.json').read_text())
    if set(manifest['sha256'])!={'database.dump','uploads.tar.gz'}:raise ValueError('Unexpected manifest file list')
    for name,value in manifest['sha256'].items():
        if (folder/name).is_symlink() or digest(folder/name)!=value:raise ValueError('Backup checksum mismatch')
    with tarfile.open(folder/'uploads.tar.gz') as tar:
        for item in tar:
            path=Path(item.name)
            if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0]!='uploads' or not (item.isfile() or item.isdir()):
                raise ValueError('Unsafe archive member')
    return manifest

def backup(destination):
    dest=Path(destination).resolve()
    if dest.is_relative_to(ROOT/'uploads'):raise ValueError('Backup cannot be stored inside uploads')
    dest.mkdir(mode=0o700,parents=True,exist_ok=False)
    running=[]
    with open(ROOT/'.backup.lock','w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        current=run(['docker','compose','ps','--status','running','--services'],capture_output=True,text=True).stdout.split()
        if 'db' not in current:raise ValueError('Database is not running')
        running=[x for x in ['caddy','backend','worker'] if x in current]
        try:
            if running:run(['docker','compose','stop',*running])
            with open(dest/'database.dump','wb') as f:
                run(['docker','compose','exec','-T','db','pg_dump','-Fc','-U','enertri_user','-d','enertri'],stdout=f)
            uploads=ROOT/'uploads'
            for file in uploads.rglob('*'):
                if file.is_symlink():raise ValueError('Symlinks in uploads must be reviewed before backup')
            with tarfile.open(dest/'uploads.tar.gz','w:gz') as tar:tar.add(uploads,arcname='uploads')
            manifest={'format':1,'created_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'version':(ROOT/'VERSION').read_text().strip(),'sha256':{name:digest(dest/name) for name in ['database.dump','uploads.tar.gz']}}
            (dest/'manifest.json').write_text(json.dumps(manifest,indent=2))
            for file in dest.iterdir():file.chmod(0o600)
            verify(dest)
        finally:
            if running:run(['docker','compose','start',*running])
    print('Backup verified:',dest)

def drill(folder):
    folder=Path(folder).resolve();verify(folder)
    name='enertri-restore-drill-'+uuid.uuid4().hex[:10]
    created=False
    with tempfile.TemporaryDirectory(prefix='enertri-restore-') as scratch:
        dest=Path(scratch)
        with tarfile.open(folder/'uploads.tar.gz') as tar:tar.extractall(dest,filter='data')
        try:
            run(['docker','run','--name',name,'--network','none','-e','POSTGRES_HOST_AUTH_METHOD=trust','-d','postgres:16'],capture_output=True)
            created=True
            for _ in range(60):
                probe=subprocess.run(['docker','exec',name,'pg_isready','-U','postgres'],capture_output=True)
                if probe.returncode==0:break
                time.sleep(1)
            else:raise RuntimeError('Restore database did not start')
            run(['docker','exec',name,'createdb','-U','postgres','enertri'])
            with open(folder/'database.dump','rb') as f:
                run(['docker','exec','-i',name,'pg_restore','--exit-on-error','--no-owner','--no-privileges','-U','postgres','-d','enertri'],stdin=f)
            sql="COPY (SELECT storage_path,sha256 FROM workspace_files WHERE deleted_at IS NULL) TO STDOUT WITH CSV"
            records=run(['docker','exec',name,'psql','-v','ON_ERROR_STOP=1','-U','postgres','-d','enertri','-c',sql],capture_output=True,text=True).stdout
            checked=0
            for path,sha in csv.reader(io.StringIO(records)):
                rel=Path(path).relative_to('/app/media')
                if '..' in rel.parts:raise ValueError('Unsafe stored path')
                file=dest/'uploads'/rel
                if not file.is_file() or digest(file)!=sha:raise ValueError('Restored file missing or checksum mismatch')
                checked+=1
            counts=run(['docker','exec',name,'psql','-v','ON_ERROR_STOP=1','-U','postgres','-d','enertri','-Atc','SELECT count(*) FROM users; SELECT count(*) FROM terms; SELECT count(*) FROM student_evidence; SELECT version_num FROM alembic_version;'],capture_output=True,text=True).stdout.splitlines()
            print(json.dumps({'restore':'passed','file_hashes_checked':checked,'users_terms_evidence_revision':counts}))
        finally:
            if created:run(['docker','rm','-f',name],capture_output=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['backup','verify','drill']);p.add_argument('folder');a=p.parse_args()
    if a.action=='backup':backup(a.folder)
    elif a.action=='verify':verify(a.folder);print('Checksum and archive safety checks passed')
    else:drill(a.folder)
