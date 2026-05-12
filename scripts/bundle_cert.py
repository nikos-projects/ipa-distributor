#!/usr/bin/env python3
"""
bundle_cert.py

For EACH certificate bundle in /tmp/build/certs_manifest.json:
  - Injects the cert into a fresh copy of ksign_original.ipa
  - Outputs /tmp/build/bundled/<folder_name>/ksign_bundled.ipa

KSign cert injection method (unchanged from single-cert version):
  KSign reads imported certificates from:
    <AppBundle>/Documents/Certificates/<cert_name>/
  Injecting into the IPA at:
    Payload/<AppName>.app/Documents/Certificates/<cert_folder>/
  triggers automatic pre-import on first launch.
"""

import os
import sys
import json
import shutil
import zipfile
import tempfile

BUILD_DIR  = "/tmp/build"
INPUT_IPA  = os.path.join(BUILD_DIR, "ksign_original.ipa")
BUNDLE_DIR = os.path.join(BUILD_DIR, "bundled")   # one sub-dir per cert

def find_app_bundle(extract_dir):
    """Find the .app folder inside Payload/."""
    payload = os.path.join(extract_dir, "Payload")
    if not os.path.isdir(payload):
        sys.exit("[ERROR] No Payload/ directory found in IPA.")
    apps = [d for d in os.listdir(payload) if d.endswith(".app")]
    if not apps:
        sys.exit("[ERROR] No .app bundle found in Payload/.")
    return os.path.join(payload, apps[0]), apps[0].replace(".app", "")

def read_mobileprovision_name(mp_path):
    """Extract the profile name from a .mobileprovision using regex on the plist XML."""
    import re
    try:
        raw = open(mp_path, "rb").read().decode("utf-8", errors="ignore")
        m = re.search(r'<key>Name</key>\s*<string>([^<]+)</string>', raw)
        if m:
            return m.group(1)
    except Exception:
        pass
    return "Certificate"

def create_ksign_import_manifest(cert_folder_name, p12_name, mp_name, has_password):
    manifest = {
        "version": 1,
        "type": "certificate_bundle",
        "name": cert_folder_name,
        "files": {
            "p12": p12_name,
            "mobileprovision": mp_name,
        },
        "hasPassword": has_password,
        "autoImport": True,
    }
    return json.dumps(manifest, indent=2)

def inject_certs_into_ipa(input_ipa, output_ipa, p12_path, mp_path, password):
    print(f"  Input IPA  : {input_ipa}")
    print(f"  Output IPA : {output_ipa}")

    with tempfile.TemporaryDirectory() as tmpdir:
        # Extract IPA
        with zipfile.ZipFile(input_ipa, "r") as zf:
            zf.extractall(tmpdir)

        app_path, app_name = find_app_bundle(tmpdir)
        print(f"  App bundle : {app_name}.app")

        p12_name = "cert.p12"
        mp_name  = "cert.mobileprovision"
        cert_folder_name = read_mobileprovision_name(mp_path)
        cert_folder_name = "".join(
            c for c in cert_folder_name if c.isalnum() or c in "._- "
        )[:40].strip() or "BundledCert"

        # ── Injection 1: Documents/Certificates/ ────────────────────────────
        cert_dest_dir = os.path.join(app_path, "Documents", "Certificates", cert_folder_name)
        os.makedirs(cert_dest_dir, exist_ok=True)
        shutil.copy2(p12_path, os.path.join(cert_dest_dir, p12_name))
        shutil.copy2(mp_path,  os.path.join(cert_dest_dir, mp_name))
        if password:
            with open(os.path.join(cert_dest_dir, "password.txt"), "w") as f:
                f.write(password)
        print(f"  ✓ Injected → Documents/Certificates/{cert_folder_name}/")

        # ── Injection 2: import.ksign manifest ──────────────────────────────
        manifest_json = create_ksign_import_manifest(
            cert_folder_name, p12_name, mp_name, bool(password)
        )
        with open(os.path.join(app_path, "import.ksign"), "w") as f:
            f.write(manifest_json)
        print(f"  ✓ import.ksign written")

        # ── Injection 3: Library/Application Support/ ────────────────────────
        lib_cert_dir = os.path.join(
            app_path, "Library", "Application Support",
            "KSign", "Certificates", cert_folder_name
        )
        os.makedirs(lib_cert_dir, exist_ok=True)
        shutil.copy2(p12_path, os.path.join(lib_cert_dir, p12_name))
        shutil.copy2(mp_path,  os.path.join(lib_cert_dir, mp_name))
        if password:
            with open(os.path.join(lib_cert_dir, "password.txt"), "w") as f:
                f.write(password)
        print(f"  ✓ Injected → Library/Application Support/KSign/Certificates/")

        # ── Repack ───────────────────────────────────────────────────────────
        os.makedirs(os.path.dirname(output_ipa), exist_ok=True)
        with zipfile.ZipFile(output_ipa, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6) as zout:
            for root, dirs, files in os.walk(tmpdir):
                for fname in files:
                    fpath   = os.path.join(root, fname)
                    arcname = os.path.relpath(fpath, tmpdir)
                    zout.write(fpath, arcname)

    size = os.path.getsize(output_ipa)
    print(f"  ✅ Done: {output_ipa} ({size:,} bytes)")
    return output_ipa

