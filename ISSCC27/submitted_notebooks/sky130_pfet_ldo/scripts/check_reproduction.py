"""Compare package executions against the separately recorded native results."""
from pathlib import Path
import json
from runtime_support import PROJECT, verify_models


def read(name):
    return json.loads((PROJECT/'results'/name).read_text())


def main():
    verify_models()
    original=read('recorded/load_screen.json')
    repeated=read('load_screen.json')
    old={row['name']:row for row in original['rows']}
    dc_error=max(abs(row['VOUT_V']-old[row['name']]['VOUT_V']) for row in repeated['rows'] if row['status']=='DC_COMPLETE')
    assert len(repeated['rows'])==len(original['rows'])==15
    assert all(row['status']==old[row['name']]['status'] for row in repeated['rows'])
    assert dc_error<1e-9
    refined=read('refined/summary.json')
    point=read('recorded/refined_operating_point.json')
    final=next(row for row in refined['load_rows'] if row['external_load_A']==.05)
    refined_error=abs(final['voltages_V']['O']-point['voltages_V']['O'])
    assert refined_error<1e-9
    cff=read('cff_screen/cff_results.json')
    saved_cff=read('recorded/cff_results.json')
    ac_error=max(abs(a['magnitude_dB']-b['magnitude_dB'])
                 for case,oldcase in zip(cff['cases'],saved_cff['cases'])
                 for port in ('supply','reference')
                 for a,b in zip(case[port]['samples'],oldcase[port]['samples']))
    assert ac_error<1e-8
    assert all(case['pole_diagnostic']['status']=='success' and case['pole_diagnostic']['poles']
               for case in cff['cases'])
    actuator=read('supply_actuator/native_results.json')
    saved_actuator=read('recorded/supply_actuator.json')
    actuator_dc_error=max(abs(a['voltages_V']['O']-b['voltages_V']['O'])
                          for a,b in zip(actuator['load_rows'],saved_actuator['load_rows']))
    actuator_ac_error=max(abs(a['magnitude_dB']-b['magnitude_dB']) for port in ('supply','reference')
                         for a,b in zip(actuator['AC'][port]['samples'],saved_actuator['AC'][port]['samples']))
    assert actuator_dc_error<1e-9 and actuator_ac_error<1e-8
    assert actuator['pole_diagnostic']['status']=='success' and actuator['pole_diagnostic']['poles']
    power=read('power_refinement/summary.json')['selected']
    saved_power=read('recorded/power_refinement.json')['selected']
    assert len(power['load_rows'])==len(saved_power['load_rows'])==7
    power_dc_error=max(abs(a['voltages_V']['O']-b['voltages_V']['O'])
                       for a,b in zip(power['load_rows'],saved_power['load_rows']))
    power_ac_error=max(abs(a['magnitude_dB']-b['magnitude_dB'])
                       for port in ('supply_samples','reference_samples')
                       for a,b in zip(power[port],saved_power[port]))
    power_transient_error=max(abs(power['transient'][key]-saved_power['transient'][key])
                              for key in ('rising_load_minimum_output_V','falling_load_maximum_output_V'))
    assert power_dc_error<1e-9 and power_ac_error<1e-8 and power_transient_error<1e-8
    assert all(r['poles'] for r in power['poles_by_load'])
    result=dict(evidence='Native execution portability comparison only',
                baseline_DC_cases=15,maximum_baseline_output_difference_V=dc_error,
                refined_50mA_output_difference_V=refined_error,
                CFF_cases=5,maximum_AC_sample_difference_dB=ac_error,
                all_CFF_pole_diagnostics_nonempty=True,
                supply_actuator_DC_cases=len(actuator['load_rows']),
                maximum_supply_actuator_output_difference_V=actuator_dc_error,
                maximum_supply_actuator_AC_difference_dB=actuator_ac_error,
                selected_power_DC_cases=7,
                maximum_selected_output_difference_V=power_dc_error,
                maximum_selected_AC_difference_dB=power_ac_error,
                maximum_selected_transient_extrema_difference_V=power_transient_error,
                limitation='Agreement verifies packaging and reproduction, not circuit performance qualification.')
    (PROJECT/'results/REPRODUCTION_CHECK.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
