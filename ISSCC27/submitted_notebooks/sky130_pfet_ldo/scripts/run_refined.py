"""Reproduce the frozen refined core without retuning it across loads."""
import hashlib
import json
import re
import subprocess
import numpy as np
from runtime_support import PROJECT, find_ngspice, verify_models, record_simulator, relative_library_path, prepare_native_outputs, check_native_completion

SOURCE = PROJECT/'circuits/refined/core_seed.spice'
OUT = PROJECT/'results/refined'


def native(text, destination, executable):
    destination.mkdir(parents=True,exist_ok=True)
    text = re.sub(r'(?m)^\.lib .+ tt$', f'.lib "{relative_library_path(destination)}" tt', text)
    (destination/'input.spice').write_text(text)
    outputs=prepare_native_outputs(text,destination)
    reply = subprocess.run([str(executable),'-b','input.spice'],cwd=destination,
                           capture_output=True,text=True,timeout=60)
    log = reply.stdout+'\n'+reply.stderr
    (destination/'run.log').write_text(log)
    check_native_completion(reply,log,outputs)
    if reply.returncode or re.search(r'(?im)^\s*(?:fatal|error on line|error:|.*aborted)',log):
        raise RuntimeError('Native run failed in '+destination.relative_to(PROJECT).as_posix())
    return reply.stdout, hashlib.sha256(text.encode()).hexdigest()


def main():
    executable=find_ngspice()
    verify_models()
    simulator=record_simulator(executable)
    source=SOURCE.read_text()
    rows=[]
    for load in [0.,.0001,.001,.005,.01,.025,.05]:
        destination=OUT/('load_'+str(round(load*1e6))+'uA')
        text=re.sub(r'(?m)^ILOAD .*$',f'ILOAD O 0 DC {load:.12g}',source)
        console,digest=native(text,destination,executable)
        values={k.strip().lower():float(x) for k,x in re.findall(r'^\s*([^\n=]+?)\s*=\s*([+-]?[\d.]+(?:e[+-]?\d+)?)\s*$',console,re.M|re.I)}
        volts={k:values['v('+k.lower()+')'] for k in ['O','G','C','X','Y','A']}
        field=lambda n,t,f:values['@m.x'+n.lower()+'.msky130_fd_pr__'+t+'['+f+']']
        row=dict(external_load_A=load,voltages_V=volts,input_current_A=-values['i(vin)'],
                 reference_current_A=-values['i(vref)'],
                 core_input_current_above_external_load_A=-values['i(vin)']-load,
                 MP_current_A=-values['i(vs_mp)'],MF_current_into_gate_A=-values['i(vs_mf)'],
                 PH_current_into_gate_A=-values['i(vs_ph)'],NB_current_from_gate_A=values['i(vs_nb)'],
                 M2_saturation_margin_V=volts['C']-volts['Y']-abs(field('M2','nfet_01v8','vdsat')),
                 MF_forward_saturation_margin_V=volts['O']-volts['G']-abs(field('MF','pfet_01v8','vdsat')),
                 output_error_V=volts['O']-.8,netlist_sha256=digest)
        rows.append(row)
        (destination/'result.json').write_text(json.dumps(row,indent=2))
    ac={}
    body=source.split('.control',1)[0]
    for name,vi,vr in [('supply',1,0),('reference',0,1)]:
        text=body.replace('VIN VIN 0 1.2',f'VIN VIN 0 1.2 AC {vi}').replace('VREF R 0 .8',f'VREF R 0 .8 AC {vr}')
        text+='\n.control\nset noaskquit\nset numdgt=15\nset wr_singlescale\nset wr_vecnames\nac dec 60 1 1e9\nwrdata ac.txt v(O) v(G) v(C)\nquit\n.endc\n.end\n'
        destination=OUT/(name+'_ac')
        console,digest=native(text,destination,executable)
        table=np.loadtxt(destination/'ac.txt',skiprows=1)
        response=table[:,1]+1j*table[:,2]
        samples=[]
        for frequency in [1,1e3,1e4,1e5,1e6,1e7,1e8]:
            i=int(np.argmin(abs(table[:,0]-frequency)))
            samples.append(dict(frequency_Hz=float(table[i,0]),real=float(response[i].real),
                                imag=float(response[i].imag),magnitude_dB=float(20*np.log10(abs(response[i])))))
        ac[name]=dict(samples=samples,netlist_sha256=digest)
    report=dict(evidence='Fresh native SKY130 TT analysis of the fixed refined circuit at 27 C.',
                simulator=simulator,source_netlist_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                load_rows=rows,ac_50mA=ac,
                stability_status='No pole, loop margin or stability qualification is performed by this runner.',
                limitations=['Quiet ideal bias and reference sources',
                             'VIN current minus external load excludes separately supplied reference current and generator power',
                             'Default ad, as, pd and ps are zero. No layout extracted capacitance.',
                             'No cancellation branches or CFF are included in this refined core.',
                             'Native completion does not mean that regulation or dynamic targets passed.'])
    (OUT/'summary.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
