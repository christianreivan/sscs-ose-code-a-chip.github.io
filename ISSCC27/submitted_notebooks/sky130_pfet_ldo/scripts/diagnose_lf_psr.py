"""Unchanged circuit DC small signal supply path reconstruction."""
from pathlib import Path
import json
import re
import subprocess
import numpy as np
from runtime_support import PROJECT,find_ngspice,verify_models
from run_power_refinement import native as run_native
HERE=PROJECT/'results/lf_psr_diagnosis'
HERE.mkdir(parents=True,exist_ok=True)
EXE=find_ngspice()
LIB=verify_models()
SOURCES={'selected':PROJECT/'circuits/power_refinement/selected.spice',
         'published_baseline':PROJECT/'circuits/refined/core_seed.spice'}
grid=json.loads((PROJECT/'results/recorded/compensation_screen_summary.json').read_text())
older=next(c for c in grid['cases'] if c['case_id']=='supply_actuator_compensation/cm0p_rz0_cs100p')
template=older['netlist_template']
source_folder=HERE/'src'
source_folder.mkdir(exist_ok=True)
comparison=source_folder/'vin.spice'
comparison.write_text(template+'\n.end\n')
SOURCES['supply_sourced_follower']=comparison
CASE_DIR={'selected':'sel','published_baseline':'base','supply_sourced_follower':'vin'}
NODES=['A','X','Y','C','G','O']
SENSING={'M1','M2','L1','L2','P1','P2','B1','B2'}
NUM=r'([+-]?[\d.]+(?:e[+-]?\d+)?)'

def read_circuit(source):
    text=source.read_text().split('.control',1)[0]
    text=re.sub(r'(?im)^\.end\s*$','',text)
    text=re.sub(r'(?im)^\.lib\s+"[^"]+"\s+\w+\s*$',f'.lib "{LIB.as_posix()}" tt',text)
    text=re.sub(r'(?im)^VIN\s+VIN\s+0\s+.*$','VIN VIN 0 1.2',text)
    text=re.sub(r'(?im)^VREF\s+R\s+0\s+.*$','VREF R 0 .8',text)
    aliases={}
    for line in text.splitlines():
        words=line.split()
        if len(words)==4 and words[0].upper().startswith('VS_') and words[3]=='0':aliases[words[2]]=words[1]
    devices=[]
    for line in text.splitlines():
        words=line.split()
        if words and words[0].startswith('X'):
            name=words[0][1:]
            devices.append(dict(name=name,D=aliases.get(words[1],words[1]),G=aliases.get(words[2],words[2]),
               S=aliases.get(words[3],words[3]),B=aliases.get(words[4],words[4]),model=words[5]))
    return text,devices

def run(name,source,devices):
    folder=HERE/CASE_DIR[name];folder.mkdir(exist_ok=True)
    result={}
    for port,vi,vr in [('supply',1,0),('reference',0,1)]:
        base=source.replace('VIN VIN 0 1.2',f'VIN VIN 0 1.2 AC {vi}').replace('VREF R 0 .8',f'VREF R 0 .8 AC {vr}')
        commands=['set noaskquit','set numdgt=15','op','print '+' '.join('v('+n+')' for n in NODES),
                  'print i(VIN) i(VREF)']
        for d in devices:
            ident='@m.x'+d['name'].lower()+'.m'+d['model']
            commands.append('print '+' '.join(ident+'['+k+']' for k in ['id','gm','gmbs','gds','vds','vgs','vbs']))
        commands+=['set wr_singlescale','set wr_vecnames','ac lin 1 1 1','wrdata '+port+'_ac.txt '+' '.join('v('+n+')' for n in NODES),'quit']
        deck=base+'\n.control\n'+'\n'.join(commands)+'\n.endc\n.end\n'
        destination=folder/port
        log=run_native(deck,destination,EXE)
        values={k.strip().lower():float(v) for k,v in re.findall(r'^\s*([^\n=]+?)\s*=\s*'+NUM+r'\s*$',log,re.M|re.I)}
        data=np.loadtxt(destination/(port+'_ac.txt'),skiprows=1,ndmin=2)[0]
        result[port]={n:dict(real=float(data[1+2*i]),imag=float(data[2+2*i])) for i,n in enumerate(NODES)}
        if port=='supply':
            result['dc_V']={n:values['v('+n.lower()+')'] for n in NODES}
            result['input_current_A']=-values['i(vin)'];result['reference_current_A']=-values['i(vref)']
            for d in devices:
                ident='@m.x'+d['name'].lower()+'.m'+d['model']
                d.update(current_A=values[ident+'[id]'],gm_S=values[ident+'[gm]'],gm_body_S=values[ident+'[gmbs]'],
                   ro_ohm=1/values[ident+'[gds]'],VDS_V=values[ident+'[vds]'],VGS_V=values[ident+'[vgs]'],VBS_V=values[ident+'[vbs]'])
    result['devices']=devices
    return result

