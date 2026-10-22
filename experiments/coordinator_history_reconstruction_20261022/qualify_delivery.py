"""Package and verify a fixed candidate after its read-only timing comparison."""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--extraction-parent', type=Path, required=True)
    args = parser.parse_args()
    v = HERE/'validation'
    if (v/'delivery.json').exists():
        parser.error('Delivery already recorded; do not overwrite accepted evidence')
    report = json.loads((v/'rich_history_comparison.json').read_text())
    local = json.loads((v/'local_tests.json').read_text())
    if report['status'] != 'MEASURED' or report['correctness'] != 'PASS' or local['result'] != 'PASS':
        raise ValueError('Correctness qualification is not complete')
    spec = importlib.util.spec_from_file_location('reconstruction_compare', HERE/'compare.py')
    compare = importlib.util.module_from_spec(spec); spec.loader.exec_module(compare)
    if compare.inventory(ROOT) != report['candidate_inventory']:
        raise ValueError('Candidate source changed after measurement')
    ref = report['reference']['idle_cycle_seconds']; candidate = report['candidate']['idle_cycle_seconds']
    cold = [r['seconds'] for r in report['candidate_cold_reopens']]
    p = HERE/'README.md'
    with p.open('a') as f:
        f.write('\nLocal final affected checks: %d PASS in %.3fs.\n\n' % (local['tests'], local['seconds']))
        f.write('| Same saved native fixture | Median | p95 | Maximum | Samples |\n| --- | ---: | ---: | ---: | ---: |\n')
        for name, values in [('Accepted command-30 reference', ref), ('Final candidate', candidate)]:
            f.write('| %s | %.3fs | %.3fs | %.3fs | %d |\n' % (name, values['median'], values['p95'], values['maximum'], values['count']))
        f.write('\nCandidate cold reopens: '+', '.join('%.3fs' % x for x in cold)+'. All PASS against 10s.\n')
        f.write('Idle gate: '+report['performance']+' (p95 <= 0.5s, maximum <= 1s). Overall qualification remains INCOMPLETE.\n')
    spec = importlib.util.spec_from_file_location('reconstruction_bundle', HERE/'build_bundle.py')
    builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
    delivery = builder.build(args.destination)
    archive = Path(delivery['archive'])
    args.extraction_parent.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as z:
        z.extractall(args.extraction_parent)
        inventory = json.loads(z.read(delivery['folder']+'/SOURCE_INVENTORY.json'))
        (v/'delivered_README.md').write_bytes(z.read(delivery['folder']+'/README.md'))
    extracted = args.extraction_parent/delivery['folder']
    run = subprocess.run([sys.executable, '-I', '-B', str(extracted/'verify_source.py')],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120)
    (v/'extracted_tests.txt').write_text(run.stdout)
    if run.returncode:
        raise RuntimeError('Extracted verification failed: '+run.stdout[-5000:])
    tests = json.loads(sorted((extracted/'runs/verification').glob('*.json'))[-1].read_text())
    if tests['result'] != 'PASS' or tests['tests'] != local['tests']:
        raise ValueError('Extracted test result/count differs')
    altered = extracted/'coordinator/src/mb_watchlist_coordinator/sampling_requests.py'
    original = altered.read_bytes()
    try:
        altered.write_bytes(original+b'\n# deliberate inventory-tamper qualification\n')
        refusal = subprocess.run([sys.executable, '-I', '-B', str(extracted/'verify_source.py')],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30)
        if refusal.returncode == 0 or 'Changed bundled source' not in refusal.stdout or 'Ran ' in refusal.stdout:
            raise AssertionError('Changed source did not fail before verification')
    finally:
        altered.write_bytes(original)
    (v/'delivery_source_inventory.json').write_text(json.dumps(inventory, indent=2)+'\n')
    (v/'extracted_qualification.json').write_text(json.dumps(dict(tests,
        extraction_path_with_spaces=True, source_inventory_checked=True,
        altered_source_refused_before_tests=True, delivery_sha256=delivery['sha256']), indent=2)+'\n')
    (v/'delivery.json').write_text(json.dumps(delivery, indent=2)+'\n')
    with p.open('a') as f:
        f.write('\nExtracted final handoff: %d PASS in %.3fs, with a path containing spaces; altered source refused before tests.\n' % (tests['tests'], tests['seconds']))
        f.write('Delivery: `%s`, %d bytes, %d files, SHA-256 `%s`.\n' % (archive.name, delivery['bytes'], delivery['files'], delivery['sha256']))
        f.write('Native Windows command 31 remains PENDING; no production installation is made.\n')
    print(json.dumps({'delivery': delivery, 'extracted_tests': tests,
        'candidate_idle_seconds': candidate, 'performance': report['performance'],
        'qualification': 'INCOMPLETE'}, indent=2))


if __name__ == '__main__':
    main()
