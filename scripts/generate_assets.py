#!/usr/bin/env python3
"""
generate_assets.py
Generates for EACH signed IPA:
  - manifest-<folder>.plist  (iOS OTA install manifest)
  - ksign_<version>_<folder>_signed.ipa (copied to deploy dir)

Plus a single index.html listing ALL certificates with individual OTA buttons.
Reads /tmp/build/signed_manifest.json produced by the sign step.
"""

import os
import sys
import json
import shutil
import hashlib
from datetime import datetime, timezone

BUILD_DIR  = "/tmp/build"
DEPLOY_DIR = "/tmp/deploy"

REPO       = os.environ.get("GITHUB_REPOSITORY", "owner/repo")
REPO_OWNER = REPO.split("/")[0]
REPO_NAME  = REPO.split("/")[-1]
VERSION    = os.environ.get("IPA_VERSION", "unknown")
BUNDLE_ID  = os.environ.get("BUNDLE_ID",  "com.nyasami.ksign")
APP_NAME   = os.environ.get("APP_NAME",   "KSign")

BASE_URL   = f"https://{REPO_OWNER}.github.io/{REPO_NAME}"

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def sanitize_slug(name):
    """Turn a cert folder name into a URL-safe slug."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)

def generate_plist(ipa_url, display_name, bundle_id, version):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>items</key>
    <array>
        <dict>
            <key>assets</key>
            <array>
                <dict>
                    <key>kind</key>
                    <string>software-package</string>
                    <key>url</key>
                    <string>{ipa_url}</string>
                </dict>
            </array>
            <key>metadata</key>
            <dict>
                <key>bundle-identifier</key>
                <string>{bundle_id}</string>
                <key>bundle-version</key>
                <string>{version}</string>
                <key>kind</key>
                <string>software</string>
                <key>title</key>
                <string>{display_name}</string>
            </dict>
        </dict>
    </array>
</dict>
</plist>"""

def cert_card_html(idx, cert):
    """Render one certificate card for the landing page."""
    folder      = cert["folder"]
    ipa_url     = cert["ipa_url"]
    plist_url   = cert["plist_url"]
    sha         = cert["sha256"]
    size_mb     = cert["size_mb"]
    itms_url    = f"itms-services://?action=download-manifest&url={plist_url}"
    short_sha   = sha[:16]
    # Friendly display name: replace underscores/hyphens with spaces, title-case
    display     = folder.replace("_", " ").replace("-", " ").title()

    return f"""
        <div class="cert-card" style="--card-index:{idx}">
          <div class="cert-header">
            <div class="cert-icon">🔐</div>
            <div class="cert-meta">
              <div class="cert-name">{display}</div>
              <div class="cert-folder-raw">{folder}</div>
            </div>
            <span class="badge">Signed</span>
          </div>

          <div class="cert-details">
            <div class="detail-item">
              <span class="detail-label">Size</span>
              <span class="detail-val">{size_mb:.1f} MB</span>
            </div>
            <div class="detail-item">
              <span class="detail-label">SHA-256</span>
              <span class="detail-val mono">{short_sha}…</span>
            </div>
          </div>

          <div class="cert-actions">
            <a href="{itms_url}" class="install-btn">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
                   stroke="currentColor" stroke-width="2.2"
                   stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z"/>
                <path d="M8 12l4 4 4-4M12 8v8"/>
              </svg>
              Install via OTA
            </a>
            <a href="{ipa_url}" class="direct-btn" title="Download .ipa">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
                   stroke="currentColor" stroke-width="2"
                   stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>
              </svg>
              .ipa
            </a>
          </div>

          <details class="sha-details">
            <summary>Full SHA-256</summary>
            <div class="sha-box">{sha}</div>
          </details>
        </div>"""

