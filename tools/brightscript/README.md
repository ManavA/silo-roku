# BrightScript runtime tests

This pinned development interpreter executes pure policies and fixture adapters
on the host. It is excluded from Roku packages. Node.js and npm are needed only
for these runtime tests; building the channel ZIP still needs only Python.

```sh
npm ci --prefix tools/brightscript --ignore-scripts
SILO_REQUIRE_BRS=1 python3 -m unittest discover -s tests -v
```

Without the interpreter, the runtime test class reports an explicit skip during
the regular Python checks. CI sets `SILO_REQUIRE_BRS=1` so missing tooling
fails the build.

Tests call the production BrightScript functions through `tools/brightscript.py`:

```python
result = run_function(
    ROOT / "source" / "adapters" / "SiloAdapter.brs",
    "MapSiloCatalog",
    [fixture, "silo-example"],
)
```

The files argument accepts one path or a list. Arguments and results support JSON
values. `run_brightscript(files, body)` runs a test body and captures its output,
including fixture reads through `ReadAsciiFile("pkg:/tests/fixtures/...")`.
Syntax errors, runtime errors, and incomplete execution fail; each subprocess has
a 20 second timeout. Function results are read directly from interpreter values
because this interpreter's `FormatJson` does not correctly escape quoted strings.

The [RokuCommunity interpreter](https://github.com/rokucommunity/brs) has runtime
gaps, including `roUrlTransfer`. These checks establish policy behavior and
fixture handling. Device testing is required for SceneGraph focus, registry,
HTTP/TLS, memory, launch, and playback. Do not add host substitutes for those APIs
and treat their results as Roku evidence.

The wrapper ignores only the named Task components' known XML scan warnings and
the exact `DetailActionList`/`LabelList` warning. This lets pure policy checks run
without emulating the native list. Other diagnostics and process failures remain
errors; physical scrolling and focus still require a Roku.
