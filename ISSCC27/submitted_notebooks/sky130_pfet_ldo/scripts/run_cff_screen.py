"""Bounded local native supply to gate capacitor experiment after saved derivation."""
import hashlib
import json
import re
import subprocess
from pathlib import Path
import sys
import numpy as np

from runtime_support import PROJECT, find_ngspice, verify_models, record_simulator, relative_library_path, prepare_native_outputs, check_native_completion
EXE=find_ngspice()
LIB=verify_models()
SIMULATOR=record_simulator(EXE)
HERE=PROJECT/'results/cff_screen'
HERE.mkdir(exist_ok=True)
CORE=PROJECT/'circuits/refined'
OPFILE=PROJECT/'results/recorded/refined_operating_point.json'
NUM=r'([+-]?[\d.]+(?:e[+-]?\d+)?)'

def run(folder,name,source):
    folder.mkdir(exist_ok=True)
    source=re.sub(r'(?m)^\.lib .+ tt$',f'.lib "{relative_library_path(folder)}" tt',source)
    (folder/(name+'.spice')).write_text(source)
    outputs=prepare_native_outputs(source,folder)
    result=subprocess.run([str(EXE),'-b',name+'.spice'],cwd=folder,capture_output=True,text=True,timeout=35)
    log=result.stdout+'\n'+result.stderr
    (folder/(name+'.log')).write_text(log)
    errors=[line.strip() for line in log.splitlines() if re.search(r'aborted|\berror\b|shorted on the way',line,re.I)]
    check_native_completion(result,log,outputs)
    return result,log,errors

def verify():
    rng=np.random.default_rng(110144)
    err=0.
    for _ in range(500):
        rd=10**rng.uniform(2,5);ro=10**rng.uniform(1,5);rl=10**rng.uniform(1,6)
        gm=10**rng.uniform(-4,0);a0=10**rng.uniform(-1,3);tau=10**rng.uniform(-9,-3);ki=rng.uniform(-1,2)
        cgs,cgd,cds,co,cff=10**rng.uniform(-14,-9,5)
        ci=cgs+cff;cg=ci+cgd;cot=co+cds+cgd;rs=1/(1/rl+1/ro)
        d=[1/rs+a0*gm,cot+rd*cg/rs+rd*cgd*gm+tau/rs-a0*cgd,
           rd*(cg*cot-cgd*cgd)+tau*(cot+rd*cg/rs+rd*cgd*gm),tau*rd*(cg*cot-cgd*cgd)]
        v0=gm*(1-ki)+1/ro;v1=cds+ki*cgd+rd*(gm*cgd+cg/ro);v2=rd*(cg*cds+ci*cgd)
        nv=[v0,v1+tau*v0,v2+tau*v1,tau*v2];nr=[a0*gm,-a0*cgd]
        nl=[-1,-tau-rd*cg,-tau*rd*cg]
        s=1j*10**rng.uniform(0,10);aa=a0/(1+s*tau)
        matrix=np.array([[1/rd+s*cg,-aa/rd-s*cgd],[gm-s*cgd,1/rs+s*cot]],complex)
        for num,rhs in [(nv,[ki/rd+s*ci,gm+1/ro+s*cds]),(nr,[-aa/rd,0]),(nl,[0,-1])]:
            x=np.polynomial.polynomial.polyval(s,num)/np.polynomial.polynomial.polyval(s,d)
            y=np.linalg.solve(matrix,rhs)[1]
            err=max(err,abs(x-y)/max(abs(x),abs(y),1e-14))
    if err>1e-7:raise AssertionError(err)
    return dict(evidence='Synthetic algebra check only',cases=500,transfers_per_case=3,maximum_relative_error=float(err))

algebra=verify()
(HERE/'two_node_algebra_check.json').write_text(json.dumps(algebra,indent=2))
base=(CORE/'core_seed.spice').read_text().split('.control',1)[0]
native=json.loads(OPFILE.read_text())
vg=native['voltages_V']['G'];vo=native['voltages_V']['O']
mp=next(d for d in native['devices'] if d['name']=='MP')
cap=f'''Native total pass gate charge fixture at connected bias
.lib "{LIB.as_posix()}" tt
.temp 27
VIN VIN 0 1.2 AC 0
VO O 0 {vo:.15g} AC 0
VG G 0 {vg:.15g} AC 1
XMP O G VIN VIN sky130_fd_pr__pfet_01v8 w=5 l=.15 nf=1 m={mp['m']}
.control
set noaskquit
set numdgt=15
set wr_singlescale
set wr_vecnames
ac lin 1 1e6 1e6
wrdata total_gate_charge.txt i(VG)
quit
.endc
.end
'''
result,log,errors=run(HERE,'total_gate_charge',cap)
data=np.loadtxt(HERE/'total_gate_charge.txt',skiprows=1,ndmin=2)
cgg=-data[0,2]/(2*np.pi*data[0,0])
gate=dict(evidence='Native isolated pass gate current at the connected DC voltages, with source and drain AC restrained.',
          total_CGG_F=float(cgg),frequency_Hz=float(data[0,0]),W_unit_um=5,L_um=.15,m=mp['m'],errors=errors)
(HERE/'total_gate_charge.json').write_text(json.dumps(gate,indent=2))

