"""Opt-in offline IPC broker. The callback owns HTTP policy and performs no retries.

No networking is implemented here. Exceptions and protocol failures latch closed;
request data is never included in diagnostic exceptions.
"""
import json
import os
import select
import subprocess
import threading
import time

FRAME_LIMIT = 3 * 1024 * 1024
REQUEST_LIMIT = 16


def execute(command, *, cwd, timeout, handler):
    request_read, request_write = os.pipe()
    response_read, response_write = os.pipe()
    deadline = time.monotonic() + min(timeout, 120)
    failed = threading.Event()
    stop = threading.Event()
    env = dict(os.environ, SILO_HTTP_WRITE_FD=str(request_write),
               SILO_HTTP_READ_FD=str(response_read))
    process = None

    def broker():
        buffer = b''
        count = 0
        try:
            while not stop.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError()
                if not select.select([request_read], [], [], min(remaining, .1))[0]:
                    continue
                chunk = os.read(request_read, 65536)
                if not chunk:
                    return
                buffer += chunk
                if len(buffer) > FRAME_LIMIT:
                    raise ValueError()
                while b'\n' in buffer:
                    frame, buffer = buffer.split(b'\n', 1)
                    count += 1
                    if failed.is_set() or count > REQUEST_LIMIT:
                        raise ValueError()
                    message = json.loads(frame)
                    if set(message) != {'request', 'timeoutMs'} or not isinstance(message['request'], dict):
                        raise ValueError()
                    request_timeout = message['timeoutMs']
                    if type(request_timeout) is not int or not 0 <= request_timeout <= 120000:
                        raise ValueError()
                    completed = threading.Event()
                    response_box = []
                    def invoke(request=message['request'], timeout_ms=request_timeout,
                               box=response_box, done=completed):
                        try:
                            box.append(handler(request, timeout_ms))
                        except Exception:
                            pass
                        finally:
                            done.set()
                    threading.Thread(target=invoke, daemon=True).start()
                    budget = deadline - time.monotonic()
                    if request_timeout:
                        budget = min(budget, request_timeout / 1000)
                    if not completed.wait(max(0, budget)) or not response_box:
                        raise ValueError()
                    response = response_box[0]
                    if (not isinstance(response, dict) or set(response) != {'statusCode', 'body'}
                            or type(response['statusCode']) is not int
                            or not 0 <= response['statusCode'] <= 599
                            or not isinstance(response['body'], str)):
                        raise ValueError()
                    encoded = json.dumps(response, ensure_ascii=True).encode() + b'\n'
                    if len(encoded) > FRAME_LIMIT or time.monotonic() >= deadline:
                        raise ValueError()
                    view = memoryview(encoded)
                    while view:
                        written = os.write(response_write, view)
                        view = view[written:]
        except Exception:
            failed.set()
        finally:
            os.close(request_read)
            os.close(response_write)

    try:
        process = subprocess.Popen(command, cwd=cwd, env=env,
                                   pass_fds=(request_write, response_read),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        os.close(request_write)
        os.close(response_read)
        worker = threading.Thread(target=broker, daemon=True)
        worker.start()
        try:
            stdout, stderr = process.communicate(timeout=max(.01, deadline-time.monotonic()))
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise RuntimeError('Host HTTP bridge deadline exceeded') from None
        if failed.is_set():
            raise RuntimeError('Host HTTP bridge failed closed')
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    finally:
        stop.set()
        if process is None:
            for fd in (request_read, request_write, response_read, response_write):
                os.close(fd)