def generate_html(certs, version, build_time):
    cert_count  = len(certs)
    cards_html  = "\n".join(cert_card_html(i, c) for i, c in enumerate(certs))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <title>{APP_NAME} — OTA Installer</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Space+Mono:ital,wght@0,400;0,700;1,400&family=Syne:wght@400;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg:        #07070d;
      --surface:   #0e0e18;
      --surface2:  #13131f;
      --border:    #1a1a2e;
      --border2:   #252540;
      --accent:    #6c63ff;
      --accent2:   #b06fff;
      --accent3:   #00e5c0;
      --text:      #dde3f0;
      --muted:     #5a6180;
      --muted2:    #7a85a8;
      --green:     #00e5c0;
      --glow:      rgba(108, 99, 255, 0.22);
      --glow2:     rgba(0, 229, 192, 0.15);
      --r:         14px;
    }}

    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    html {{ scroll-behavior: smooth; }}

    body {{
      background: var(--bg);
      color: var(--text);
      font-family: 'Syne', sans-serif;
      min-height: 100vh;
      overflow-x: hidden;
    }}

    /* ── Noise texture overlay ── */
    body::before {{
      content: '';
      position: fixed;
      inset: 0;
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='300' height='300'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.75' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='300' height='300' filter='url(%23n)' opacity='0.03'/%3E%3C/svg%3E");
      pointer-events: none;
      z-index: 0;
      opacity: 0.6;
    }}

    /* ── Grid ── */
    body::after {{
      content: '';
      position: fixed;
      inset: 0;
      background-image:
        linear-gradient(var(--border) 1px, transparent 1px),
        linear-gradient(90deg, var(--border) 1px, transparent 1px);
      background-size: 48px 48px;
      opacity: 0.25;
      pointer-events: none;
      z-index: 0;
    }}

    /* ── Glow orbs ── */
    .orb {{
      position: fixed;
      border-radius: 50%;
      filter: blur(100px);
      pointer-events: none;
      z-index: 0;
    }}
    .orb-1 {{
      width: 500px; height: 500px;
      background: radial-gradient(circle, rgba(108,99,255,0.12), transparent 70%);
      top: -150px; left: -150px;
    }}
    .orb-2 {{
      width: 400px; height: 400px;
      background: radial-gradient(circle, rgba(0,229,192,0.07), transparent 70%);
      bottom: 10%; right: -100px;
    }}

    /* ── Layout ── */
    .page {{
      position: relative;
      z-index: 1;
      max-width: 980px;
      margin: 0 auto;
      padding: 0 1.25rem 5rem;
    }}

    /* ── Hero ── */
    .hero {{
      padding: 4rem 0 3rem;
      text-align: center;
    }}

    .logo {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 84px; height: 84px;
      background: linear-gradient(135deg, var(--accent), var(--accent2));
      border-radius: 24px;
      font-size: 2.5rem;
      margin-bottom: 1.6rem;
      box-shadow: 0 0 50px var(--glow), 0 0 100px rgba(108,99,255,0.08);
      animation: logoFloat 4s ease-in-out infinite;
    }}

    @keyframes logoFloat {{
      0%, 100% {{ transform: translateY(0); }}
      50%       {{ transform: translateY(-6px); }}
    }}

    .hero h1 {{
      font-size: clamp(2rem, 6vw, 3.2rem);
      font-weight: 800;
      letter-spacing: -0.03em;
      line-height: 1.1;
      background: linear-gradient(135deg, #fff 20%, var(--accent2) 65%, var(--accent3));
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
      margin-bottom: 0.6rem;
    }}

    .hero-sub {{
      color: var(--muted2);
      font-size: 1rem;
      font-weight: 400;
      letter-spacing: 0.01em;
    }}

    /* ── Stats bar ── */
    .stats-bar {{
      display: flex;
      justify-content: center;
      gap: 0.5rem;
      flex-wrap: wrap;
      margin: 2rem 0 3rem;
    }}

    .stat-pill {{
      display: inline-flex;
      align-items: center;
      gap: 0.45rem;
      padding: 0.45rem 1rem;
      background: var(--surface);
      border: 1px solid var(--border2);
      border-radius: 99px;
      font-family: 'Space Mono', monospace;
      font-size: 0.72rem;
      color: var(--muted2);
    }}

    .stat-pill .dot {{
      width: 6px; height: 6px;
      border-radius: 50%;
      background: var(--accent3);
      box-shadow: 0 0 6px var(--accent3);
    }}

    .stat-pill strong {{ color: var(--text); }}

    /* ── Section heading ── */
    .section-head {{
      display: flex;
      align-items: center;
      gap: 0.75rem;
      margin-bottom: 1.25rem;
    }}

    .section-label {{
      font-family: 'Space Mono', monospace;
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.14em;
      color: var(--muted);
    }}

    .section-line {{
      flex: 1;
      height: 1px;
      background: var(--border2);
    }}

    /* ── Cert grid ── */
    .cert-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
      gap: 1rem;
      margin-bottom: 2rem;
    }}

    /* ── Cert card ── */
    .cert-card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--r);
      padding: 1.4rem;
      display: flex;
      flex-direction: column;
      gap: 1rem;
      opacity: 0;
      transform: translateY(16px);
      animation: cardIn 0.4s ease forwards;
      animation-delay: calc(var(--card-index) * 0.07s);
      transition: border-color 0.2s, box-shadow 0.2s;
    }}

    @keyframes cardIn {{
      to {{ opacity: 1; transform: translateY(0); }}
    }}

    .cert-card:hover {{
      border-color: var(--border2);
      box-shadow: 0 0 30px rgba(108,99,255,0.08);
    }}

    .cert-header {{
      display: flex;
      align-items: center;
      gap: 0.8rem;
    }}

    .cert-icon {{
      font-size: 1.6rem;
      flex-shrink: 0;
      width: 42px; height: 42px;
      display: flex;
      align-items: center;
      justify-content: center;
      background: var(--surface2);
      border: 1px solid var(--border2);
      border-radius: 10px;
    }}

    .cert-meta {{ flex: 1; min-width: 0; }}

    .cert-name {{
      font-size: 0.92rem;
      font-weight: 700;
      color: var(--text);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}

    .cert-folder-raw {{
      font-family: 'Space Mono', monospace;
      font-size: 0.62rem;
      color: var(--muted);
      margin-top: 0.15rem;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}

    .badge {{
      flex-shrink: 0;
      display: inline-flex;
      align-items: center;
      gap: 0.3rem;
      font-size: 0.65rem;
      font-family: 'Space Mono', monospace;
      padding: 0.2rem 0.55rem;
      border-radius: 99px;
      background: rgba(0, 229, 192, 0.08);
      color: var(--green);
      border: 1px solid rgba(0, 229, 192, 0.2);
    }}
    .badge::before {{ content: '●'; font-size: 0.5rem; }}

    /* ── Details row ── */
    .cert-details {{
      display: flex;
      gap: 0.5rem;
    }}

    .detail-item {{
      flex: 1;
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.55rem 0.75rem;
    }}

    .detail-label {{
      font-size: 0.62rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      display: block;
      margin-bottom: 0.2rem;
    }}

    .detail-val {{
      font-size: 0.82rem;
      color: var(--text);
      font-weight: 600;
    }}

    .detail-val.mono {{
      font-family: 'Space Mono', monospace;
      font-size: 0.7rem;
      font-weight: 400;
    }}

    /* ── Actions ── */
    .cert-actions {{
      display: flex;
      gap: 0.6rem;
      align-items: stretch;
    }}

    .install-btn {{
      flex: 1;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 0.5rem;
      padding: 0.7rem 0.9rem;
      background: linear-gradient(135deg, var(--accent), var(--accent2));
      color: #fff;
      font-family: 'Syne', sans-serif;
      font-size: 0.88rem;
      font-weight: 700;
      border-radius: 9px;
      text-decoration: none;
      transition: opacity 0.18s, transform 0.15s;
      box-shadow: 0 0 24px rgba(108,99,255,0.3);
    }}

    .install-btn:hover  {{ opacity: 0.88; transform: translateY(-1px); }}
    .install-btn:active {{ transform: translateY(0); opacity: 0.75; }}

    .direct-btn {{
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 0.35rem;
      padding: 0.7rem 0.85rem;
      background: var(--surface2);
      color: var(--muted2);
      font-size: 0.8rem;
      font-family: 'Space Mono', monospace;
      border: 1px solid var(--border2);
      border-radius: 9px;
      text-decoration: none;
      white-space: nowrap;
      transition: color 0.18s, border-color 0.18s;
    }}

    .direct-btn:hover {{ color: var(--text); border-color: var(--accent); }}

    /* ── SHA details ── */
    .sha-details {{
      font-size: 0.72rem;
    }}

    .sha-details summary {{
      cursor: pointer;
      color: var(--muted);
      font-family: 'Space Mono', monospace;
      font-size: 0.65rem;
      user-select: none;
      outline: none;
      list-style: none;
    }}
    .sha-details summary::-webkit-details-marker {{ display: none; }}
    .sha-details summary::before {{ content: '▸ '; }}
    .sha-details[open] summary::before {{ content: '▾ '; }}

    .sha-box {{
      margin-top: 0.5rem;
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 0.5rem 0.7rem;
      font-family: 'Space Mono', monospace;
      font-size: 0.6rem;
      color: var(--muted);
      word-break: break-all;
      line-height: 1.6;
    }}

    /* ── Info / how-to ── */
    .info-card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--r);
      padding: 1.4rem;
      margin-bottom: 1rem;
    }}

    .info-card .card-title {{
      font-family: 'Space Mono', monospace;
      font-size: 0.68rem;
      text-transform: uppercase;
      letter-spacing: 0.13em;
      color: var(--muted);
      margin-bottom: 1rem;
    }}

    .steps {{ list-style: none; }}
    .steps li {{
      display: flex;
      gap: 0.85rem;
      align-items: flex-start;
      padding: 0.6rem 0;
      border-bottom: 1px solid var(--border);
      font-size: 0.86rem;
      color: var(--muted2);
      line-height: 1.5;
    }}
    .steps li:last-child {{ border-bottom: none; }}
    .step-num {{
      flex-shrink: 0;
      width: 22px; height: 22px;
      background: var(--border2);
      border-radius: 6px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-family: 'Space Mono', monospace;
      font-size: 0.68rem;
      color: var(--accent2);
      margin-top: 2px;
    }}

    .warning {{
      background: rgba(255, 180, 0, 0.05);
      border: 1px solid rgba(255, 180, 0, 0.18);
      border-radius: 9px;
      padding: 0.85rem 1rem;
      font-size: 0.82rem;
      color: #fbbf24;
      margin-top: 1rem;
      line-height: 1.5;
    }}

    /* ── Footer ── */
    footer {{
      margin-top: 3rem;
      text-align: center;
      font-family: 'Space Mono', monospace;
      font-size: 0.68rem;
      color: var(--muted);
      line-height: 2;
    }}

    footer a {{ color: var(--accent2); text-decoration: none; }}
    footer a:hover {{ text-decoration: underline; }}

    /* ── Responsive ── */
    @media (max-width: 480px) {{
      .cert-grid {{ grid-template-columns: 1fr; }}
      .hero h1 {{ font-size: 1.8rem; }}
      .stats-bar {{ gap: 0.4rem; }}
    }}
  </style>