def main():
    manifest_path = os.path.join(BUILD_DIR, "certs_manifest.json")
    if not os.path.exists(manifest_path):
        sys.exit(f"[ERROR] certs_manifest.json not found at {manifest_path}. Run fetch_cert.py first.")

    with open(manifest_path) as f:
        cert_bundles = json.load(f)

    if not cert_bundles:
        sys.exit("[ERROR] certs_manifest.json is empty.")

    if not os.path.exists(INPUT_IPA):
        sys.exit(f"[ERROR] Original IPA not found at {INPUT_IPA}. Run fetch_ipa.py first.")

    os.makedirs(BUNDLE_DIR, exist_ok=True)

    # Track output IPAs for downstream (sign + generate_assets)
    output_manifest = []

    for i, bundle in enumerate(cert_bundles):
        folder   = bundle["folder"]
        p12_path = bundle["p12_path"]
        mp_path  = bundle["mp_path"]
        password = bundle.get("password", "")

        print(f"\n[{i+1}/{len(cert_bundles)}] Bundling cert: {folder}")

        out_dir = os.path.join(BUNDLE_DIR, folder)
        os.makedirs(out_dir, exist_ok=True)
        output_ipa = os.path.join(out_dir, "ksign_bundled.ipa")

        try:
            inject_certs_into_ipa(INPUT_IPA, output_ipa, p12_path, mp_path, password)
            output_manifest.append({
                "folder":      folder,
                "p12_path":    p12_path,
                "mp_path":     mp_path,
                "password":    password,
                "bundled_ipa": output_ipa,
            })
        except Exception as e:
            print(f"  [ERROR] Failed to bundle cert '{folder}': {e}")
            continue

    if not output_manifest:
        sys.exit("[ERROR] No IPAs were successfully bundled.")

    # Write updated manifest for sign step
    out_manifest_path = os.path.join(BUILD_DIR, "bundled_manifest.json")
    with open(out_manifest_path, "w") as f:
        json.dump(output_manifest, f, indent=2)

    print(f"\n✅ {len(output_manifest)} bundled IPA(s) ready.")
    for item in output_manifest:
        print(f"  • {item['folder']} → {item['bundled_ipa']}")

    # Legacy single-cert compat
    first = output_manifest[0]
    with open(os.path.join(BUILD_DIR, "p12_path.txt"),      "w") as f: f.write(first["p12_path"])
    with open(os.path.join(BUILD_DIR, "mp_path.txt"),       "w") as f: f.write(first["mp_path"])
    with open(os.path.join(BUILD_DIR, "cert_password.txt"), "w") as f: f.write(first["password"])

if __name__ == "__main__":
    main()