all_cases=[]
for capacitance_pf in [0,5,20,100,500]:
    folder=HERE/f'cff_{capacitance_pf}pF'
    circuit=base+('' if capacitance_pf==0 else f'\nCFF VIN G {capacitance_pf}p\n')
    row=dict(CFF_pF=capacitance_pf,CFF_to_native_pass_CGG_ratio=capacitance_pf*1e-12/cgg)
    for name,vi,vr in [('supply',1,0),('reference',0,1)]:
        source=circuit.replace('VIN VIN 0 1.2',f'VIN VIN 0 1.2 AC {vi}').replace('VREF R 0 .8',f'VREF R 0 .8 AC {vr}')
        source+=f'''\n.control
set noaskquit
set numdgt=15
set wr_singlescale
set wr_vecnames
op
print v(O) v(G) v(C)
ac dec 60 1 1e9
wrdata {name}_ac.txt v(O) v(G) v(C)
quit
.endc
.end
'''
        result,log,errors=run(folder,name,source)
        values={k.strip().lower():float(x) for k,x in re.findall(r'^\s*(v\([ogc]\))\s*=\s*'+NUM+r'\s*$',log,re.M|re.I)}
        data=np.loadtxt(folder/(name+'_ac.txt'),skiprows=1)
        h=data[:,1]+1j*data[:,2]
        hg=data[:,3]+1j*data[:,4]
        frequencies=[1,1e3,1e4,1e5,1e6,3e6,1e7]
        samples=[]
        for frequency in frequencies:
            # Complex interpolation on log frequency retains a fixed requested comparison frequency.
            lh=np.log10(data[:,0]);lf=np.log10(frequency)
            z=np.interp(lf,lh,h.real)+1j*np.interp(lf,lh,h.imag)
            zg=np.interp(lf,lh,hg.real)+1j*np.interp(lf,lh,hg.imag)
            samples.append(dict(frequency_Hz=frequency,real=float(z.real),imag=float(z.imag),
                magnitude_dB=float(20*np.log10(abs(z))),phase_deg=float(np.angle(z,deg=True)),
                gate_real=float(zg.real),gate_imag=float(zg.imag)))
        row[name]=dict(returncode=result.returncode,errors=errors,DC_voltages_V=values,samples=samples)
    source=circuit.replace('VIN VIN 0 1.2','VIN VIN 0 1.2 AC 1').replace('VREF R 0 .8','VREF R 0 .8 AC 0')
    source+='\n.control\nset noaskquit\nset numdgt=15\nop\npz VIN 0 O 0 vol pz\nprint all\nwrite closed_pz.raw all\nquit\n.endc\n.end\n'
    result,log,errors=run(folder,'closed_pz',source)
    poles=[dict(real_per_s=float(a),imag_per_s=float(b)) for a,b in re.findall(r'pole\(\d+\)\s*=\s*'+NUM+r'\s*,\s*'+NUM,log,re.I)]
    valid=result.returncode==0 and not errors and bool(poles)
    if not valid:
        raise RuntimeError('Native pole diagnostic returned no valid poles.')
    row['pole_diagnostic']=dict(status='success' if valid else 'failed',returncode=result.returncode,errors=errors,poles=poles,
         RHP_pole_count=sum(p['real_per_s']>0 for p in poles) if valid else None)
    all_cases.append(row)
    (HERE/'cff_results.partial.json').write_text(json.dumps(all_cases,indent=2))

baseline=all_cases[0]
for case in all_cases:
    case['supply_improvement_dB']=[dict(frequency_Hz=a['frequency_Hz'],improvement_dB=b['magnitude_dB']-a['magnitude_dB'])
       for a,b in zip(case['supply']['samples'],baseline['supply']['samples'])]
    curve=np.loadtxt(HERE/f'cff_{case["CFF_pF"]}pF'/'supply_ac.txt',skiprows=1)
    ref=np.loadtxt(HERE/'cff_0pF'/'supply_ac.txt',skiprows=1)
    improvement=20*np.log10(abs(ref[:,1]+1j*ref[:,2]))-20*np.log10(abs(curve[:,1]+1j*curve[:,2]))
    case['sampled_band_improvement_dB']={}
    for label,lo,hi in [('1Hz_to_100kHz',1,1e5),('1MHz_to_10MHz',1e6,1e7)]:
        mask=(curve[:,0]>=lo*(1-1e-10))&(curve[:,0]<=hi*(1+1e-10))
        case['sampled_band_improvement_dB'][label]=dict(minimum=float(np.min(improvement[mask])),maximum=float(np.max(improvement[mask])))
final=dict(evidence='New local native SKY130 TT 27 C connected circuit AC and PZ screen.',simulator=SIMULATOR,
           derivation_sha256=hashlib.sha256((PROJECT/'references/cff_derivation.tex').read_bytes()).hexdigest(),
           total_gate_charge=gate,algebra_check=algebra,cases=all_cases,
           fixed_conditions=dict(VIN_V=1.2,VREF_V=.8,load_A=.05,COUT_F=200e-12,CC_F=100e-12),
           comparison_interpolation='Complex interpolation on log frequency for requested spots. Whole band extrema use actual sweep points.',
           limitations=['Quiet ideal bias and reference ports','TT at 27 C and 50 mA only','No load transient or startup evaluation','No added source sensing cancellation branches','No novelty claim','Default diffusion areas and perimeters are zero. No layout capacitance qualification.'])
(HERE/'cff_results.json').write_text(json.dumps(final,indent=2))
print(json.dumps(dict(total_gate_CGG_pF=cgg*1e12,algebra_error=algebra['maximum_relative_error'],
   cases=[dict(CFF_pF=c['CFF_pF'],pole_status=c['pole_diagnostic']['status'],RHP=c['pole_diagnostic']['RHP_pole_count'],
               supply_dB=[x['magnitude_dB'] for x in c['supply']['samples']],
               sampled_band_improvement_dB=c['sampled_band_improvement_dB']) for c in all_cases]),indent=2))
