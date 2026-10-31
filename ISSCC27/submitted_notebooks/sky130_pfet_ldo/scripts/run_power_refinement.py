"""Reproduce the fixed physical power cell, capacitor ablation and corner screen."""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import tempfile
import numpy as np
from runtime_support import (PROJECT, find_ngspice, verify_models, record_simulator,
    relative_library_path, prepare_native_outputs, check_native_completion)

SOURCE=PROJECT/'circuits/power_refinement/selected.spice'
BASELINE=PROJECT/'circuits/refined/core_seed.spice'
OUT=PROJECT/'results/power_refinement'
NUM=r'([+-]?[\d.]+(?:e[+-]?\d+)?)'
FREQS=[1,1e3,1e4,1e5,1e6,3e6,1e7]
LOADS=[0,.0001,.001,.005,.01,.025,.05]

def body(source,load=.05,corner='tt',temperature=27,cap_pf=None,driver_scale=None):
    text=source.split('.control',1)[0]
    text=re.sub(r'(?im)^\.end\s*$','',text)
    text=re.sub(r'(?m)^ILOAD .+$',f'ILOAD O 0 DC {load:.15g}',text)
    text=re.sub(r'(?m)^\.temp .+$',f'.temp {temperature:g}',text)
    text=re.sub(r'(?m)^(\.lib\s+"[^"]+")\s+\w+$',r'\1 '+corner,text)
    if cap_pf is not None:
        text=re.sub(r'(?m)^CAG .+\n?','',text)
        if cap_pf:
            text+=f'\nCAG O G {cap_pf:g}p\n'
    if driver_scale is not None:
        for name,unit in [('MF',100),('PH',2),('NB',4),('PU',30)]:
            text,count=re.subn(r'(?m)^(X'+name+r'\s+.*\bm=)\d+(\s*)$',lambda m:m.group(1)+str(unit*driver_scale)+m.group(2),text)
            if count!=1:raise ValueError('Expected one driver device '+name)
    return text

def native(text,destination,executable):
    destination.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy()
    env['OMP_NUM_THREADS']='2'
    # A short native working path avoids legacy Windows simulator path limits.
    with tempfile.TemporaryDirectory(prefix='pwr_',dir=PROJECT/'results') as temporary:
        work=Path(temporary)
        library=relative_library_path(work)
        executed=re.sub(r'(?m)^\.lib\s+"[^"]+"\s+(\w+)$',lambda m:f'.lib "{library}" {m.group(1)}',text)
        (work/'input.spice').write_text(executed)
        archived=re.sub(r'(?m)^\.lib\s+"[^"]+"\s+(\w+)$',lambda m:f'.lib "{relative_library_path(destination)}" {m.group(1)}',text)
        (destination/'input.spice').write_text(archived)
        prepare_native_outputs(archived,destination)
        outputs=prepare_native_outputs(executed,work)
        reply=subprocess.run([str(executable),'-b','input.spice'],cwd=work,
            capture_output=True,text=True,timeout=90,env=env)
        log=reply.stdout+'\n'+reply.stderr
        (destination/'run.log').write_text(log)
        check_native_completion(reply,log,outputs)
        for output in outputs:
            (destination/output.name).write_bytes(output.read_bytes())
    return log

def control(text,commands):
    return text+'\n.control\nset noaskquit\nset numdgt=15\n'+commands+'\nquit\n.endc\n.end\n'

