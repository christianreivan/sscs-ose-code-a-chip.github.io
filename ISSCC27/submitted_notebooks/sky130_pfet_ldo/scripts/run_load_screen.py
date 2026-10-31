"""Run the fixed SKY130 core at declared loads without cancellation retuning."""
from pathlib import Path
import concurrent.futures
import hashlib
import json
import os
import re
import subprocess
import time

ROOT=Path(__file__).resolve().parent
from runtime_support import PROJECT, find_ngspice, verify_models, record_simulator, relative_library_path, prepare_native_outputs, check_native_completion
EXE=find_ngspice()
LIBRARY=verify_models()
SOURCE=PROJECT/'circuits/core_extracted.spice'
BASE=SOURCE.read_text()
DEST=PROJECT/'results/load_screen'
DEST.mkdir(exist_ok=True)
CASES=[('tt',27,x) for x in [0,.0001,.001,.005,.01,.025,.05]]
CASES += [(corner,temp,load) for corner in ['ss','ff'] for temp in [0,85] for load in [0,.05]]

def run(case):
    corner,temp,load=case
    name=f'{corner}_{temp}C_{round(load*1e6)}uA'
    out=DEST/name
    out.mkdir(exist_ok=True)
    text=re.sub(r'(?m)^ILOAD .+$',f'ILOAD O 0 DC {load:.12g}',BASE.replace('../models/sky130_mos.lib.spice',relative_library_path(out)))
    text=re.sub(r'(?m)^\.temp .+$',f'.temp {temp}',text)
    text=re.sub(r'(?m)^(\.lib .+) tt$',r'\1 '+corner,text)
    text=text.replace('core_extracted_op.raw','op.raw')
    (out/'input.spice').write_text(text)
    outputs=prepare_native_outputs(text,out)
    start=time.perf_counter()
    env=os.environ.copy()
    env['OMP_NUM_THREADS']='2'
    result=subprocess.run([str(EXE),'-b','input.spice'],cwd=out,capture_output=True,text=True,timeout=45,env=env)
    log=result.stdout+'\n'+result.stderr
    (out/'run.log').write_text(log)
    check_native_completion(result,log,outputs)
    values={k.strip().lower():float(v) for k,v in re.findall(r'^\s*([^\n=]+?)\s*=\s*([+-]?[\d.]+(?:e[+-]?\d+)?)\s*$',result.stdout,re.M|re.I)}
    fail=bool(result.returncode or re.search(r'(?im)^\s*(?:fatal|error on line|error:)',log))
    row=dict(name=name,corner=corner,temperature_C=temp,external_load_A=load,returncode=result.returncode,
             seconds=time.perf_counter()-start,netlist_sha256=hashlib.sha256(text.encode()).hexdigest(),status='FAILED' if fail else 'DC_COMPLETE')
    if not fail:
        row.update(VOUT_V=values['v(o)'],VG_V=values['v(g)'],VC_V=values['v(c)'],
                   output_error_V=values['v(o)']-.8,input_current_A=-values['i(vin)'],
                   reference_current_A=-values['i(vref)'],core_overhead_A=-values['i(vin)']-load,
                   M2_margin_V=abs(values['@m.xm2.msky130_fd_pr__nfet_01v8[vds]'])-abs(values['@m.xm2.msky130_fd_pr__nfet_01v8[vdsat]']),
                   pass_gm_S=values['@m.xmp.msky130_fd_pr__pfet_01v8[gm]'],
                   pass_ro_ohm=1/values['@m.xmp.msky130_fd_pr__pfet_01v8[gds]'])
    (out/'result.json').write_text(json.dumps(row,indent=2))
    return row

def main():
    simulator=record_simulator(EXE)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        rows=list(pool.map(run,CASES))
    receipt=dict(evidence='Fresh local native ngspice SKY130 fixed core DC screen.', simulator=simulator,
                 source_netlist_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                 fixed_biases=True,fixed_geometry=True,ideal_quiet_bias_ports=True,
                 source_cancellation_present=False,rows=rows,
                 limitations=['DC results only','No physical bias generator or its power',
                              'No complete PVT qualification','No layout parasitics',
                              'No claim that the cancellation architecture is validated'])
    (PROJECT/'results/load_screen.json').write_text(json.dumps(receipt,indent=2))
    print(json.dumps(rows,indent=2))
    if any(row['status']!='DC_COMPLETE' for row in rows):
        raise RuntimeError('At least one native DC load case failed.')

if __name__=='__main__':main()
