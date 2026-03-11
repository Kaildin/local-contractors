import os, sys, subprocess, threading, queue

def stream_subprocess(cmd, cwd=None, env=None, input_data=None):
    """Run a subprocess and yield its stdout lines in real-time."""
    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE if input_data else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )
    if input_data:
        try:
            process.stdin.write(input_data)
            process.stdin.flush()
            process.stdin.close()
        except Exception:
            pass

    q = queue.Queue()

    def reader_thread():
        for line in process.stdout:
            q.put(line)
        process.stdout.close()

    t = threading.Thread(target=reader_thread, daemon=True)
    t.start()

    while True:
        try:
            line = q.get(timeout=0.1)
            yield line
        except queue.Empty:
            if process.poll() is not None:
                break

    while True:
        try:
            line = q.get_nowait()
            yield line
        except queue.Empty:
            break

    returncode = process.wait()
    if returncode != 0:
        yield f"\n[process exited with code {returncode}]\n"
