"""Portable simulator lookup and bundled model verification."""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess

PROJECT = Path(__file__).resolve().parents[1]


def find_ngspice():
    explicit = os.environ.get('NGSPICE_EXE')
    found = explicit or shutil.which('ngspice') or shutil.which('ngspice_con')
    if not found:
        raise RuntimeError('Install ngspice or set NGSPICE_EXE to its executable path.')
    executable = Path(found).expanduser().resolve()
    if not executable.is_file():
        raise FileNotFoundError(executable)
    return executable


def verify_models():
    folder = PROJECT/'models'
    provenance = json.loads((folder/'MODEL_PROVENANCE.json').read_text())
    for row in provenance['generated_models']:
        path = folder/row['file']
        if hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
            raise RuntimeError('Bundled model hash mismatch: '+row['file'])
    library = folder/'sky130_mos.lib.spice'
    if hashlib.sha256(library.read_bytes()).hexdigest() != provenance['library_sha256']:
        raise RuntimeError('Model selection library hash mismatch')
    return library.resolve()


def record_simulator(executable=None):
    executable = executable or find_ngspice()
    reply = subprocess.run([str(executable), '--version'], text=True, capture_output=True, timeout=15)
    if reply.returncode:
        raise RuntimeError(reply.stderr)
    result = {'version_output':reply.stdout.strip(),
              'executable_sha256':hashlib.sha256(executable.read_bytes()).hexdigest()}
    (PROJECT/'results').mkdir(exist_ok=True)
    (PROJECT/'results/SIMULATOR_PROVENANCE.json').write_text(json.dumps(result,indent=2))
    return result


def relative_library_path(work_directory):
    library=verify_models()
    alias=library.parent/'m.lib'
    if alias.exists():
        if hashlib.sha256(alias.read_bytes()).digest()!=hashlib.sha256(library.read_bytes()).digest():
            raise RuntimeError('Short model library alias differs from the verified library')
        library=alias
    return Path(os.path.relpath(library, work_directory)).as_posix()


def prepare_native_outputs(source, work_directory):
    """Remove only explicitly named generated outputs before a new native run."""
    directory = Path(work_directory).resolve()
    results = (PROJECT/'results').resolve()
    if not directory.is_relative_to(results):
        raise ValueError('Native outputs must remain within the project results directory.')
    outputs = []
    for match in re.finditer(r'(?im)^\s*(?:wrdata|write)\s+(?:"([^"]+)"|(\S+))', source):
        path = (directory/(match.group(1) or match.group(2))).resolve()
        if not path.is_relative_to(directory):
            raise ValueError('Generated output path escapes the native run directory.')
        if path not in outputs:
            if path.exists():
                if not path.is_file():
                    raise ValueError('Expected a generated output file: '+path.name)
                path.unlink()
            outputs.append(path)
    return outputs


def check_native_completion(completed, log, outputs=()):
    """Reject simulator failures and missing or empty fresh result tables."""
    errors = [line.strip() for line in log.splitlines() if re.search(
        r'(?i)\baborted\b|\berror\b|\bfatal\b|shorted on the way|no such vector|doAnalyses:', line)]
    if completed.returncode or errors:
        detail = '\n'.join(errors) or 'Simulator exit status '+str(completed.returncode)
        raise RuntimeError('Native simulation failed. '+detail)
    for path in outputs:
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError('Native simulation did not create a fresh result: '+path.name)
        if path.suffix.lower() in {'.txt', '.csv'}:
            lines = path.read_text().splitlines()
            if len(lines) < 2 or not lines[1].split():
                raise RuntimeError('Native result table contains no data: '+path.name)
            try:
                float(lines[1].split()[0])
            except ValueError as exc:
                raise RuntimeError('Native result table does not contain numeric data: '+path.name) from exc


if __name__ == '__main__':
    verify_models()
    print(json.dumps(record_simulator(),indent=2))
