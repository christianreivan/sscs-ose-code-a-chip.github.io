# Supply Disturbance and Gate Drive in a SKY130 PFET Regulator

Author: Christian Reivan  
Affiliation:  
GitHub: [christianreivan](https://github.com/christianreivan)

This notebook investigates the bias, headroom, supply response, and gate drive of a PFET regulator using the public SKY130 device models. It combines explicit transistor connections, analytical derivations, native ngspice experiments, and reproducible counterexamples to assess which proposed changes improve the circuit.

The final refinement combines a longer PFET pass device, a stronger finite driver, a parallel PFET helper and a 1 pF capacitor between output and pass gate. At TT 27 °C and 50 mA, it improves rejection by at least 4.45 dB across the sampled 1 to 10 MHz band and by 1.01 to 1.94 dB across 1 to 100 kHz relative to the earlier refined core. For the same 5 mA to 50 mA to 5 mA transition, the output minimum improves from 0.467 V to 0.537 V and the maximum falls from 0.910 V to 0.891 V. COUT remains 200 pF. VIN overhead increases from 52.9 µA to 105.3 µA, excluding the separate reference current and bias generator power.

This is a measured improvement in native transistor simulation, not a qualified regulator. Fixed bias checks expose driver saturation failure at SS 27 °C and TT 0 °C. The SS result amplifies supply disturbance at 1 and 10 MHz. The substantial remaining transient excursion, physical bias generation, startup, internal loop margins and extracted parasitics require further work. Both successful and rejected experiments are retained in the notebook.

## Start here

Open [the notebook](sky130_pfet_ldo.ipynb) and run its cells in order. It includes saved results and embedded figures for inspection, plus executable cells for reproduction. The circuit sources are under `circuits`, portable runners are under `scripts`, and recorded results are under `results/recorded`. Generated native outputs are created under `results` when the experiments run.

Install Python 3.10 or newer, the packages in `requirements.txt`, and ngspice. The recorded execution uses Python 3.12 and ngspice 47. The command executable must be on `PATH`, or its path must be supplied through the `NGSPICE_EXE` environment variable. The notebook and runners record the actual executable version and hash. The simulator is not bundled. See the [official ngspice download page](https://ngspice.sourceforge.io/download.html).

From this project directory:

```text
python -m pip install -r requirements.txt
python scripts/run_core.py
python scripts/run_load_screen.py
python scripts/run_refined.py
python scripts/run_transient_screen.py
python scripts/run_cff_screen.py
python scripts/run_pass_disturbance.py
python scripts/run_supply_actuator.py
python scripts/check_power_equations.py
python scripts/run_power_refinement.py
python scripts/check_reproduction.py
```

`run_core.py` reproduces the first DC seed. `run_load_screen.py` evaluates the fixed seed at seven TT loads and eight bounded process and temperature cases. `run_refined.py` evaluates the separate refined circuit at seven TT loads and obtains its supply and reference AC responses at 50 mA. No parameter is independently retuned for each load.

`run_transient_screen.py` applies the declared 5 mA to 50 mA to 5 mA load transition. `run_cff_screen.py` evaluates five supply to gate capacitances and a closed pole diagnostic with an explicitly designated input. A clean, nonempty pole result is required for a completed diagnostic. This does not substitute for a loop margin measurement.

`run_pass_disturbance.py` fixes the output voltage and imposes ideal gate tracking. It measures pass current disturbance, not connected LDO PSR. Its ideal null gain is a design target and does not establish a realizable gate driver. The numerical depth of an ideal null must not be interpreted as circuit performance.

The isolated pass and gate charge experiments use `results/recorded/refined_operating_point.json` as a declared fixed bias fixture. They do not automatically adapt that fixture when transistor geometry or bias is changed. A modified design requires a newly recorded fixture and comparison values. The connected circuit experiments solve their own operating points on every run.

`run_supply_actuator.py` moves the actuator source and body from the regulated output to VIN and uses its declared replacement geometry. Every other circuit value remains fixed. This improves the tested static load behavior but removes the original local FVF action and produces substantial MHz supply peaking. It is an evaluated alternative, not the final design.

`run_power_refinement.py` reproduces the selected final circuit, seven nominal load points, supply and reference responses, native pole diagnostics, load transitions, fixed corner checks, and the declared driver and capacitor ablations. The exact selected transistor connections are in `circuits/power_refinement/selected.spice`. Its recorded comparison is in `results/recorded/power_refinement.json`. No load or corner receives an independently retuned bias. The notebook derives the reduced model before invoking this experiment.

`check_power_equations.py` checks the explicit three node polynomial transfers and the two declared ordered return ratios against independent matrix calculations. It uses synthetic parameter cases to verify algebra. It does not qualify a native model approximation or measure transistor circuit loop margins.

## Model provenance and scope

The bundled models contain standard and LVT NFET and PFET families at five corners. They derive from the [official SKY130 primitive repository](https://github.com/google/skywater-pdk-libs-sky130_fd_pr) at commit `f62031a1be9aefe902d6d54cddd6f59b57627436`. The original include directives were expanded into portable corner files. Electrical model parameters were not changed. Source and generated hashes are recorded in `models/MODEL_PROVENANCE.json`, and the original model license is preserved.

The instances use default zero diffusion areas and perimeters, `ad`, `as`, `pd`, and `ps`. Native model intrinsic and default overlap behavior is included, but diffusion geometry, interconnect, and layout extraction are not qualified. The bundled model subset is not a full layout PDK.

Reference and bias ports are ideal voltage sources. Core overhead means VIN current minus external load. It excludes the separately supplied VREF current and all generator power. The refined nominal point draws approximately 13.4 µA from the reference port separately. No physical reference or bias generator is claimed.

Only public SKY130 data is included. Analytical equations, native transistor experiments, and unvalidated proposed extensions are identified separately. The connected core does not include the proposed active replica cancellation branches.

The original recorded results remain under `results/recorded`. The repository includes the executed notebook, model files, circuit sources, derivations and recorded summaries. Reproduction creates separate result folders containing the actual netlists, logs, and numerical tables. `results/REPRODUCTION_CHECK.json` compares reproduced results with the independently retained values. Numerical agreement establishes reproduction, not performance qualification.

Before each native run, the runner removes only the explicitly named generated output files in that run directory. A simulator error, missing fresh output, empty data table, or empty requested pole diagnostic stops execution. Older generated curves cannot be reused as if a failed rerun had succeeded. The recorded reference results remain intact.

## License

The project uses Apache License 2.0. The model sources retain their original copyright notices and license. Refer to `LICENSE` and `models/LICENSE`.
