"""Optional native reproduction of recorded compensation circuits.

With no arguments, this lists the recorded cases without launching simulations.
Use --case FAMILY/NAME for selected cases or --all for the entire recorded grid.
The recorded data remain untouched. New results use a timestamped directory.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import numpy as np
from runtime_support import PROJECT,find_ngspice,verify_models,record_simulator,relative_library_path,check_native_completion

RECORD=PROJECT/'results/recorded/compensation_screen_summary.json'
NUM=r'([+-]?[\d.]+(?:e[+-]?\d+)?)'

def native(executable,folder,name,base,control):
    folder.mkdir(parents=True,exist_ok=True)
    source=base.replace('__SKY130_MODEL_LIBRARY__',relative_library_path(folder))+control
    deck=folder/(name+'.spice')
    deck.write_text(source)
    p=subprocess.run([str(executable),'-b',deck.name],cwd=folder,capture_output=True,text=True,timeout=120)
    log=p.stdout+'\n'+p.stderr
    (folder/(name+'.log')).write_text(log)
    check_native_completion(p,log)
    return log

def ac_result(path):
    data=np.loadtxt(path,skiprows=1)
    if len(data)<2:raise RuntimeError('The native AC table is empty.')
    h=data[:,1]+1j*data[:,2]
    result=[]
    for f in [1,1e3,1e4,1e5,1e6,3e6,1e7]:
        z=np.interp(np.log10(f),np.log10(data[:,0]),h.real)+1j*np.interp(np.log10(f),np.log10(data[:,0]),h.imag)
        result.append(dict(frequency_Hz=f,real=float(z.real),imag=float(z.imag),dB=float(20*np.log10(abs(z)))))
    band=(data[:,0]>=1e6*(1-1e-12))&(data[:,0]<=1e7*(1+1e-12))
    i=np.flatnonzero(band)[np.argmax(np.abs(h[band]))]
    return dict(samples=result,worst_sampled_1_to_10_MHz_dB=float(20*np.log10(abs(h[i]))),worst_sampled_frequency_Hz=float(data[i,0]))

def reproduce(executable,root,case):
    base=case['netlist_template']
    if hashlib.sha256(base.encode()).hexdigest()!=case['template_sha256']:
        raise RuntimeError('Recorded netlist template hash mismatch.')
    folder=root/case['family']/case['name']
    report=dict(case_id=case['case_id'],COUT_F=case['COUT_F'],evidence='New native public SKY130 result. No loop margin or PVT claim.')
    points=case.get('native_AC_points_per_decade',80)
    control=f'\n.control\nset noaskquit\nset numdgt=15\nset wr_singlescale\nset wr_vecnames\nop\nprint v(O) v(G) v(C) i(VIN) i(VREF)\nac dec {points} 1 1e8\nwrdata supply_ac.txt v(O) v(G) v(C)\nquit\n.endc\n.end\n'
    try:
        native(executable,folder,'supply',base,control)
        report['AC']=dict(status='success',**ac_result(folder/'supply_ac.txt'))
    except Exception as exc:
        report['AC']=dict(status='failed',error=str(exc))
    poles=[]
    for load in [0,.005,.05]:
        loadbase,count=re.subn(r'(?im)^ILOAD\s+O\s+0\s+DC\s+\S+\s*$',f'ILOAD O 0 DC {load:g}',base)
        if count!=1:raise RuntimeError('Expected exactly one external DC load.')
        point=dict(load_A=load)
        try:
            log=native(executable,folder/f'load_{round(load*1e6)}uA','closed_pz',loadbase,
                '\n.control\nset noaskquit\nset numdgt=15\nop\npz VIN 0 O 0 vol pz\nprint all\nquit\n.endc\n.end\n')
            roots=[dict(real_per_s=float(a),imag_per_s=float(b)) for a,b in re.findall(r'pole\(\d+\)\s*=\s*'+NUM+r'\s*,\s*'+NUM,log,re.I)]
            if not roots:raise RuntimeError('Native PZ returned an empty pole set.')
            point.update(status='success',poles=roots,RHP_pole_count=sum(x['real_per_s']>0 for x in roots))
        except Exception as exc:point.update(status='failed',error=str(exc),RHP_pole_count=None)
        poles.append(point)
    report['pole_diagnostics']=poles
    report['all_tested_poles_LHP']=all(p['status']=='success' and p['RHP_pole_count']==0 for p in poles)
    report['acceptance_boundary']='Closed poles do not establish loop margin or successful large signal recovery. A low AC value at an unstable point is not accepted regulator PSR.'
    (folder/'reproduction.json').write_text(json.dumps(report,indent=2))
    return report

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',action='append',default=[],help='Recorded FAMILY/NAME to reproduce. May be repeated.')
    parser.add_argument('--all',action='store_true',help='Reproduce every recorded configuration.')
    parser.add_argument('--list',action='store_true',help='List cases without launching a simulator.')
    args=parser.parse_args()
    data=json.loads(RECORD.read_text())
    if args.list or not (args.case or args.all):
        for row in data['cases']:
            print(row['case_id'],row['worst_sampled_1_to_10_MHz_dB'])
        return
    ids={x['case_id'] for x in data['cases']}
    unknown=set(args.case)-ids
    if unknown:parser.error('Unknown cases: '+', '.join(sorted(unknown)))
    chosen=data['cases'] if args.all else [x for x in data['cases'] if x['case_id'] in args.case]
    verify_models();executable=find_ngspice();record_simulator(executable)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    root=PROJECT/'results/native/compensation_grid'/stamp
    root.mkdir(parents=True,exist_ok=False)
    results=[]
    for case in chosen:
        row=reproduce(executable,root,case);results.append(row)
        print(case['case_id'],row['AC']['status'],row['all_tested_poles_LHP'])
    (root/'summary.json').write_text(json.dumps(dict(evidence='New optional native reproduction. Recorded summary preserved.',cases=results),indent=2))
    print(root.relative_to(PROJECT).as_posix())

if __name__=='__main__':main()
