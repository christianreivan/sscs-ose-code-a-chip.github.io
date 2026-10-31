"""Native fixed output pass cell experiment, distinct from regulator PSR."""
from pathlib import Path
import json
import re
import subprocess
import numpy as np

HERE = Path(__file__).resolve().parent
from runtime_support import PROJECT, find_ngspice, verify_models, record_simulator, relative_library_path, prepare_native_outputs, check_native_completion
EXE=find_ngspice()
LIB=verify_models()
SIMULATOR=record_simulator(EXE)
OP = json.loads((PROJECT/'results/recorded/refined_operating_point.json').read_text())
MP = OP['devices'][0]
DEST = PROJECT/'results/pass_disturbance'
DEST.mkdir(exist_ok=True)
k = 1 + 1/(MP['gm_S']*MP['ro_ohm'])
traces = {}
for name, gain in [('fixed_gate',0),('unity_tracking',1),('ro_corrected',k)]:
    folder = DEST/name
    folder.mkdir(exist_ok=True)
    deck = f'''SKY130 fixed output pass cell supply disturbance
.lib "{relative_library_path(folder)}" tt
.temp 27
.option reltol=1e-6 abstol=1e-13 vntol=1e-8
VIN VIN 0 DC 1.2 AC 1
VG G 0 DC {OP['voltages_V']['G']:.15g} AC {gain:.15g}
VO O 0 DC {OP['voltages_V']['O']:.15g} AC 0
XMP O G VIN VIN sky130_fd_pr__pfet_01v8 w=5 l=.15 nf=1 m=1923
.control
set noaskquit
set numdgt=15
set wr_singlescale
set wr_vecnames
ac dec 50 1 1e8
wrdata response.txt i(VO)
quit
.endc
.end
'''
    (folder/'input.spice').write_text(deck)
    outputs=prepare_native_outputs(deck,folder)
    run = subprocess.run([str(EXE),'-b','input.spice'],cwd=folder,capture_output=True,text=True,timeout=30)
    log = run.stdout+'\n'+run.stderr
    (folder/'run.log').write_text(log)
    check_native_completion(run,log,outputs)
    if run.returncode or re.search(r'(?im)^\s*(?:fatal|error:|error on line|.*aborted)',log):
        raise RuntimeError(log[-3000:])
    d = np.loadtxt(folder/'response.txt',skiprows=1)
    f=d[:,0]
    traces[name]=d[:,1]+1j*d[:,2]
target = traces['fixed_gate']/(traces['fixed_gate']-traces['unity_tracking'])
rows=[]
for frequency in [1,1e3,1e4,1e5,1e6,3e6,1e7,1e8]:
    j=int(np.argmin(abs(np.log(f/frequency))))
    row=dict(frequency_Hz=float(f[j]),ideal_null_gate_gain_real=float(target[j].real),
             ideal_null_gate_gain_imag=float(target[j].imag))
    for name,trace in traces.items():
        row[name+'_current_per_supply_A_per_V']=float(abs(trace[j]))
        row[name+'_relative_to_fixed_gate_dB']=float(20*np.log10(abs(trace[j]/traces['fixed_gate'][j])))
    rows.append(row)
result = dict(evidence='Native SKY130 isolated pass cell AC with output voltage clamped.',simulator=SIMULATOR,
    DC_gate_V=OP['voltages_V']['G'], DC_output_V=OP['voltages_V']['O'],
    gm_S=MP['gm_S'],ro_ohm=MP['ro_ohm'],low_frequency_correction_gain=k,
    rows=rows, limitations=['This measures pass drain current, not connected LDO PSR',
        'Gate tracking is imposed by ideal AC sources',
        'No realizable circuit claim for the complex ideal null ratio',
        'Default zero diffusion areas and perimeters'])
(DEST/'result.json').write_text(json.dumps(result,indent=2))
print(json.dumps({'evidence':result['evidence'],'low_frequency_correction_gain':k,'interpretation':'Ideal imposed tracking current experiment. Not connected LDO PSR.'},indent=2))
