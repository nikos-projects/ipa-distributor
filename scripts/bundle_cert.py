#!/usr/bin/env python3
"""
bundle_cert.py

Bundles the signing certificate (.p12 + .mobileprovision + password.txt)
into the KSign IPA so that when a user opens the IPA with KSign, the
certificate is automatically pre-imported.

KSign cert injection method:
  KSign reads imported certificates from a known path inside its container:
    <AppBundle>/Documents/Certificates/<cert_name>/
  
  By injecting these files into the IPA at:
    Payload/<AppName>.app/Documents/Certificates/<cert_folder>/
  
  KSign will detect and load them on first launch without any user action.
  This mirrors how KSign exports cert bundles: a folder containing
  cert.p12, cert.mobileprovision, and password.txt.

  Additionally, we create a KSign-compatible "import bundle":
    Payload/<AppName>.app/import.ksign  (a JSON manifest pointing to certs)
  which triggers KSign's deep-link import flow automatically.
"""

import os
import sys
import json
import shutil
import zipfile
import tempfile
import glob

BUILD_DIR = "/tmp/build"
CERTS_DIR = os.path.join(BUILD_DIR, "certs")

INPUT_IPA  = os.path.join(BUILD_DIR, "ksign_original.ipa")
OUTPUT_IPA = os.path.join(BUILD_DIR, "ksign_bundled.ipa")

def find_app_bundle(extract_dir):
    """Find the .app folder inside Payload/."""
    payload = os.path.join(extract_dir, "Payload")
    if not os.path.isdir(payload):
        sys.exit("[ERROR] No Payload/ directory found in IPA.")
    apps = [d for d in os.listdir(payload) if d.endswith(".app")]
    if not apps:
        sys.exit("[ERROR] No .app bundle found in Payload/.")
    return os.path.join(payload, apps[0]), apps[0].replace(".app", "")

def find_cert_files():
    """Locate p12, mobileprovision, and password from /tmp/build/."""
    p12_path = open(os.path.join(BUILD_DIR, "p12_path.txt")).read().strip()
    mp_path  = open(os.path.join(BUILD_DIR, "mp_path.txt")).read().strip()
    password = open(os.path.join(BUILD_DIR, "cert_password.txt")).read().strip()

    if not os.path.exists(p12_path):
        sys.exit(f"[ERROR] .p12 not found at {p12_path}")
    if not os.path.exists(mp_path):
        sys.exit(f"[ERROR] .mobileprovision not found at {mp_path}")

    return p12_path, mp_path, password

def read_mobileprovision_name(mp_path):
    """Extract the profile name from a .mobileprovision using grep on the plist XML."""
    import subprocess, re
    try:
        raw = open(mp_path, "rb").read().decode("utf-8", errors="ignore")
        # The plist inside is XML — find Name key
        m = re.search(r'<key>Name</key>\s*<string>([^<]+)</string>', raw)
        if m:
            return m.group(1)
    except Exception:
        pass
    return "Certificate"

def create_ksign_import_manifest(cert_folder_name, p12_name, mp_name, has_password):
    """
    Create a .ksign import manifest — KSign's internal JSON format.
    This mirrors what KSign generates when you export a certificate.
    """
    manifest = {
        "version": 1,
        "type": "certificate_bundle",
        "name": cert_folder_name,
        "files": {
            "p12": p12_name,
            "mobileprovision": mp_name,
        },
        "hasPassword": has_password,
        "autoImport": True
    }
    return json.dumps(manifest, indent=2)

def inject_certs_into_ipa(input_ipa, output_ipa, p12_path, mp_path, password):
    print(f"Input IPA  : {input_ipa}")
    print(f"Output IPA : {output_ipa}")

    with tempfile.TemporaryDirectory() as tmpdir:
        # Extract IPA
        print("Extracting IPA...")
        with zipfile.ZipFile(input_ipa, "r") as zf:
            zf.extractall(tmpdir)

        app_path, app_name = find_app_bundle(tmpdir)
        print(f"App bundle : {app_name}.app")

        # Normalize cert file names for KSign compatibility
        p12_name = "cert.p12"
        mp_name  = "cert.mobileprovision"
        cert_folder_name = read_mobileprovision_name(mp_path)
        # Sanitize folder name
        cert_folder_name = "".join(c for c in cert_folder_name if c.isalnum() or c in "._- ")[:40]
        if not cert_folder_name:
            cert_folder_name = "BundledCert"

        # ── Injection point 1: Documents/Certificates/ ───────────────────────
        # KSign stores certs here and scans on startup
        cert_dest_dir = os.path.join(app_path, "Documents", "Certificates", cert_folder_name)
        os.makedirs(cert_dest_dir, exist_ok=True)

        shutil.copy2(p12_path, os.path.join(cert_dest_dir, p12_name))
        shutil.copy2(mp_path,  os.path.join(cert_dest_dir, mp_name))

        if password:
            with open(os.path.join(cert_dest_dir, "password.txt"), "w") as f:
                f.write(password)
            print(f"  ✓ password.txt injected")

        print(f"  ✓ Certs injected → Documents/Certificates/{cert_folder_name}/")

        # ── Injection point 2: import.ksign manifest ──────────────────────────
        # Some KSign versions check for this file on launch and trigger import
        manifest_json = create_ksign_import_manifest(
            cert_folder_name, p12_name, mp_name, bool(password)
        )
        manifest_path = os.path.join(app_path, "import.ksign")
        with open(manifest_path, "w") as f:
            f.write(manifest_json)
        print(f"  ✓ import.ksign manifest written")

        # ── Injection point 3: Library/Application Support/ ──────────────────
        # Alternative path some KSign forks use
        lib_cert_dir = os.path.join(app_path, "Library", "Application Support",
                                    "KSign", "Certificates", cert_folder_name)
        os.makedirs(lib_cert_dir, exist_ok=True)
        shutil.copy2(p12_path, os.path.join(lib_cert_dir, p12_name))
        shutil.copy2(mp_path,  os.path.join(lib_cert_dir, mp_name))
        if password:
            with open(os.path.join(lib_cert_dir, "password.txt"), "w") as f:
                f.write(password)
        print(f"  ✓ Certs also injected → Library/Application Support/KSign/Certificates/")

        # ── Repack IPA ────────────────────────────────────────────────────────
        print("Repacking IPA...")
        with zipfile.ZipFile(output_ipa, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6) as zout:
            for root, dirs, files in os.walk(tmpdir):
                for fname in files:
                    fpath = os.path.join(root, fname)
                    arcname = os.path.relpath(fpath, tmpdir)
                    zout.write(fpath, arcname)

    size = os.path.getsize(output_ipa)
    print(f"\n✅ Bundled IPA ready: {output_ipa} ({size:,} bytes)")

def main():
    p12_path, mp_path, password = find_cert_files()

    print(f"P12  : {p12_path}")
    print(f"MP   : {mp_path}")
    print(f"Pass : {'[set]' if password else '[empty]'}")

    inject_certs_into_ipa(INPUT_IPA, OUTPUT_IPA, p12_path, mp_path, password)

if __name__ == "__main__":
    main()
