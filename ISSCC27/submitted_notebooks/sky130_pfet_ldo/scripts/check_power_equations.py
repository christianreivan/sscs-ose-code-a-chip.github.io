"""Algebra check of the reduced final PU and reciprocal CAG circuit."""
from pathlib import Path
import json
import numpy as np
PROJECT=Path(__file__).resolve().parents[1]
OUTPUT=PROJECT/'results/analytical'
OUTPUT.mkdir(parents=True,exist_ok=True)
rng=np.random.default_rng(202611019)
error=dict(supply=0.,reference=0.,load=0.,denominator=0.,CAG_affinity=0.,sensing_return_normalized=0.,follower_return_normalized=0.)
def coeff(p,cag):
    rc,rg,ro,rof,rop,rou,roh=p['R']
    P,F,U,H,EO,ER,SC,SR,CV,SV=p['gm']
    S,Q,T0,CC0,CG0,CO0,CU,CI,CP=p['C']
    T=T0+cag;CC=CC0+S+Q+CU;CG=CG0+Q+T;CO=CO0+S+T
    w=[(F+U)*(P-1/rof)-(H+1/rg)*(SC-F),
       -(F+U)*T-Q*(P-1/rof)+(H+1/rg)*S-CG*(SC-F),Q*T+CG*S]
    z=[-(P-1/rof)/rc,T/rc-CC*(P-1/rof)-Q*(SC-F),CC*T+Q*S]
    y=[(H+1/rg)/rc,CG/rc+CC*(H+1/rg)+Q*(F+U),CC*CG-Q*Q]
    d=[EO*w[0]-(F+1/rof)*z[0]+(F+1/ro)*y[0],
       EO*w[1]-S*w[0]-(F+1/rof)*z[1]-T*z[0]+(F+1/ro)*y[1]+CO*y[0],
       EO*w[2]-S*w[1]-(F+1/rof)*z[2]-T*z[1]+(F+1/ro)*y[2]+CO*y[1],
       -S*w[2]-T*z[2]+CO*y[2]]
    kv=H+1/roh+U+1/rou;ko=P+1/rop+SV
    n=[CV*w[0]+kv*z[0]+ko*y[0],CV*w[1]+CU*w[0]+kv*z[1]+CI*z[0]+ko*y[1]+CP*y[0],
       CV*w[2]+CU*w[1]+kv*z[2]+CI*z[1]+ko*y[2]+CP*y[1],CU*w[2]+CI*z[2]+CP*y[2]]
    nr=[ER*w[i]+SR*y[i] for i in range(3)]
    return dict(d=d,n=n,r=nr,y=y,w=w,CC=CC,CG=CG,CO=CO,T=T)

for _ in range(1000):
    p=dict(R=10**rng.uniform(1,6,7),gm=10**rng.uniform(-6,0,10),C=10**rng.uniform(-14,-9,9))
    p['gm'][6:]*=rng.choice([-1,1],4)
    cag=10**rng.uniform(-14,-10)
    k=coeff(p,cag);k0=coeff(p,0);k2=coeff(p,2*cag)
    rc,rg,ro,rof,rop,rou,roh=p['R'];P,F,U,H,EO,ER,SC,SR,CV,SV=p['gm'];S,Q,T0,CC0,CG0,CO0,CU,CI,CP=p['C']
    s=1j*10**rng.uniform(0,10)
    M=np.array([[1/rc+s*k['CC'],-s*Q,EO-s*S],
       [F+U-s*Q,H+1/rg+s*k['CG'],-F-1/rof-s*k['T']],
       [SC-F-s*S,P-1/rof-s*k['T'],F+1/ro+s*k['CO']]],complex)
    val=lambda x:np.polynomial.polynomial.polyval(s,x)
    relative=lambda a,b:abs(a-b)/max(abs(a),abs(b),1e-20)
    error['denominator']=max(error['denominator'],relative(val(k['d']),np.linalg.det(M)))
    for name,poly,rhs in [('supply',k['n'],[CV+s*CU,H+1/roh+U+1/rou+s*CI,P+1/rop+SV+s*CP]),
                         ('reference',k['r'],[ER,0,SR]),('load',[-x for x in k['y']],[0,0,-1])]:
        error[name]=max(error[name],relative(val(poly)/val(k['d']),np.linalg.solve(M,rhs)[2]))
    for name in ['d','n','r']:
        a=np.array(k2[name])+np.array(k0[name]);b=2*np.array(k[name])
        error['CAG_affinity']=max(error['CAG_affinity'],float(np.max(np.abs(a-b)/np.maximum(np.maximum(np.abs(a),np.abs(b)),1e-35))))
    inner=M.copy();inner[0,2]=-s*S
    opened=inner.copy();opened[1,0]=U-s*Q;opened[1,2]=-1/rof-s*k['T'];opened[2,0]=SC-s*S;opened[2,2]=1/ro+s*k['CO']
    pe=dict(p);pe['gm']=p['gm'].copy();pe['gm'][4]=0
    pf=dict(pe);pf['gm']=pe['gm'].copy();pf['gm'][1]=0
    dinner=val(coeff(pe,cag)['d']);dopened=val(coeff(pf,cag)['d'])
    ne=EO*val(k['w'])
    lf=[F*(P-1/rof+H+1/rg)/rc,
        F*((k['CG']-k['T'])/rc+(k['CC']-S)*(P-1/rof+H+1/rg)+Q*(SC+U-1/rof+1/ro)),
        F*((k['CC']-S)*(k['CG']-k['T'])+Q*(k['CO']-S-k['T']-Q))]
    nf=val(lf);dd=val(k['d'])
    for name,formula,direct in [('sensing_return_normalized',ne/dinner,np.linalg.det(M)/np.linalg.det(inner)-1),
       ('follower_return_normalized',nf/dopened,np.linalg.det(inner)/np.linalg.det(opened)-1)]:
        error[name]=max(error[name],abs(formula-direct)/max(1,abs(formula),abs(direct)))
if max(error.values())>1e-7:raise AssertionError(error)
result=dict(evidence='Synthetic algebra check of a selected three node model only. No native simulation or qualification.',
    cases=1000,transfer_evaluations=3000,ordered_loop_evaluations=2000,
    loop_error_normalization='Absolute discrepancy divided by max(1, magnitudes of both compared returns).',
    maximum_relative_errors={k:float(v) for k,v in error.items()})
(OUTPUT/'power_equations_check.json').write_text(json.dumps(result,indent=2))
print(json.dumps(dict(evidence=result['evidence'],cases=result['cases'],transfer_evaluations=result['transfer_evaluations'],ordered_loop_evaluations=result['ordered_loop_evaluations'],maximum_normalized_error=max(result['maximum_relative_errors'].values())),indent=2))
