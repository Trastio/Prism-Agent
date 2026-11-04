# -*- coding: utf-8 -*-
"""云端部署用的 SSH 小工具（仅依赖 paramiko）

用法：
    set PRISM_SSH_PASS=xxx && python deploy/remote.py exec "uname -a"
    python deploy/remote.py put deploy\\prism-images.tar /tmp/prism-images.tar
    python deploy/remote.py get /tmp/a.log logs\\a.log

环境变量：
    PRISM_SSH_HOST  默认 203.0.113.10
    PRISM_SSH_USER  默认 root
    PRISM_SSH_PASS  必填
"""
import os
import sys

import paramiko

HOST = os.environ.get("PRISM_SSH_HOST", "203.0.113.10")
USER = os.environ.get("PRISM_SSH_USER", "root")
PASS = os.environ.get("PRISM_SSH_PASS", "")


def _client():
    if not PASS:
        raise SystemExit("缺少 PRISM_SSH_PASS 环境变量")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASS, timeout=20, banner_timeout=20)
    return c


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    action = sys.argv[1]
    cli = _client()
    if action == "exec":
        cmd = sys.argv[2]
        stdin, stdout, stderr = cli.exec_command(cmd, timeout=600)
        out = stdout.read().decode("utf-8", "ignore")
        err = stderr.read().decode("utf-8", "ignore")
        if out:
            print(out)
        if err:
            print("[stderr]", err, file=sys.stderr)
        code = stdout.channel.recv_exit_status()
        cli.close()
        return code
    if action in ("put", "get"):
        sftp = cli.open_sftp()
        local, remote = sys.argv[2], sys.argv[3]
        if action == "put":
            sftp.put(local, remote)
        else:
            sftp.get(remote, local)
        sftp.close()
        cli.close()
        print(f"{action} ok: {local} <-> {remote}")
        return 0
    print("未知动作")
    return 1


if __name__ == "__main__":
    sys.exit(main())
