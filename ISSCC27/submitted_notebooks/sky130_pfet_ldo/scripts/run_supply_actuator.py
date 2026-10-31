"""Exactly one fixed supply sourced actuator candidate, with no retuning."""
import hashlib
import json
import re
import subprocess
import numpy as np
from runtime_support import PROJECT, find_ngspice, verify_models, record_simulator, relative_library_path, prepare_native_outputs, check_native_completion
EXE=find_ngspice()
verify_models()
SIMULATOR=record_simulator(EXE)

BASE=PROJECT/'circuits/refined'
OUT=PROJECT/'results/supply_actuator'
OUT.mkdir(exist_ok=True)
old=(BASE/'core_seed.spice').read_text().split('.control',1)[0]
expected='XMF D_MF C O O sky130_fd_pr__pfet_01v8 w=5 l=0.15 nf=1 m=100'
replacement='XMF D_MF C VIN VIN sky130_fd_pr__pfet_01v8 w=5 l=1.0 nf=1 m=116'
if old.count(expected)!=1:raise AssertionError('Frozen MF line not found exactly once')
base=old.replace(expected,replacement)
(OUT/'connection_change.json').write_text(json.dumps(dict(
    evidence='Prespecified exact physical change. No automatic bias or geometry tuning.',
    old=expected,new=replacement,all_other_values_fixed=True,
    removed_function='Original output sourced local FVF action',
    pretest_hypothesis_path='references/supply_actuator_hypothesis.tex',
    pretest_hypothesis_sha256=hashlib.sha256((PROJECT/'references/supply_actuator_hypothesis.tex').read_bytes()).hexdigest()),indent=2))

def run(folder,name,source):
    folder.mkdir(exist_ok=True)
    source=re.sub(r'(?m)^\.lib .+ tt$',f'.lib "{relative_library_path(folder)}" tt',source)
    (folder/(name+'.spice')).write_text(source)
    outputs=prepare_native_outputs(source,folder)
    p=subprocess.run([str(EXE),'-b',name+'.spice'],cwd=folder,capture_output=True,text=True,timeout=35)
    log=p.stdout+'\n'+p.stderr
    (folder/(name+'.log')).write_text(log)
    errors=[x.strip() for x in log.splitlines() if re.search(r'aborted|\berror\b|shorted on the way',x,re.I)]
    check_native_completion(p,log,outputs)
    return p,log,errors

cmd=['set numdgt=15','op','print v(O) v(G) v(C) v(X) v(Y) v(A)','print i(VIN) i(VREF) i(VS_MP) i(VS_MF) i(VS_PH) i(VS_NB) i(VS_L2)']
for name,kind in [('M2','nfet_01v8'),('MF','pfet_01v8'),('MP','pfet_01v8'),('NB','nfet_01v8')]:
    ident='m.x'+name.lower()+'.msky130_fd_pr__'+kind
    cmd.append('print '+' '.join('@'+ident+'['+f+']' for f in ['id','gm','gds','vdsat','vds','vgs']))
control='\n.control\nset noaskquit\n'+'\n'.join(cmd)+'\nquit\n.endc\n.end\n'
rows=[]
for load in [0.,.0001,.001,.005,.01,.025,.05]:
    folder=OUT/('load_'+str(round(load*1e6))+'uA')
    circuit=base.replace('ILOAD O 0 DC .05',f'ILOAD O 0 DC {load:.12g}')+control
    p,log,errors=run(folder,'core',circuit)
    values={k.strip().lower():float(x) for k,x in re.findall(r'^\s*([^\n=]+?)\s*=\s*([+-]?[\d.]+(?:e[+-]?\d+)?)\s*$',log,re.M|re.I)}
    v={k:values['v('+k.lower()+')'] for k in ['O','G','C','X','Y','A']}
    field=lambda name,kind,f:values['@m.x'+name.lower()+'.msky130_fd_pr__'+kind+'['+f+']']
    row=dict(external_load_A=load,returncode=p.returncode,errors=errors,voltages_V=v,
       input_current_A=-values['i(vin)'],reference_current_A=-values['i(vref)'],
       MP_current_A=-values['i(vs_mp)'],actuator_current_into_gate_A=-values['i(vs_mf)'],
       PH_current_into_gate_A=-values['i(vs_ph)'],NB_current_from_gate_A=values['i(vs_nb)'],
       M2_VDS_V=v['C']-v['Y'],M2_VDSAT_V=abs(field('M2','nfet_01v8','vdsat')),
       actuator_VSD_V=1.2-v['G'],actuator_VDSAT_V=abs(field('MF','pfet_01v8','vdsat')),
       actuator_gm_S=field('MF','pfet_01v8','gm'),actuator_ro_ohm=1/field('MF','pfet_01v8','gds'),
       output_current_balance_A=-values['i(vs_mp)']-load+values['i(vs_l2)'])
    row['M2_saturation_margin_V']=row['M2_VDS_V']-row['M2_VDSAT_V']
    row['actuator_saturation_margin_V']=row['actuator_VSD_V']-row['actuator_VDSAT_V']
    row['output_error_V']=v['O']-.8
    rows.append(row)