</head>
<body>
  <div class="orb orb-1"></div>
  <div class="orb orb-2"></div>

  <div class="page">
    <div class="hero">
      <div class="logo">✍️</div>
      <h1>{APP_NAME} OTA Installer</h1>
      <p class="hero-sub">Certificate-bundled builds · Install directly on iOS</p>
    </div>

    <div class="stats-bar">
      <div class="stat-pill">
        <span class="dot"></span>
        <strong>{cert_count}</strong> certificate{'' if cert_count == 1 else 's'} available
      </div>
      <div class="stat-pill">
        <span class="dot"></span>
        Version <strong>{version}</strong>
      </div>
      <div class="stat-pill">
        <span class="dot"></span>
        Built <strong>{build_time} UTC</strong>
      </div>
    </div>

    <!-- Cert grid -->
    <div class="section-head">
      <span class="section-label">Available Certificates</span>
      <div class="section-line"></div>
    </div>

    <div class="cert-grid">
{cards_html}
    </div>

    <!-- How to install -->
    <div class="section-head">
      <span class="section-label">How to Install</span>
      <div class="section-line"></div>
    </div>

    <div class="info-card">
      <ol class="steps">
        <li><span class="step-num">1</span>Pick a certificate above and tap <strong>Install via OTA</strong> on your iPhone or iPad.</li>
        <li><span class="step-num">2</span>Follow the iOS prompts to install the profile &amp; app.</li>
        <li><span class="step-num">3</span>Open {APP_NAME} — your certificate is pre-loaded automatically.</li>
        <li><span class="step-num">4</span>If prompted, go to <strong>Settings → General → VPN &amp; Device Management</strong> and trust the developer.</li>
      </ol>
      <div class="warning">
        ⚠️ Tap <em>Install via OTA</em> only on an iOS device. Each card installs {APP_NAME} pre-bundled with that specific certificate.
      </div>
    </div>

    <footer>
      Auto-built by <a href="https://github.com/{REPO}">GitHub Actions</a> ·
      {build_time} UTC<br>
      {APP_NAME} by <a href="https://github.com/nyasami/ksign">nyasami</a>
    </footer>
  </div>