def stamp(devices):
    K=np.zeros((6,6));inputs={'VIN':np.zeros(6),'R':np.zeros(6)};partitions={}
    for d in devices:
        kd=np.zeros((6,6));bd={'VIN':np.zeros(6),'R':np.zeros(6)}
        gm=d['gm_S'];body=d['gm_body_S'];ro=d['ro_ohm']
        controls=[(d['D'],1/ro),(d['G'],gm),(d['B'],body),(d['S'],-gm-body-1/ro)]
        for row,sign in [(d['D'],1),(d['S'],-1)]:
            if row not in NODES:continue
            i=NODES.index(row)
            for column,value in controls:
                if column in NODES:kd[i,NODES.index(column)]+=sign*value
                elif column in bd:bd[column][i]-=sign*value
        K+=kd
        for port in bd:inputs[port]+=bd[port]
        partitions[d['name']]=dict(matrix=kd,inputs=bd)
    return K,inputs,partitions

def solve(result):
    devices=result['devices'];K,b,parts=stamp(devices)
    answers={key:np.linalg.solve(K,rhs) for key,rhs in b.items()}
    contributions=[]
    for name,part in parts.items():
        for port in ['VIN','R']:
            if np.any(part['inputs'][port]):
                response=np.linalg.solve(K,part['inputs'][port])
                contributions.append(dict(device=name,input=port,injected_current_vector_A_per_V=part['inputs'][port].tolist(),
                     node_response_V_per_V=dict(zip(NODES,response.tolist()))))
    selected=[d for d in devices if d['name'] in SENSING]
    front,fb,_=stamp(selected)
    u=[NODES.index(x) for x in ['A','X','Y']];p=[NODES.index(x) for x in ['C','O']]
    eff=front[np.ix_(p,p)]-front[np.ix_(p,u)]@np.linalg.solve(front[np.ix_(u,u)],front[np.ix_(u,p)])
    effb={port:vec[p]-front[np.ix_(p,u)]@np.linalg.solve(front[np.ix_(u,u)],vec[u]) for port,vec in fb.items()}
    rc=1/eff[0,0];rs=1/eff[1,1]
    frontend=dict(RC_ohm=rc,RS_ohm=rs,gm_EO_S=float(eff[0,1]),gm_SC_S=float(eff[1,0]),
        gm_CV_S=float(effb['VIN'][0]),gm_SV_S=float(effb['VIN'][1]),gm_ER_S=float(effb['R'][0]),gm_SR_S=float(effb['R'][1]))
    # Exact DC elimination of the unchanged sensing internal nodes.
    kept=[NODES.index(x) for x in ['C','G','O']]
    reduced=K[np.ix_(kept,kept)]-K[np.ix_(kept,u)]@np.linalg.solve(K[np.ix_(u,u)],K[np.ix_(u,kept)])
    rb={port:vec[kept]-K[np.ix_(kept,u)]@np.linalg.solve(K[np.ix_(u,u)],vec[u]) for port,vec in b.items()}
    opened=reduced.copy();opened[0,2]-=frontend['gm_EO_S']
    sensing_return=float(np.linalg.det(reduced)/np.linalg.det(opened)-1)
    native_supply=result['supply']['O']['real'];native_reference=result['reference']['O']['real']
    reconstructed=dict(VIN=float(answers['VIN'][-1]),VREF=float(answers['R'][-1]))
    return dict(node_order=NODES,static_matrix=K.tolist(),supply_current_vector=b['VIN'].tolist(),reference_current_vector=b['R'].tolist(),
        reconstructed_gain=reconstructed,native_gain=dict(VIN=native_supply,VREF=native_reference),
        relative_errors=dict(VIN=abs(reconstructed['VIN']-native_supply)/abs(native_supply),VREF=abs(reconstructed['VREF']-native_reference)/abs(native_reference)),
        reconstructed_nodes={key:dict(zip(NODES,x.tolist())) for key,x in answers.items()},
        per_device_input_contributions=contributions,frontend=frontend,reduced_node_order=['C','G','O'],
        reduced_matrix=reduced.tolist(),reduced_inputs={key:value.tolist() for key,value in rb.items()},
        sensing_feedback_return_at_DC=sensing_return)