(OUT/'tt_load_screen.json').write_text(json.dumps(dict(evidence='New local native SKY130 TT 27 C fixed circuit DC load sweep.',rows=rows),indent=2))

ac_results={}
for name,vi,vr in [('supply',1,0),('reference',0,1)]:
    source=base.replace('VIN VIN 0 1.2',f'VIN VIN 0 1.2 AC {vi}').replace('VREF R 0 .8',f'VREF R 0 .8 AC {vr}')
    source+=f'\n.control\nset noaskquit\nset numdgt=15\nset wr_singlescale\nset wr_vecnames\nac dec 60 1 1e9\nwrdata {name}_ac.txt v(O) v(G) v(C)\nquit\n.endc\n.end\n'
    p,log,errors=run(OUT,name,source)
    data=np.loadtxt(OUT/(name+'_ac.txt'),skiprows=1)
    h=data[:,1]+1j*data[:,2]
    samples=[]
    for f in [1,1e3,1e4,1e5,1e6,3e6,1e7]:
        z=np.interp(np.log10(f),np.log10(data[:,0]),h.real)+1j*np.interp(np.log10(f),np.log10(data[:,0]),h.imag)
        samples.append(dict(frequency_Hz=f,real=float(z.real),imag=float(z.imag),magnitude_dB=float(20*np.log10(abs(z)))))
    ac_results[name]=dict(returncode=p.returncode,errors=errors,samples=samples)

dc_clean=all(row['returncode']==0 and not row['errors'] and row['M2_saturation_margin_V']>0 and row['actuator_saturation_margin_V']>0 for row in rows)
poleresult=dict(status='not_run_after_DC_failure',RHP_pole_count=None)
if dc_clean:
    source=base.replace('VIN VIN 0 1.2','VIN VIN 0 1.2 AC 1').replace('VREF R 0 .8','VREF R 0 .8 AC 0')
    source+='\n.control\nset noaskquit\nset numdgt=15\nop\npz VIN 0 O 0 vol pz\nprint all\nquit\n.endc\n.end\n'
    p,log,errors=run(OUT,'closed_pz',source)
    num=r'([+-]?[\d.]+(?:e[+-]?\d+)?)'
    poles=[dict(real_per_s=float(a),imag_per_s=float(b)) for a,b in re.findall(r'pole\(\d+\)\s*=\s*'+num+r'\s*,\s*'+num,log,re.I)]
    good=p.returncode==0 and not errors and bool(poles)
    if not good:
        raise RuntimeError('Native pole diagnostic returned no valid poles.')
    poleresult=dict(status='success' if good else 'failed',returncode=p.returncode,errors=errors,poles=poles,
                   RHP_pole_count=sum(x['real_per_s']>0 for x in poles) if good else None)
report=dict(evidence='Native SKY130 TT at 27 C with one prespecified source connection and geometry change.',simulator=SIMULATOR,
       connection_change=json.loads((OUT/'connection_change.json').read_text()),load_rows=rows,AC=ac_results,pole_diagnostic=poleresult,
       nominal_load_A=.05,COUT_F=200e-12,CC_F=100e-12,
       limitations=['Original FVF action removed','Quiet ideal reference and bias ports','Nominal process only','No load transient or startup validation','No added cancellation branches','No automatic retuning','Default zero diffusion areas and perimeters. No layout capacitance qualification.'])
(OUT/'native_results.json').write_text(json.dumps(report,indent=2))
print(json.dumps(dict(loads=[dict(load_A=x['external_load_A'],O_V=x['voltages_V']['O'],G_V=x['voltages_V']['G'],C_V=x['voltages_V']['C'],
      M2_margin_V=x['M2_saturation_margin_V'],actuator_margin_V=x['actuator_saturation_margin_V']) for x in rows],
      AC=ac_results,pole_status=poleresult['status'],RHP=poleresult['RHP_pole_count']),indent=2))