def dc(text,destination,executable,load):
    names=[('MP','pfet_01v8'),('MF','pfet_01v8'),('M2','nfet_01v8'),('NB','nfet_01v8')]
    commands=['op','print v(O) v(G) v(C) v(X) v(Y) v(A)',
        'print i(VIN) i(VREF) i(VS_MP) i(VS_MF) i(VS_PH) i(VS_NB)'+(' i(VS_PU)' if 'VS_PU' in text else '')]
    for name,kind in names:
        ident='@m.x'+name.lower()+'.msky130_fd_pr__'+kind
        commands.append('print '+' '.join(ident+'['+f+']' for f in ['id','gm','gds','vdsat']))
    log=native(control(text,'\n'.join(commands)),destination,executable)
    values={k.strip().lower():float(v) for k,v in re.findall(r'^\s*([^\n=]+?)\s*=\s*'+NUM+r'\s*$',log,re.M|re.I)}
    volts={n:values['v('+n.lower()+')'] for n in ['O','G','C','X','Y','A']}
    def field(name,kind,f):return values['@m.x'+name.lower()+'.msky130_fd_pr__'+kind+'['+f+']']
    result=dict(external_load_A=load,voltages_V=volts,input_current_A=-values['i(vin)'],
        reference_current_A=-values['i(vref)'],core_VIN_overhead_A=-values['i(vin)']-load,
        MP_current_A=-values['i(vs_mp)'],MF_current_into_gate_A=-values['i(vs_mf)'],
        PH_current_into_gate_A=-values['i(vs_ph)'],NB_current_from_gate_A=values['i(vs_nb)'],
        PU_current_into_gate_A=-values['i(vs_pu)'] if 'VS_PU' in text else 0,
        MP_gm_S=field('MP','pfet_01v8','gm'),MP_ro_ohm=1/field('MP','pfet_01v8','gds'),
        M2_saturation_margin_V=volts['C']-volts['Y']-abs(field('M2','nfet_01v8','vdsat')),
        MF_forward_saturation_margin_V=volts['O']-volts['G']-abs(field('MF','pfet_01v8','vdsat')),
        NB_saturation_margin_V=volts['G']-abs(field('NB','nfet_01v8','vdsat')),
        MP_saturation_margin_V=1.2-volts['O']-abs(field('MP','pfet_01v8','vdsat')),
        output_error_V=volts['O']-.8)
    (destination/'result.json').write_text(json.dumps(result,indent=2))
    return result

def ac(text,destination,executable,port):
    vi,vr=(1,0) if port=='supply' else (0,1)
    text=text.replace('VIN VIN 0 1.2',f'VIN VIN 0 1.2 AC {vi}').replace('VREF R 0 .8',f'VREF R 0 .8 AC {vr}')
    native(control(text,'set wr_singlescale\nset wr_vecnames\nac dec 60 1 1e9\nwrdata ac.txt v(O) v(G) v(C)'),destination,executable)
    data=np.loadtxt(destination/'ac.txt',skiprows=1)
    h=data[:,1]+1j*data[:,2]
    samples=[]
    for f in FREQS:
        z=np.interp(np.log10(f),np.log10(data[:,0]),h.real)+1j*np.interp(np.log10(f),np.log10(data[:,0]),h.imag)
        samples.append(dict(frequency_Hz=f,real=float(z.real),imag=float(z.imag),magnitude_dB=float(20*np.log10(abs(z)))))
    return dict(samples=samples),data

def bands(data,baseline):
    delta=20*np.log10(abs(baseline[:,1]+1j*baseline[:,2]))-20*np.log10(abs(data[:,1]+1j*data[:,2]))
    result={}
    for name,lo,hi in [('LF',1e3,1e5),('MHz',1e6,1e7)]:
        mask=(data[:,0]>=lo*(1-1e-10))&(data[:,0]<=hi*(1+1e-10))
        result[name]=dict(minimum_improvement_dB=float(delta[mask].min()),maximum_improvement_dB=float(delta[mask].max()),sample_count=int(mask.sum()))
    return result

def pz(text,destination,executable,load):
    text=text.replace('VIN VIN 0 1.2','VIN VIN 0 1.2 AC 1').replace('VREF R 0 .8','VREF R 0 .8 AC 0')
    log=native(control(text,'op\npz VIN 0 O 0 vol pz\nprint all'),destination,executable)
    def roots(kind):
        return [dict(real_per_s=float(a),imag_per_s=float(b)) for a,b in re.findall(kind+r'\(\d+\)\s*=\s*'+NUM+r'\s*,\s*'+NUM,log,re.I)]
    poles=roots('pole')
    if not poles:raise RuntimeError('Native PZ returned no poles')
    return dict(load_A=load,poles=poles,zeros=roots('zero'),RHP_pole_count=sum(p['real_per_s']>0 for p in poles))

