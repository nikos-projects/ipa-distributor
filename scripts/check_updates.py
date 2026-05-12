#!/usr/bin/env python3
"""
check_updates.py
Compares the latest cert folder in NovaCerts and the latest IPA release
against the last known state. Sets GitHub Actions outputs accordingly.
"""

import os
import sys
import json
import requests

CERT_REPO  = os.environ.get("CERT_REPO",  "NovaDev404/NovaCerts")
IPA_REPO   = os.environ.get("IPA_REPO",   "nyasami/ksign")
GH_TOKEN   = os.environ.get("GH_TOKEN",   "")
CERT_PAT   = os.environ.get("CERT_REPO_PAT", GH_TOKEN)
FORCE      = os.environ.get("FORCE_REBUILD", "false").lower() == "true"
STATE_DIR  = ".state"

API = "https://api.github.com"

def gh_headers(token):
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h

def set_output(name, value):
    """Write to GITHUB_OUTPUT (multi-line safe)."""
    env_file = os.environ.get("GITHUB_OUTPUT", "")
    if env_file:
        with open(env_file, "a") as f:
            f.write(f"{name}={value}\n")
    else:
        print(f"::set-output name={name}::{value}")  # fallback

def read_state(filename):
    path = os.path.join(STATE_DIR, filename)
    if os.path.exists(path):
        return open(path).read().strip()
    return ""

# ── Fetch latest cert folder ──────────────────────────────────────────────────
def get_latest_cert_folder():
    """
    Looks at the root of CERT_REPO for the newest folder (by name or commit date).
    Folders are expected to be named like dates or incrementing IDs.
    """
    url = f"{API}/repos/{CERT_REPO}/contents/"
    r = requests.get(url, headers=gh_headers(CERT_PAT), timeout=30)

    if r.status_code == 404:
        print(f"[WARN] Cert repo {CERT_REPO} not found or private — check CERT_REPO_PAT secret.")
        return None, None

    r.raise_for_status()
    items = r.json()

    folders = [i for i in items if i["type"] == "dir"]
    if not folders:
        print("[WARN] No folders found in cert repo.")
        return None, None

    # Sort by name descending (works for date-named or numeric folders)
    folders.sort(key=lambda x: x["name"], reverse=True)
    latest = folders[0]
    return latest["name"], latest["sha"]

# ── Fetch latest IPA release ──────────────────────────────────────────────────
def get_latest_ipa_release():
    url = f"{API}/repos/{IPA_REPO}/releases/latest"
    r = requests.get(url, headers=gh_headers(GH_TOKEN), timeout=30)

    if r.status_code == 404:
        # Fall back to checking all releases
        url = f"{API}/repos/{IPA_REPO}/releases"
        r = requests.get(url, headers=gh_headers(GH_TOKEN), timeout=30)
        r.raise_for_status()
        releases = r.json()
        if not releases:
            print("[WARN] No releases found in IPA repo.")
            return None, None
        release = releases[0]
    else:
        r.raise_for_status()
        release = r.json()

    version = release.get("tag_name", "unknown")
    assets  = release.get("assets", [])
    ipa_asset = next((a for a in assets if a["name"].endswith(".ipa")), None)

    if not ipa_asset:
        # Check body for direct download links
        print(f"[WARN] No .ipa asset in release {version}. Checking release body...")
        body = release.get("body", "")
        import re
        urls = re.findall(r'https?://\S+\.ipa', body)
        if urls:
            return version, urls[0]
        return version, None

    return version, ipa_asset["browser_download_url"]

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print(f"Checking cert repo : {CERT_REPO}")
    print(f"Checking IPA repo  : {IPA_REPO}")

    cert_folder, cert_sha = get_latest_cert_folder()
    ipa_version, ipa_url  = get_latest_ipa_release()

    print(f"Latest cert folder : {cert_folder} ({cert_sha})")
    print(f"Latest IPA version : {ipa_version}")
    print(f"IPA download URL   : {ipa_url}")

    last_cert    = read_state("last_cert")
    last_version = read_state("last_ipa_version")

    print(f"Cached cert folder : {last_cert}")
    print(f"Cached IPA version : {last_version}")

    cert_changed = cert_folder and cert_folder != last_cert
    ipa_changed  = ipa_version and ipa_version != last_version
    should_build = FORCE or cert_changed or ipa_changed

    print(f"\ncert_changed={cert_changed}, ipa_changed={ipa_changed}, force={FORCE}")
    print(f"should_build={should_build}")

    set_output("should_build", str(should_build).lower())
    set_output("cert_folder",  cert_folder  or "")
    set_output("ipa_url",      ipa_url      or "")
    set_output("ipa_version",  ipa_version  or "unknown")

    if not should_build:
        print("\n✅ Nothing new — skipping build.")
    else:
        print("\n🔨 Changes detected — triggering build.")

if __name__ == "__main__":
    main()
