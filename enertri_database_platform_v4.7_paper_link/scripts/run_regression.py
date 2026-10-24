"""Legacy tests mutate process environment; isolate each module."""
import subprocess
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
failed=[]
for path in sorted((root/"backend/tests").glob("test_*.py")):
    name="tests."+path.stem
    result=subprocess.run([sys.executable,"-m","unittest",name],cwd=root/"backend")
    if result.returncode: failed.append(name)
print("Failed modules:",failed)
sys.exit(bool(failed))
