from __future__ import annotations
import os, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    env={**os.environ,'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
    print('RUNNING existing deterministic Windows V1 acceptance', flush=True)
    subprocess.run([sys.executable,str(ROOT/'scripts/windows_v1_acceptance.py')],cwd=ROOT,env=env,check=True)
    print('TRUST_RH_RC3_WINDOWS_ACCEPTANCE=PASS')
if __name__=='__main__': main()
