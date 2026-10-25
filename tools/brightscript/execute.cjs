// Return interpreter values directly: its FormatJson does not escape strings.
// The interpreter's test mode preserves ParseJson's invalid return without
// emitting a host console error for an expected malformed server response.
process.env.NODE_ENV = 'test';
const brs = require('@rokucommunity/brs');
const { ValueKind, RoArray, RoAssociativeArray } = brs.types;

// Roku ParseJson defaults to case-sensitive AAs and accepts the optional "i"
// flag. The development interpreter otherwise drops one of Plex's guid/Guid
// fields. Keep this documented runtime difference inside the test bridge.
// https://developer.roku.com/dev/docs/global-utility-functions#parsejson
const jsonLibrary = require('@rokucommunity/brs/lib/stdlib/Json');
function parsedJsonValue(value, caseInsensitive) {
    if (Array.isArray(value)) return new RoArray(value.map(child => parsedJsonValue(child, caseInsensitive)));
    if (value !== null && typeof value === 'object') {
        const result = new RoAssociativeArray([]);
        result.modeCaseSensitive = !caseInsensitive;
        for (const [key, child] of Object.entries(value)) {
            result.set(new brs.types.BrsString(key), parsedJsonValue(child, caseInsensitive), true);
        }
        return result;
    }
    return brs.types.brsValueOf(value);
}
jsonLibrary.ParseJson.signatures[0] = {
    signature: {
        returns: ValueKind.Dynamic,
        args: [new brs.types.StdlibArgument('jsonString', ValueKind.String),
               new brs.types.StdlibArgument('flags', ValueKind.String, new brs.types.BrsString(''))],
    },
    impl: (_, jsonString, flags) => {
        try {
            return parsedJsonValue(JSON.parse(jsonString.getValue()), flags.getValue().includes('i'));
        } catch {
            return brs.types.BrsInvalid.Instance;
        }
    },
};

function toNative(value) {
    if (value.kind === ValueKind.Invalid) return null;
    if (value instanceof RoArray) return value.getElements().map(toNative);
    if (value instanceof RoAssociativeArray) {
        return Object.fromEntries(value.getElements().map(key => [key.toString(), toNative(value.get(key, value.modeCaseSensitive))]));
    }
    if (value.kind === ValueKind.Object && brs.types.isUnboxable(value)) return toNative(value.unbox());
    if (value.kind === ValueKind.Int64) return value.getValue().toNumber();
    if ([ValueKind.String, ValueKind.Boolean, ValueKind.Int32, ValueKind.Float, ValueKind.Double].includes(value.kind)) {
        return value.getValue();
    }
    throw new Error('Function result is not a JSON value');
}

// Dedicated inherited pipes keep requests out of stdout and process arguments.
if (process.env.SILO_HTTP_WRITE_FD && process.env.SILO_HTTP_READ_FD) {
    const fs = require('fs');
    const writeFd = Number(process.env.SILO_HTTP_WRITE_FD);
    const readFd = Number(process.env.SILO_HTTP_READ_FD);
    const limit = 3 * 1024 * 1024;
    let closed = false;
    require('@rokucommunity/brs/lib/stdlib').HostHttpRequest = new brs.types.Callable('HostHttpRequest', {
        signature: {returns: ValueKind.Dynamic, args: [
            new brs.types.StdlibArgument('request', ValueKind.Object),
            new brs.types.StdlibArgument('timeoutMs', ValueKind.Int32),
        ]},
        impl: (_, request, timeoutMs) => {
            if (closed) return parsedJsonValue({statusCode: 0, body: ''}, false);
            try {
                const frame = Buffer.from(JSON.stringify({request: toNative(request), timeoutMs: toNative(timeoutMs)}) + '\n');
                if (frame.length > limit) throw new Error();
                let offset = 0;
                while (offset < frame.length) offset += fs.writeSync(writeFd, frame, offset);
                const bytes = [];
                const byte = Buffer.alloc(1);
                while (true) {
                    if (fs.readSync(readFd, byte, 0, 1, null) !== 1) throw new Error();
                    if (byte[0] === 10) break;
                    bytes.push(byte[0]);
                    if (bytes.length > limit) throw new Error();
                }
                const response = JSON.parse(Buffer.from(bytes).toString('utf8'));
                if (!Number.isInteger(response.statusCode) || response.statusCode < 0 || response.statusCode > 599 || typeof response.body !== 'string') throw new Error();
                return parsedJsonValue(response, false);
            } catch {
                closed = true;
                return parsedJsonValue({statusCode: 0, body: ''}, false);
            }
        },
    });
}

async function main() {
    let stdout = '';
    let stderr = '';
    const [root, ...files] = process.argv.slice(2);
    const result = await brs.execute(files, {
        root,
        stdout: { write: text => { stdout += text; } },
        stderr: { write: text => { stderr += text; } },
    });
    const lines = stdout.trimEnd().split(/\r?\n/);
    // The standalone interpreter lacks SceneGraph's built-in Task component.
    // Ignore only that known warning; every other diagnostic remains fatal.
    const diagnostics = stderr.split(/\r?\n/).filter(line => line &&
        line !== "Warning: XML component 'ApiTask' extends unknown component 'Task'. Ignoring extension.");
    if (diagnostics.length || lines.pop() !== 'SILO_BRS_TEST_COMPLETE') {
        throw new Error(diagnostics.join('\n') || 'BrightScript test did not run to completion');
    }
    process.stdout.write(JSON.stringify({ result: toNative(result[0]), stdout: lines.join('\n') }));
}

main().catch(error => {
    process.stderr.write((process.env.SILO_HTTP_WRITE_FD ? 'Host HTTP execution failed' : String(error)) + '\n');
    process.exitCode = 1;
});
