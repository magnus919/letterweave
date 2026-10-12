"""Build offline, install into a clean disposable venv, test outside source."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import venv

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-python", required=True, type=Path,
                        help="Existing interpreter with pip and setuptools; nothing is downloaded")
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "package-verification.json")
    args = parser.parse_args()
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON") and not k.startswith("PIP_")}
    env.update({"PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_CONFIG_FILE": os.devnull,
                "PYTHONNOUSERSITE": "1"})
    evidence = {"scope": "offline isolated package verification; fixture data only", "network_downloads": False,
                "global_changes": False, "pythonpath_present": False, "steps": []}
    with tempfile.TemporaryDirectory(prefix="email-forge-package-") as folder:
        base = Path(folder)
        source, dist, work = base / "source", base / "dist", base / "work"
        source.mkdir()
        dist.mkdir()
        work.mkdir()
        env["PIP_CACHE_DIR"] = str(base / "pip-cache")
        shutil.copytree(ROOT / "email_corpus_forge", source / "email_corpus_forge", ignore=shutil.ignore_patterns("__pycache__"))
        for name in ("pyproject.toml", "LICENSE", "README.md"):
            shutil.copy2(ROOT / name, source / name)
        shutil.copytree(ROOT / "tests", base / "tests", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(ROOT / "LICENSE", base / "LICENSE")
        for name in ('verify_dataset.py','verify_scenario_plans.py','assemble_model_release.py','build_contrast_plan.py'):
            verifier = ROOT / 'tools' / name
            if verifier.exists():
                (base / 'tools').mkdir(exist_ok=True)
                shutil.copy2(verifier, base / 'tools' / name)
        if (ROOT / 'scenario-plans').exists():
            shutil.copytree(ROOT / 'scenario-plans', base / 'scenario-plans')

        def execute(label, command):
            result = subprocess.run(command, cwd=work, env=env, text=True, capture_output=True)
            evidence["steps"].append({"name": label, "exit_code": result.returncode})
            print(f"{label}: exit {result.returncode}", flush=True)
            if result.returncode:
                # Exact diagnostic available to caller without silently substituting an install.
                print(result.stdout + result.stderr, file=sys.stderr)
                raise RuntimeError(label + " failed")
            return result

        build_versions = execute("existing build tooling", [str(args.build_python), "-c",
            "import importlib.metadata,json; print(json.dumps({x:importlib.metadata.version(x) for x in ['pip','setuptools']}))"])
        evidence["build_tool_versions"] = json.loads(build_versions.stdout)
        execute("offline wheel build", [str(args.build_python), "-m", "pip", "wheel", "--no-index", "--no-deps",
                                       "--no-build-isolation", "--no-cache-dir", "--wheel-dir", str(dist), str(source)])
        wheels = list(dist.glob("*.whl"))
        if len(wheels) != 1:
            raise RuntimeError("expected exactly one local wheel")
        evidence["wheel"] = {"name": wheels[0].name, "sha256": hashlib.sha256(wheels[0].read_bytes()).hexdigest()}
        venv_dir = base / "venv"
        venv.EnvBuilder(with_pip=True, system_site_packages=False).create(venv_dir)
        python = venv_dir / "bin" / "python"
        execute("clean offline install", [str(python), "-m", "pip", "install", "--no-index", "--no-deps", "--no-cache-dir", str(wheels[0])])
        probe = execute("isolated installed import and resources", [str(python), "-I", "-c", '''
import json,sys,importlib.metadata
from pathlib import Path
from importlib.resources import files
import email_corpus_forge
from email_corpus_forge.contracts import CONTENT_SCHEMA,REVIEW_SCHEMA,RUBRIC,LABELS,VERSION
from email_corpus_forge.providers import PHRASES
root=files('email_corpus_forge').joinpath('data')
load=lambda name:json.loads(root.joinpath(name).read_text())
assert load('content.schema.json')==CONTENT_SCHEMA
assert load('review.schema.json')==REVIEW_SCHEMA
assert load('taxonomy.json')=={'version':VERSION,'labels':list(LABELS),'rubric':RUBRIC}
assert load('fixture-phrases.json')['phrases']==PHRASES
assert load('fixture-phrases.json')['kind']=='software_fixture_not_corpus'
assert Path(email_corpus_forge.__file__).is_relative_to(Path(sys.prefix))
print(json.dumps({'python':sys.version.split()[0],'version':importlib.metadata.version('email-corpus-forge'),'resources_verified':4,'import_from_venv':True}))
'''])
        evidence["installed_probe"] = json.loads(probe.stdout)
        console = venv_dir / "bin" / "email-corpus-forge"
        for stage in ("plan", "run", "status", "export"):
            command = [str(console), stage, "--run", str(work / "run")]
            if stage == "export":
                command += ["--out", str(work / "export")]
            execute("installed console " + stage, command)
        report = json.loads((work / "export" / "report.json").read_text())
        evidence["fixture_counts"] = report["counts"]
        evidence["fixture_budget"] = report["budget"]
        tests = execute("installed isolated test suite", [str(python), "-I", "-m", "unittest", "discover", "-s", str(base / "tests"), "-v"])
        evidence["test_output"] = tests.stderr.strip()
        execute("installed dependency consistency", [str(python), "-m", "pip", "check"])
    args.out.write_text(json.dumps(evidence, indent=2) + "\n")
    print(f"Saved {args.out}; temporary environment removed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
