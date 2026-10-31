# Supply Disturbance and Gate Drive in a SKY130 PFET Regulator

Author: Christian Reivan  
Affiliation:  
GitHub: [christianreivan](https://github.com/christianreivan)

This notebook studies a PFET regulator with VIN = 1.2 V, VREF = 0.8 V, load current from 0 to 50 mA and COUT = 200 pF. It includes transistor connections, expanded transfer functions, ordered loop returns and ngspice simulations using public SKY130 models.

The selected circuit combines a longer pass transistor, stronger gate drive, a parallel PFET helper and a 1 pF capacitor between output and pass gate. At TT 27 °C and 50 mA, supply transfer is −20.43 dB at 1 kHz, −20.25 dB at 100 kHz, −18.27 dB at 1 MHz and −9.31 dB at 10 MHz. The improvement of at least 4.45 dB across 1 to 10 MHz is relative to the earlier SKY130 circuit. The selected result does not meet a −40 dB rejection benchmark.

For a 5 mA to 50 mA to 5 mA load transition with 100 ns edges, the output minimum improves from 0.467 V to 0.537 V and the maximum falls from 0.910 V to 0.891 V. VIN overhead rises from 52.9 µA to 105.3 µA. The reference supplies a separate 13.4 µA. Reference and bias generator power is excluded.

The remaining transient excursion is substantial. NB loses saturation at SS 27 °C and TT 0 °C, with poor supply rejection at those corners. Startup, mismatch, physical reference and bias circuits, and extracted layout effects require further work.

The low frequency limit is dominated by the sensing mirror supply response. The reduced sensing coefficients predict about −20.56 dB of supply coupling, close to the complete circuit result. The notebook separates this mechanism from the main pass transistor output resistance path.

## Run the notebook

Open [the notebook](sky130_pfet_ldo.ipynb) and run its cells in order. Saved plots and tables can be inspected without running a simulation.

Install Python 3.10 or newer, the packages in `requirements.txt`, and [ngspice](https://ngspice.sourceforge.io/download.html). The recorded simulations use Python 3.12 and ngspice 47. Put ngspice on PATH or set `NGSPICE_EXE` to its executable.

```text
python -m pip install -r requirements.txt
```

The circuit sources are in `circuits`, experiment scripts are in `scripts`, and recorded results are in `results/recorded`. The selected circuit is `circuits/power_refinement/selected.spice`. Its experiment is reproduced by `scripts/run_power_refinement.py`. The notebook also evaluates the earlier core, direct supply to gate capacitance, the source connection alternative and the declared driver and capacitor variations. See `REPRODUCING.txt` for the complete command sequence.

## Models and assumptions

The bundled transistor models come from the [official SKY130 primitive library](https://github.com/google/skywater-pdk-libs-sky130_fd_pr). Electrical model parameters are unchanged. Five process corners are included. The subset supports circuit simulation and is not a complete layout PDK.

The instances use zero diffusion areas and perimeters. Intrinsic and default overlap capacitances are included, but extracted diffusion and interconnect capacitances are absent. Reference and bias ports are ideal voltage sources. VIN overhead is supply current minus external load and excludes reference current and generator power.

The isolated pass and gate charge experiments use `results/recorded/refined_operating_point.json` as a fixed bias fixture. Update that fixture when changing their device geometry or bias. Connected experiments solve their own operating points.

The reduced equations are checked independently against their node equations. This verifies the algebra. Native pole diagnostics inspect observable transfer poles and do not establish every internal mode or gain and phase margin.

## License

The project uses Apache License 2.0. Original model copyright notices and licenses are preserved in `LICENSE` and `models/LICENSE`.
