"""Execute the frozen core DC seed with local bundled models."""
from pathlib import Path
import json
import subprocess
from runtime_support import PROJECT, find_ngspice, verify_models, record_simulator, relative_library_path, prepare_native_outputs, check_native_completion


def main():
    executable = find_ngspice()
    library = verify_models()
    record_simulator(executable)
    destination = PROJECT/'results/core_reproduction'
    destination.mkdir(exist_ok=True)
    source = (PROJECT/'circuits/core_extracted.spice').read_text()
    source = source.replace('../models/sky130_mos.lib.spice', relative_library_path(destination))
    (destination/'input.spice').write_text(source)
    outputs=prepare_native_outputs(source,destination)
    reply = subprocess.run([str(executable),'-b','input.spice'],cwd=destination,
                           capture_output=True,text=True,timeout=60)
    (destination/'run.log').write_text(reply.stdout+'\n'+reply.stderr)
    check_native_completion(reply,reply.stdout+'\n'+reply.stderr,outputs)
    if reply.returncode or 'No. of Data Rows : 1' not in reply.stdout:
        raise RuntimeError('Native DC run did not complete. Inspect results/core_reproduction/run.log.')
    print(reply.stdout)


if __name__ == '__main__':
    main()
