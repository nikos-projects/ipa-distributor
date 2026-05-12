#!/usr/bin/env python3
"""
fetch_ipa.py
Downloads the latest KSign .ipa from the IPA_URL env var (set by check_updates.py).
Falls back to scraping GitHub releases if URL is missing.
"""

import os
import sys
import re
import requests

IPA_REPO    = os.environ.get("IPA_REPO",   "nyasami/ksign")
GH_TOKEN    = os.environ.get("GH_TOKEN",   "")
IPA_URL     = os.environ.get("IPA_URL",    "")
IPA_VERSION = os.environ.get("IPA_VERSION","unknown")
BUILD_DIR   = "/tmp/build"

API = "https://api.github.com"

def gh_headers():
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if GH_TOKEN:
        h["Authorization"] = f"Bearer {GH_TOKEN}"
    return h

def resolve_ipa_url():
    """Try multiple strategies to find the IPA download URL."""
    # Strategy 1: use env var from check_updates.py
    if IPA_URL and IPA_URL.endswith(".ipa"):
        return IPA_URL, IPA_VERSION

    print("IPA_URL not set or invalid — probing releases...")

    # Strategy 2: latest release assets
    r = requests.get(f"{API}/repos/{IPA_REPO}/releases/latest", headers=gh_headers(), timeout=30)
    if r.ok:
        rel = r.json()
        ver = rel.get("tag_name", "unknown")
        for asset in rel.get("assets", []):
            if asset["name"].endswith(".ipa"):
                return asset["browser_download_url"], ver
        # Check release body for URLs
        for url in re.findall(r'https?://\S+\.ipa', rel.get("body", "")):
            return url, ver

    # Strategy 3: all releases
    r = requests.get(f"{API}/repos/{IPA_REPO}/releases", headers=gh_headers(), timeout=30)
    if r.ok:
        for rel in r.json():
            ver = rel.get("tag_name", "unknown")
            for asset in rel.get("assets", []):
                if asset["name"].endswith(".ipa"):
                    return asset["browser_download_url"], ver

    # Strategy 4: check tags for attached files
    r = requests.get(f"{API}/repos/{IPA_REPO}/tags", headers=gh_headers(), timeout=30)
    if r.ok:
        for tag in r.json()[:5]:
            tag_name = tag["name"]
            # Sometimes IPAs are committed directly — check repo contents
            for branch in ["main", "master", "release"]:
                url = f"{API}/repos/{IPA_REPO}/contents/?ref={branch}"
                cr = requests.get(url, headers=gh_headers(), timeout=15)
                if cr.ok:
                    for item in cr.json():
                        if item.get("name", "").endswith(".ipa"):
                            return item["download_url"], tag_name

    sys.exit(f"[ERROR] Could not locate .ipa for {IPA_REPO}. "
             "Set IPA_URL manually or check the repo structure.")

def download_ipa(url, dest):
    print(f"Downloading IPA from:\n  {url}")
    headers = gh_headers()
    # GitHub asset redirects need Accept: application/octet-stream
    headers["Accept"] = "application/octet-stream"

    with requests.get(url, headers=headers, stream=True,
                      allow_redirects=True, timeout=300) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        downloaded = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded / total * 100
                    print(f"\r  {pct:.1f}%  ({downloaded:,} / {total:,} bytes)", end="")
    print(f"\n✅ Downloaded {downloaded:,} bytes → {dest}")
    return dest

def main():
    os.makedirs(BUILD_DIR, exist_ok=True)

    url, version = resolve_ipa_url()
    print(f"IPA version : {version}")
    print(f"IPA URL     : {url}")

    dest = os.path.join(BUILD_DIR, "ksign_original.ipa")
    download_ipa(url, dest)

    # Persist version for downstream scripts
    with open(os.path.join(BUILD_DIR, "ipa_version.txt"), "w") as f:
        f.write(version)

    # Basic sanity check — IPA is a ZIP
    import zipfile
    if not zipfile.is_zipfile(dest):
        sys.exit(f"[ERROR] Downloaded file is not a valid IPA/ZIP: {dest}")
    print("✅ IPA integrity check passed (valid ZIP).")

if __name__ == "__main__":
    main()
