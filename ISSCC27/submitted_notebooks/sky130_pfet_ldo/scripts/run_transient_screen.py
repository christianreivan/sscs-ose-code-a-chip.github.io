"""Bounded native load transition screen for the frozen refined circuit."""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import numpy as np

HERE = Path(__file__).resolve().parent
from runtime_support import PROJECT, find_ngspice, verify_models, record_simulator, relative_library_path, prepare_native_outputs, check_native_completion
EXE = find_ngspice()
verify_models()
simulator = record_simulator(EXE)
SOURCE = PROJECT / 'circuits/refined/core_seed.spice'
OUT = PROJECT / 'results/transient_screen'
OUT.mkdir(exist_ok=True)
base = SOURCE.read_text().split('.control')[0]
base = re.sub(r'(?m)^\.lib .+ tt$', f'.lib "{relative_library_path(OUT)}" tt', base)
base = re.sub(r'(?m)^ILOAD .*$',
              'ILOAD O 0 PWL(0 .005 2u .005 2.1u .05 7.1u .05 7.2u .005 12u .005)', base)
text = base + '''.control
set noaskquit
set numdgt=15
set wr_singlescale
set wr_vecnames
tran 2n 12u
wrdata transient.txt v(O) v(G) v(C) i(VIN)
quit
.endc
.end
'''
(OUT/'input.spice').write_text(text)
outputs=prepare_native_outputs(text,OUT)
env = os.environ.copy()
env['OMP_NUM_THREADS'] = '2'
p = subprocess.run([str(EXE), '-b', 'input.spice'], cwd=OUT, env=env,
                   capture_output=True, text=True, timeout=90)
log = p.stdout + '\n' + p.stderr
(OUT/'run.log').write_text(log)
check_native_completion(p,log,outputs)
if p.returncode or re.search(r'(?im)^\s*(?:fatal|error:|error on line|.*aborted)', log):
    raise RuntimeError(log[-4000:])
d = np.loadtxt(OUT/'transient.txt', skiprows=1)
t, o, g, c = d[:,0], d[:,1], d[:,2], d[:,3]
rise = (t>=2e-6) & (t<7.1e-6)
fall = t>=7.1e-6
receipt = dict(
    evidence='Fresh local native SKY130 TT transient at 27 C.', simulator=simulator,
    input_sha256=hashlib.sha256(text.encode()).hexdigest(),
    supply_V=1.2, reference_V=.8, initial_load_A=.005,
    high_load_A=.05, rise_and_fall_s=100e-9,
    output_capacitance_F=200e-12, compensation_capacitance_F=100e-12,
    CFF_F=0, max_step_s=2e-9, data_points=len(t),
    initial_output_V=float(o[0]), final_output_V=float(o[-1]),
    rising_load_minimum_output_V=float(o[rise].min()),
    falling_load_maximum_output_V=float(o[fall].max()),
    minimum_gate_V=float(g.min()), maximum_gate_V=float(g.max()),
    limitations=['Quiet ideal bias and reference sources',
                 'Default zero diffusion areas and perimeters',
                 'Not startup or load range qualification'])
(OUT/'result.json').write_text(json.dumps(receipt, indent=2))
print(json.dumps(receipt, indent=2))