def build_summary(reports):
    cases={}
    for name,report in reports.items():
        a=report['analysis'];devices={d['name']:d for d in report['native']['devices']};f=a['frontend']
        if not all(d['model'].startswith('sky130_fd_pr__') for d in devices.values()):raise ValueError('Only public SKY130 devices are permitted.')
        label='supply_sourced_follower' if name in ['older_strong_LF','supply_sourced_follower'] else name
        origin={'selected':'circuits/power_refinement/selected.spice','published_baseline':'circuits/refined/core_seed.spice',
          'supply_sourced_follower':'results/recorded/compensation_screen_summary.json, case supply_actuator_compensation/cm0p_rz0_cs100p'}[label]
        matrix=np.array(a['reduced_matrix']);bv=np.array(a['reduced_inputs']['VIN']);br=np.array(a['reduced_inputs']['R'])
        plant=matrix[1:,1:]
        pc=float(np.linalg.solve(plant,-matrix[1:,0])[-1]);pv=float(np.linalg.solve(plant,bv[1:])[-1]);pr=float(np.linalg.solve(plant,br[1:])[-1])
        T=f['RC_ohm']*f['gm_EO_S']*pc
        paths={x['device']:x['node_response_V_per_V']['O'] for x in a['per_device_input_contributions'] if x['input']=='VIN'}
        sensing=sum(paths.get(x,0) for x in ['P1','P2'])
        gain=a['native_gain']['VIN'];ref=a['native_gain']['VREF']
        k=np.array(a['static_matrix']);b=np.array(a['supply_current_vector']);u=[0,1,2]
        held=np.linalg.solve(k[np.ix_(u,u)],b[u]);aheld=float(held[0])
        ro_p2=devices['P2']['ro_ohm'];gm_p2=devices['P2']['gm_S']
        complex_gain=complex(report['native']['supply']['O']['real'],report['native']['supply']['O']['imag'])
        cases[label]=dict(public_circuit_origin=origin,technology='Public SKY130 tt at27C',
            native_VIN_gain_V_per_V=gain,native_VIN_gain_imaginary_V_per_V=float(complex_gain.imag),
            native_VIN_gain_magnitude_V_per_V=abs(complex_gain),native_VIN_gain_dB=float(20*np.log10(abs(complex_gain))),
            native_VREF_gain_V_per_V=ref,reconstructed_gain=a['reconstructed_gain'],reconstruction_relative_errors=a['relative_errors'],
            signed_supply_path_V_per_V=paths,sensing_path_sum_V_per_V=sensing,remaining_power_driver_path_V_per_V=sum(paths.values())-sensing,
            gmCV_S=f['gm_CV_S'],gmEO_S=f['gm_EO_S'],gmER_S=f['gm_ER_S'],RC_ohm=f['RC_ohm'],RS_ohm=f['RS_ohm'],
            roP2_ohm=ro_p2,P2_gm_S=gm_p2,P2_ro_current_coefficient_A_per_V=1/ro_p2,
            P2_ro_fraction_of_gmCV=(1/ro_p2)/f['gm_CV_S'],
            mirror_A_supply_gain_with_C_O_R_held_zero=aheld,P2_gm_supply_remainder_A_per_V=gm_p2*(1-aheld),
            sensing_supply_floor_V_per_V=f['gm_CV_S']/f['gm_EO_S'],
            sensing_supply_floor_dB=float(20*np.log10(abs(f['gm_CV_S']/f['gm_EO_S']))),
            sensing_return_at_DC=T,plant_command_gain=pc,plant_supply_gain=pv,plant_reference_gain=pr,
            command_supply_gain_with_output_held=f['RC_ohm']*f['gm_CV_S'],command_reference_gain_with_output_held=f['RC_ohm']*f['gm_ER_S'],
            command_output_gain_magnitude=f['RC_ohm']*f['gm_EO_S'],
            closed_formula_VIN=(pv+pc*f['RC_ohm']*f['gm_CV_S'])/(1+T),
            closed_formula_VREF=(pr+pc*f['RC_ohm']*f['gm_ER_S'])/(1+T),
            frontend_part_of_VIN=pc*f['RC_ohm']*f['gm_CV_S']/(1+T),
            plant_part_of_VIN=pv/(1+T),
            source_dataset=CASE_DIR[label]+'/diagnosis.json')
    selected=cases['selected'];old=cases.get('supply_sourced_follower');baseline=cases.get('published_baseline')
    return dict(evidence='Native unchanged connected circuits at 50 mA with 1 Hz supply or reference excitation, followed by a static gm, body gm, ro reconstruction.',
      partition_method='Analytical superposition of each transistor VIN terminal forcing vector through the same connected DC matrix. No separate native supply sources or topology changes were used for the path partition.',
      public_scope='Selected public SKY130 circuit, its published public SKY130 baseline, and the existing public SKY130 supply sourced follower alternative only. No proprietary circuit is included.',
      gain_convention='native_VIN_gain_dB uses the complex magnitude at1Hz. native_VIN_gain_V_per_V is the real part used for the DC reconstruction comparison.',
      cases=cases,
      selected_improvement_over_published_baseline_dB=(baseline['native_VIN_gain_dB']-selected['native_VIN_gain_dB']) if baseline else None,
      selected_degradation_from_older_strong_LF_dB=(selected['native_VIN_gain_dB']-old['native_VIN_gain_dB']) if old else None,
      interpretation=['The selected sensing mirror finite output resistance dominates the low frequency supply error.',
        'Increasing command loop gain alone approaches gmCV/gmEO when the plant supply term stays bounded. This conditional limit is not a universal impossibility bound.',
        'The older stronger low frequency circuit obtains a small residual from cancellation of a positive sensing path and negative supply sourced actuator paths. Its low frequency result was not preserved in the selected circuit.',
        'The published baseline is the output sourced refined core near minus19.42dB. It is not the older supply sourced actuator near minus61.46dB.',
        'This diagnostic does not optimize topology, establish PVT robustness, or validate complete internal stability.'])


reports={}
for name,path in SOURCES.items():
    text,devices=read_circuit(path)
    native_result=run(name,text,devices)
    report=dict(evidence='Unchanged native circuit diagnostic and DC parameter reconstruction.',
      native=native_result,analysis=solve(native_result))
    (HERE/CASE_DIR[name]/'diagnosis.json').write_text(json.dumps(report,indent=2))
    reports[name]=report
summary=build_summary(reports)
(HERE/'summary.json').write_text(json.dumps(summary,indent=2))
for name,row in summary['cases'].items():
    print(json.dumps(dict(case=name,VIN_gain_dB=row['native_VIN_gain_dB'],VREF_gain=row['native_VREF_gain_V_per_V'],
        gmCV_uS=row['gmCV_S']*1e6,gmEO_uS=row['gmEO_S']*1e6,roP2_kohm=row['roP2_ohm']/1e3,
        conditional_floor_dB=row['sensing_supply_floor_dB']),ensure_ascii=True))
