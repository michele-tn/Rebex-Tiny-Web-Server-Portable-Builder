# Rebex Tiny Web Server Portable Builder

![Tiny Web Server](https://www.rebex.net/Content/images/TinyWebServer.png)
Portable automation for building a ready-to-run Rebex Tiny Web Server folder with HTTP, HTTPS, and a generated TLS certificate.

The builder downloads the official Rebex Tiny Web Server ZIP package, creates a Rebex-compatible PFX certificate with a generated password, updates `RebexTinyWebServer.exe.config`, and writes helper scripts for administrator startup and client Root CA installation.

## What It Builds

- Rebex Tiny Web Server package downloaded from the official Rebex website.
- `RebexTinyWebServer.exe.config` configured for:
  - HTTP port `80`
  - HTTPS port `443`
  - `autoStart=true`
  - `serverCertificateFile=server-certificate.pfx`
  - `serverCertificatePassword=<generated password>`
- `server-certificate.pfx` in a PKCS#12 format compatible with Rebex/.NET loaders.
- Root CA installation package for client machines.
- Administrator launcher for binding to ports 80 and 443.

## Repository Layout

```text
.
├── src/
│   └── build_tiny_web_server_portable.py
├── dist/
│   └── build_tiny_web_server_portable.exe
├── scripts/
│   ├── build_compiled.cmd
│   └── build_interpreted.cmd
├── examples/
│   └── wwwroot/
├── CHANGELOG.md
├── LICENSE
├── README.md
├── requirements.txt
└── VERSION
```

## Quick Start: Compiled Builder

Run this from the repository root:

```bat
scripts\build_compiled.cmd
```

This uses:

```text
dist\build_tiny_web_server_portable.exe
```

and creates:

```text
RebexTinyWebServer_Portable_Production
```

## Quick Start: Python Source

Install dependencies:

```bat
py -3 -m pip install -r requirements.txt
```

Run the builder:

```bat
py -3 src\build_tiny_web_server_portable.py --output-dir RebexTinyWebServer_Portable_Production --force --import-root-ca
```

## Production Startup

After the build finishes, open the generated production folder and run:

```bat
AVVIA_TINY_WEB_SERVER_ADMIN.cmd
```

Administrator privileges are required because Windows normally requires elevation for applications binding to ports `80` and `443`.

## Client Trust Setup

To avoid browser/client TLS errors such as `CertificateUnknown`, install the generated Root CA on each client machine.

In the generated production folder, copy this folder to each client:

```text
pacchetto_client_root_ca
```

Then run as administrator:

```bat
ESEGUI_COME_AMMINISTRATORE.cmd
```

## Useful Options

```bat
dist\build_tiny_web_server_portable.exe --help
```

Common options:

```bat
dist\build_tiny_web_server_portable.exe ^
  --output-dir RebexTinyWebServer_Portable_Production ^
  --common-name tinywebserver.local ^
  --dns PC01,pc01.grissinbon.local,localhost ^
  --ip 169.254.83.107,127.0.0.1 ^
  --force ^
  --import-root-ca
```

## Security Notes

Do not commit or publish generated production secrets:

- `server-certificate.pfx`
- `*.password.txt`
- `*.key.pem`
- `*.key.encrypted.pem`
- generated Root CA private keys
- generated production folders

The `.gitignore` in this repository excludes these files by default.

## Rebex Notice

This project does not vendor the Rebex Tiny Web Server binary in source form. The builder downloads the official ZIP package from Rebex at build time.

Rebex Tiny Web Server is provided by Rebex. Review the official Rebex terms and license before redistribution or production use.

Official page: <https://www.rebex.net/tiny-web-server/>

## Limitations

Rebex Tiny Web Server is a small Windows GUI web server. It is useful for local networks, testing, demos, and controlled deployments, but it is not a replacement for a hardened internet-facing production web server.
