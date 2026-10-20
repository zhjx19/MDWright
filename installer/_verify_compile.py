# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pre-verify UninstallMDEditor.cs compiles (the same compile install.cmd
will run on the user machine at install time). Writes _setup_out/_uninstall_compile_test.exe."""
import os
import subprocess

root = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                    "Microsoft.NET", "Framework64")
vers = sorted((d for d in os.listdir(root) if d.startswith("v4")), reverse=True)
comp = os.path.join(root, vers[0], "cs" + "c.exe")
out = os.path.join("_setup_out", "_uninstall_compile_test.exe")
if os.path.exists(out):
    os.remove(out)
args = [comp, "/nologo", "/target:winexe", "/platform:anycpu", "/out:" + out,
        "/win32icon:uninstall-md.ico",
        "/r:System.Windows.Forms.dll", "/r:System.Drawing.dll",
        "UninstallMDEditor.cs"]
r = subprocess.run(args, capture_output=True, timeout=120)
print("rc =", r.returncode)
if r.stdout:
    print(r.stdout.decode("mbcs", "replace"))
if r.stderr:
    print(r.stderr.decode("mbcs", "replace"))
print("exe:", os.path.exists(out), os.path.getsize(out) if os.path.exists(out) else 0)