def transient(text,destination,executable):
    text=re.sub(r'(?m)^ILOAD .+$','ILOAD O 0 PWL(0 .005 2u .005 2.1u .05 7.1u .05 7.2u .005 12u .005)',text)
    native(control(text,'set wr_singlescale\nset wr_vecnames\ntran 2n 12u\nwrdata transient.txt v(O) v(G) v(C) i(VIN)'),destination,executable)
    data=np.loadtxt(destination/'transient.txt',skiprows=1)
    rise=(data[:,0]>=2e-6)&(data[:,0]<7.1e-6)
    fall=data[:,0]>=7.1e-6
    return dict(low_load_A=.005,high_load_A=.05,edge_s=100e-9,COUT_F=200e-12,CC_F=100e-12,
        initial_output_V=float(data[0,1]),final_output_V=float(data[-1,1]),
        rising_load_minimum_output_V=float(data[rise,1].min()),falling_load_maximum_output_V=float(data[fall,1].max()))

def gate_charge(source,point,destination,executable):
    device=next(line for line in source.splitlines() if line.startswith('XMP '))
    device=device.replace('D_MP','O')
    text='Native pass array gate loading at the connected nominal operating point\n.lib "models" tt\n.temp 27\n.option reltol=1e-6 abstol=1e-13 vntol=1e-8\n'
    text+=f'VIN VIN 0 1.2 AC 0\nVO O 0 {point["voltages_V"]["O"]:.15g} AC 0\nVG G 0 {point["voltages_V"]["G"]:.15g} AC 1\n'+device+'\n'
    native(control(text,'set wr_singlescale\nset wr_vecnames\nac lin 1 1e6 1e6\nwrdata charge.txt i(VG)'),destination,executable)
    data=np.loadtxt(destination/'charge.txt',skiprows=1,ndmin=2)
    return dict(CGG_F=float(-data[0,2]/(2*np.pi*data[0,0])),frequency_Hz=1e6,
        condition='Isolated native pass array at the connected 50 mA terminal voltages. Source and drain are AC grounded only in this capacitance fixture.')