</body>
</html>"""

def main():
    os.makedirs(DEPLOY_DIR, exist_ok=True)

    # Load signed manifest produced by the sign step
    signed_manifest_path = os.path.join(BUILD_DIR, "signed_manifest.json")
    if not os.path.exists(signed_manifest_path):
        sys.exit(f"[ERROR] signed_manifest.json not found at {signed_manifest_path}. "
                 "Run the sign step first.")

    with open(signed_manifest_path) as f:
        signed_items = json.load(f)

    if not signed_items:
        sys.exit("[ERROR] signed_manifest.json is empty.")

    # Read version
    ver_file = os.path.join(BUILD_DIR, "ipa_version.txt")
    version  = open(ver_file).read().strip() if os.path.exists(ver_file) else VERSION
    build_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    certs_meta = []

    for item in signed_items:
        folder     = item["folder"]
        signed_ipa = item["signed_ipa"]
        slug       = sanitize_slug(folder)

        if not os.path.exists(signed_ipa):
            print(f"[WARN] Signed IPA missing for '{folder}': {signed_ipa} — skipping.")
            continue

        ipa_size    = os.path.getsize(signed_ipa)
        ipa_size_mb = ipa_size / (1024 * 1024)
        ipa_sha     = sha256(signed_ipa)

        ipa_filename = f"ksign_{version}_{slug}_signed.ipa"
        ipa_deploy   = os.path.join(DEPLOY_DIR, ipa_filename)
        print(f"Copying IPA [{folder}] → {ipa_deploy}")
        shutil.copy2(signed_ipa, ipa_deploy)

        ipa_url   = f"{BASE_URL}/{ipa_filename}"
        plist_name = f"manifest-{slug}.plist"
        plist_url  = f"{BASE_URL}/{plist_name}"

        # Write per-cert plist
        plist_content = generate_plist(ipa_url, APP_NAME, BUNDLE_ID, version)
        plist_path    = os.path.join(DEPLOY_DIR, plist_name)
        with open(plist_path, "w") as f:
            f.write(plist_content)
        print(f"  ✓ {plist_name} written")

        certs_meta.append({
            "folder":    folder,
            "ipa_url":   ipa_url,
            "plist_url": plist_url,
            "sha256":    ipa_sha,
            "size_mb":   ipa_size_mb,
        })

    if not certs_meta:
        sys.exit("[ERROR] No valid signed IPAs to deploy.")

    # Single index.html listing all certs
    html_content = generate_html(certs_meta, version, build_time)
    html_path    = os.path.join(DEPLOY_DIR, "index.html")
    with open(html_path, "w") as f:
        f.write(html_content)
    print(f"✓ index.html written ({len(certs_meta)} cert card(s))")

    # meta.json for programmatic access
    meta = {
        "version":    version,
        "build_time": build_time,
        "bundle_id":  BUNDLE_ID,
        "app_name":   APP_NAME,
        "certs":      certs_meta,
    }
    with open(os.path.join(DEPLOY_DIR, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    print(f"✓ meta.json written")

    print(f"\n✅ Deploy assets ready in {DEPLOY_DIR} ({len(certs_meta)} cert(s))")
    for c in certs_meta:
        print(f"  • {c['folder']}")
        print(f"      IPA   : {c['ipa_url']}")
        print(f"      OTA   : itms-services://?action=download-manifest&url={c['plist_url']}")

if __name__ == "__main__":
    main()
