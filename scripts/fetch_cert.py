#!/usr/bin/env python3
"""
fetch_cert.py
Downloads the latest certificate bundle (.p12, .mobileprovision, password.txt)
from the NovaCerts GitHub repo into /tmp/build/certs/.
"""

import os
import sys
import base64
import requests

CERT_REPO   = os.environ.get("CERT_REPO",  "NovaDev404/NovaCerts")
CERT_PAT    = os.environ.get("CERT_REPO_PAT", os.environ.get("GH_TOKEN", ""))
CERT_FOLDER = os.environ.get("CERT_FOLDER", "")
BUILD_DIR   = "/tmp/build"
CERTS_DIR   = os.path.join(BUILD_DIR, "certs")

API = "https://api.github.com"

def gh_headers(token):
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h

def list_folder(path):
    url = f"{API}/repos/{CERT_REPO}/contents/{path}"
    r = requests.get(url, headers=gh_headers(CERT_PAT), timeout=30)
    if r.status_code == 401:
        sys.exit("[ERROR] CERT_REPO_PAT is missing or invalid. Add it as a repo secret.")
    r.raise_for_status()
    return r.json()

def download_file(api_url, dest_path):
    """Download via GitHub contents API (handles files up to 100MB)."""
    r = requests.get(api_url, headers=gh_headers(CERT_PAT), timeout=60)
    r.raise_for_status()
    data = r.json()

    if data.get("encoding") == "base64":
        content = base64.b64decode(data["content"].replace("\n", ""))
    else:
        # Fall back to download_url for large files
        dl = requests.get(data["download_url"], headers=gh_headers(CERT_PAT), timeout=120)
        dl.raise_for_status()
        content = dl.content

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with open(dest_path, "wb") as f:
        f.write(content)
    print(f"  ✓ {os.path.basename(dest_path)} ({len(content):,} bytes)")
    return dest_path

def find_file_by_ext(items, ext):
    """Find the first item matching extension (case-insensitive)."""
    return next((i for i in items if i["name"].lower().endswith(ext.lower())), None)

def main():
    os.makedirs(CERTS_DIR, exist_ok=True)
    os.makedirs(BUILD_DIR, exist_ok=True)

    # If no cert folder specified, auto-detect latest
    folder = CERT_FOLDER
    if not folder:
        print(f"No CERT_FOLDER specified — auto-detecting from {CERT_REPO}...")
        root = list_folder("")
        folders = sorted([i for i in root if i["type"] == "dir"],
                         key=lambda x: x["name"], reverse=True)
        if not folders:
            sys.exit("[ERROR] No certificate folders found in cert repo.")
        folder = folders[0]["name"]

    print(f"Fetching cert folder: {folder}")
    items = list_folder(folder)

    # Support nested structure: if there's a sub-folder, dive in
    subfolders = [i for i in items if i["type"] == "dir"]
    if subfolders and not any(i["name"].lower().endswith(".p12") for i in items):
        print(f"  Found sub-folder: {subfolders[0]['name']} — diving in")
        items = list_folder(f"{folder}/{subfolders[0]['name']}")

    files = [i for i in items if i["type"] == "file"]
    print(f"  Files found: {[f['name'] for f in files]}")

    # Required files
    p12_item = find_file_by_ext(files, ".p12")
    mp_item  = find_file_by_ext(files, ".mobileprovision")

    # Password: check password.txt, pass.txt, or any .txt
    pw_item = (
        next((f for f in files if f["name"].lower() in ("password.txt", "pass.txt")), None)
        or find_file_by_ext(files, ".txt")
    )

    if not p12_item:
        sys.exit("[ERROR] No .p12 file found in cert folder.")
    if not mp_item:
        sys.exit("[ERROR] No .mobileprovision file found in cert folder.")

    # Download
    print("\nDownloading cert files:")
    p12_path = download_file(p12_item["url"], os.path.join(CERTS_DIR, p12_item["name"]))
    mp_path  = download_file(mp_item["url"],  os.path.join(CERTS_DIR, mp_item["name"]))

    password = ""
    if pw_item:
        pw_path = download_file(pw_item["url"], os.path.join(CERTS_DIR, pw_item["name"]))
        with open(pw_path, "r", errors="ignore") as f:
            password = f.read().strip()
        print(f"  Password loaded ({len(password)} chars)")
    else:
        print("  [WARN] No password file found — using empty password")

    # Write paths for downstream scripts
    with open(os.path.join(BUILD_DIR, "p12_path.txt"),      "w") as f: f.write(p12_path)
    with open(os.path.join(BUILD_DIR, "mp_path.txt"),       "w") as f: f.write(mp_path)
    with open(os.path.join(BUILD_DIR, "cert_password.txt"), "w") as f: f.write(password)

    print(f"\n✅ Cert files ready in {CERTS_DIR}")

if __name__ == "__main__":
    main()