def main():
    executable=find_ngspice()
    verify_models()
    simulator=record_simulator(executable)
    source=SOURCE.read_text()
    baseline=BASELINE.read_text()
    before,before_curve=ac(body(baseline),OUT/'original/supply',executable,'supply')
    original_dc=dc(body(baseline),OUT/'original/dc',executable,.05)
    original=dict(dc_50mA=original_dc,supply=before,
        transient=transient(body(baseline),OUT/'original/transient',executable),
        gate_charge=gate_charge(baseline,original_dc,OUT/'original/gate_charge',executable))
    rows=[dc(body(source,load),OUT/f'load_{round(load*1e6)}uA',executable,load) for load in LOADS]
    supply,curve=ac(body(source),OUT/'selected/supply',executable,'supply')
    reference,_=ac(body(source),OUT/'selected/reference',executable,'reference')
    selected=dict(driver_scale=3,CAG_pF=1,load_rows=rows,dc_50mA=rows[-1],supply=supply,reference=reference,
        bands_vs_original=bands(curve,before_curve),gate_charge=gate_charge(source,rows[-1],OUT/'selected/gate_charge',executable),
        pole_diagnostics=[pz(body(source,load),OUT/f'selected/pz_{round(load*1e6)}uA',executable,load) for load in [0,.005,.05]],
        transient=transient(body(source),OUT/'selected/transient',executable))
    (OUT/'selected_ac.txt').write_bytes((OUT/'selected/supply/ac.txt').read_bytes())
    (OUT/'selected_reference_ac.txt').write_bytes((OUT/'selected/reference/ac.txt').read_bytes())
    (OUT/'selected_transient.txt').write_bytes((OUT/'selected/transient/transient.txt').read_bytes())
    (OUT/'original_ac.txt').write_bytes((OUT/'original/supply/ac.txt').read_bytes())
    (OUT/'original_transient.txt').write_bytes((OUT/'original/transient/transient.txt').read_bytes())
    ablation=[]
    for cap in [0,1,2,3,5,20,50,100]:
        directory=OUT/f'CAG_{cap}p'
        response,data=ac(body(source,cap_pf=cap,driver_scale=2),directory/'supply',executable,'supply')
        case=dict(CAG_pF=cap,driver_scale=2,supply=response,bands_vs_original=bands(data,before_curve),
            pole_diagnostics=[pz(body(source,load,cap_pf=cap,driver_scale=2),directory/f'pz_{round(load*1e6)}uA',executable,load) for load in [0,.005,.05]],
            transient=transient(body(source,cap_pf=cap,driver_scale=2),directory/'transient',executable))
        ablation.append(case)
        print(json.dumps(dict(CAG_pF=cap,bands=case['bands_vs_original'],transient=case['transient'])),flush=True)
    driver_cases=[]
    for scale in [3,4]:
        for cap in [1,2]:
            directory=OUT/f'driver_{scale}_CAG_{cap}p'
            text=body(source,cap_pf=cap,driver_scale=scale)
            response,data=ac(text,directory/'supply',executable,'supply')
            case=dict(driver_scale=scale,CAG_pF=cap,dc_50mA=dc(text,directory/'dc',executable,.05),
                supply=response,bands_vs_original=bands(data,before_curve),
                pole_diagnostics=[pz(body(source,load,cap_pf=cap,driver_scale=scale),directory/f'pz_{round(load*1e6)}uA',executable,load) for load in [0,.005,.05]],
                transient=transient(text,directory/'transient',executable))
            driver_cases.append(case)
            print(json.dumps(dict(driver_scale=scale,CAG_pF=cap,bands=case['bands_vs_original'],transient=case['transient'])),flush=True)
    corners=[]
    for corner,temperature in [('ss',27),('ff',27),('tt',0),('tt',85)]:
        directory=OUT/f'corner_{corner}_{temperature}C'
        text=body(source,corner=corner,temperature=temperature)
        point=dc(text,directory/'dc',executable,.05)
        response,_=ac(text,directory/'supply',executable,'supply')
        case=dict(corner=corner,temperature_C=temperature,load_A=.05,dc=point,supply=response,
            pole_diagnostics=pz(text,directory/'pz',executable,.05),
            within_one_percent_output=abs(point['output_error_V'])<=.008)
        corners.append(case)
        print(json.dumps(dict(corner=corner,temperature_C=temperature,output_V=point['voltages_V']['O'],within_one_percent=case['within_one_percent_output'])),flush=True)
    selected.update(supply_samples=supply['samples'],reference_samples=reference['samples'],
        gate_capacitance_F=selected['gate_charge']['CGG_F'],poles_by_load=selected['pole_diagnostics'],corner_rows=corners)
    report=dict(evidence='Native public SKY130 simulations of a fixed physical connected circuit.',simulator=simulator,
        source_netlist_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        pretest_derivation_sha256=hashlib.sha256((PROJECT/'references/power_refinement.tex').read_bytes()).hexdigest(),
        original=original,selected=selected,cag_cases=ablation,driver_cases=driver_cases,
        CAG_ablation=ablation,fixed_bias_corner_screen=corners,
        selection_rule='Among the declared scale 3 and scale 4 cases with CAG 1 and 2 pF, select the largest minimum improvement across 1 to 10 MHz while retaining positive improvement across 1 kHz to 100 kHz, improved original transient extrema, positive seven load nominal M2 MF and NB margins, and no returned RHP pole. This selects scale 3 and CAG 1 pF. Corners use this same circuit without rebias.',
        limitations=['Quiet ideal reference and bias ports remain external.',
            'VIN current above the external load excludes the separately supplied reference current and all reference and bias generator power.',
            'Default diffusion areas and perimeters are zero. No layout extraction is included.',
            'Nominal poles of the observable supply transfer are a diagnostic and do not establish all internal modes or a loop gain margin.',
            'No startup, mismatch, reliability or silicon qualification is claimed.',
            'The capacitor ablation and fixed bias corner failures are retained. No load or corner dependent rebias is performed.'])
    (OUT/'summary.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(dict(selected=selected['dc_50mA'],bands=selected['bands_vs_original'],gate_charge=selected['gate_charge'])),flush=True)

if __name__=='__main__':
    main()
