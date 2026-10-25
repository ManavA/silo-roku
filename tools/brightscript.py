"""Run pure BrightScript policies using a pinned, optional development interpreter.

Install with: npm ci --prefix tools/brightscript --ignore-scripts
The interpreter is not a substitute for Roku UI, transport, or playback tests.
"""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
INTERPRETER = ROOT / "tools" / "brightscript" / "node_modules" / "@rokucommunity" / "brs"
BRIDGE = ROOT / "tools" / "brightscript" / "execute.cjs"
COMPLETE = "SILO_BRS_TEST_COMPLETE"


def interpreter_available() -> bool:
    return INTERPRETER.is_dir() and shutil.which("node") is not None


def _execute(files, body: str, root: Path, result_expression: str = "invalid", host_http=None):
    if not interpreter_available():
        raise RuntimeError("install runtime tests: npm ci --prefix tools/brightscript --ignore-scripts")
    if isinstance(files, (str, Path)):
        files = [files]
    with tempfile.TemporaryDirectory(prefix="silo-brs-test-") as directory:
        script = Path(directory) / "test.brs"
        script.write_text(
            'function Main() as Dynamic\n' + body + '\nprint "' + COMPLETE
            + '"\nreturn ' + result_expression + '\nend function\n',
            encoding="utf-8",
        )
        script.chmod(0o600)
        command = [shutil.which("node"), str(BRIDGE), str(root),
                   *(str(Path(file).resolve()) for file in files), str(script)]
        if host_http is not None:
            from tools.brightscript_http import execute
            result = execute(command, cwd=ROOT,
                             timeout=float(os.environ.get("SILO_BRS_TIMEOUT", "120")),
                             handler=host_http)
        else:
            result = subprocess.run(
                command, cwd=ROOT, capture_output=True, text=True,
                timeout=float(os.environ.get("SILO_BRS_TIMEOUT", "120")),
                check=False,
            )
    # brs lacks these native SceneGraph Task/LabelList implementations. Ignore
    # only their exact XML scan warnings; other diagnostics still fail the run.
    task_warnings = {
        "Warning: XML component 'HomeCacheTask' extends unknown component 'Task'. Ignoring extension.",
        "Warning: XML component 'ApiTask' extends unknown component 'Task'. Ignoring extension.",
        "Warning: XML component 'EpisodeNeighborTask' extends unknown component 'Task'. Ignoring extension.",
        "Warning: XML component 'ArtworkTask' extends unknown component 'Task'. Ignoring extension.",
        "Warning: XML component 'PersonPhotoTask' extends unknown component 'Task'. Ignoring extension.",
        "Warning: XML component 'SiloUIQrTask' extends unknown component 'Task'. Ignoring extension.",
        "Warning: XML component 'SiloUITrickplayTask' extends unknown component 'Task'. Ignoring extension.",
        "Warning: XML component 'SiloCompatTask' extends unknown component 'Task'. Ignoring extension.",
        "Warning: XML component 'SiloStockEngineTask' extends unknown component 'Task'. Ignoring extension.",
    }
    # The production engine scripts are mapped into the archive from the same
    # revision's experiment tree; the host VM scans unpackaged XML at repo root.
    from tools.package import stock_engine_sources
    virtual_missing = set()
    root_path = Path(root).resolve()
    if (root_path / "components/SiloStockEngineTask.xml").is_file():
        try:
            mapped = stock_engine_sources(root_path)
            explicit = {Path(file).resolve() for file in files}
            virtual_missing = {f"brs: can't open file '{root_path / name}': [Errno -2]"
                               for name in mapped if (root_path / name) not in explicit}
        except ValueError:
            pass
    diagnostics = "\n".join(line for line in result.stderr.splitlines()
                            if line not in task_warnings and line not in virtual_missing)
    if result.returncode or diagnostics:
        raise RuntimeError("Host HTTP execution failed" if host_http is not None else
                           "BrightScript execution failed:\n" + diagnostics + result.stdout)
    return json.loads(result.stdout)


def run_brightscript(files, body: str, *, root: Path = ROOT) -> str:
    """Execute actual app functions plus a test body and return only its output."""
    return _execute(files, body, root)["stdout"]


# Pure functions need no SceneGraph components; scanning the project's XML costs
# about two seconds per call, so they run against an empty root.
PURE_ROOT = Path(tempfile.mkdtemp(prefix="silo-brs-pure-"))


def run_function(files, function_name: str, arguments, *, root: Path = PURE_ROOT, host_http=None):
    """Call a pure app function with JSON arguments and decode its JSON result."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", function_name):
        raise ValueError("function_name must be a BrightScript identifier")
    payload = json.dumps(arguments, ensure_ascii=True).replace('"', '""')
    parameters = ", ".join(f"arguments[{index}]" for index in range(len(arguments)))
    body = f'arguments = ParseJson("{payload}")\nresult = {function_name}({parameters})'
    return _execute(files, body, root, "result", host_http=host_http)["result"]
