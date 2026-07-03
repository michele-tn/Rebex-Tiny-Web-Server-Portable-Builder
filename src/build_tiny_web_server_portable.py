#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Builds a portable Rebex Tiny Web Server production folder.

The generated package contains:
- Rebex Tiny Web Server downloaded from the official Rebex page;
- HTTP/HTTPS configuration for ports 80 and 443;
- a Rebex-compatible PKCS#12/PFX certificate with password;
- Root CA client installation scripts;
- administrator launchers for binding privileged ports on Windows.
"""

from __future__ import annotations

import argparse
import ctypes
import html
import ipaddress
import os
import re
import secrets
import shutil
import string
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.dom import minidom

SCRIPT_VERSION = "2026-07-03-rebex-tiny-web-server-portable-v1"
REBEX_DOWNLOAD_PAGE = "https://www.rebex.net/tiny-web-server/"
REBEX_DIRECT_URL_FALLBACK = (
    "https://www.rebex.net/getfile/612afd113df34002b407c58441ba5c49/"
    "RebexTinyWebServer-Binaries-Latest.zip/direct"
)
DEFAULT_OUTPUT_DIR = Path.cwd() / "RebexTinyWebServer_Portable_Production"
DEFAULT_COMMON_NAME = "tinywebserver.local"
DEFAULT_DNS_NAMES = ["PC01", "pc01", "pc01.grissinbon.local", "tinywebserver.local", "localhost"]
DEFAULT_IP_ADDRESSES = ["169.254.83.107", "127.0.0.1", "::1"]
ROOT_VALID_DAYS = 3650
SERVER_VALID_DAYS = 825


def ensure_cryptography() -> None:
    """Installs cryptography when the script is run in interpreted mode."""
    try:
        import cryptography  # noqa: F401

        return
    except ImportError:
        print("[INFO] Modulo 'cryptography' non trovato. Installazione in corso...")

    subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
    subprocess.check_call([sys.executable, "-m", "pip", "install", "cryptography"])


ensure_cryptography()

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import PrivateFormat, pkcs12
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


@dataclass(frozen=True)
class CertificateFiles:
    """Paths for generated certificate artifacts."""

    root_cert: Path
    root_key: Path
    root_password: Path
    server_cert: Path
    server_fullchain: Path
    server_key: Path
    server_key_encrypted: Path
    server_pfx: Path
    password: Path
    client_dir: Path
    client_root_cert: Path
    client_ps1: Path
    client_cmd: Path


@dataclass(frozen=True)
class BuildConfig:
    """User-selected build configuration."""

    output_dir: Path
    common_name: str
    dns_names: list[str]
    ip_addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address]
    password: str
    http_port: str
    https_port: str
    download_url: str | None
    force: bool
    import_root_ca: bool


def log(message: str) -> None:
    """Prints a timestamped status line."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")


def is_windows() -> bool:
    """Returns True on Windows."""
    return os.name == "nt"


def is_admin() -> bool:
    """Returns True when the process is elevated on Windows."""
    if not is_windows():
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def generate_password(length: int = 24) -> str:
    """Generates a password that is strong and easy to paste in Rebex config."""
    alphabet = string.ascii_letters + string.digits + "-_@#%+="
    return "".join(secrets.choice(alphabet) for _ in range(length))


def split_values(values: list[str]) -> list[str]:
    """Parses repeated and comma-separated CLI values."""
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        for item in value.split(","):
            normalized = item.strip()
            key = normalized.lower()
            if normalized and key not in seen:
                seen.add(key)
                result.append(normalized)
    return result


def parse_ip_addresses(values: list[str]) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Converts strings to IP address objects."""
    return [ipaddress.ip_address(value) for value in values]


def resolve_download_url(explicit_url: str | None) -> str:
    """Finds the current Rebex Tiny Web Server ZIP URL from the official page."""
    if explicit_url:
        return explicit_url

    log(f"Leggo pagina ufficiale Rebex: {REBEX_DOWNLOAD_PAGE}")
    try:
        with urllib.request.urlopen(REBEX_DOWNLOAD_PAGE, timeout=30) as response:
            page = response.read().decode("utf-8", errors="replace")
        match = re.search(
            r'href="([^"]*RebexTinyWebServer-Binaries-Latest\.zip(?:/direct)?)"',
            page,
            re.IGNORECASE,
        )
        if match:
            url = urllib.request.urljoin(REBEX_DOWNLOAD_PAGE, html.unescape(match.group(1)))
            return url if url.endswith("/direct") else url.rstrip("/") + "/direct"
    except Exception as exc:
        log(f"[WARN] Non riesco a risolvere il link dalla pagina ufficiale: {exc}")

    log("[WARN] Uso URL diretto fallback noto.")
    return REBEX_DIRECT_URL_FALLBACK


def download_zip(url: str, destination: Path) -> None:
    """Downloads the Rebex ZIP package."""
    log(f"Download Rebex Tiny Web Server: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=120) as response:
        destination.write_bytes(response.read())
    if destination.stat().st_size < 100_000:
        raise RuntimeError(f"Download troppo piccolo o non valido: {destination}")


def prepare_output_dir(output_dir: Path, force: bool) -> None:
    """Creates or replaces the output directory."""
    if output_dir.exists():
        if not force:
            raise FileExistsError(f"La cartella esiste gia. Usa --force: {output_dir}")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)


def extract_rebex_package(zip_path: Path, output_dir: Path) -> None:
    """Extracts the official Rebex package into the production folder."""
    log("Estraggo pacchetto Rebex...")
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(output_dir)
    exe = output_dir / "RebexTinyWebServer.exe"
    config = output_dir / "RebexTinyWebServer.exe.config"
    if not exe.exists() or not config.exists():
        raise FileNotFoundError("Il pacchetto Rebex non contiene RebexTinyWebServer.exe e .config.")


def certificate_files(output_dir: Path, common_name: str) -> CertificateFiles:
    """Builds all certificate paths for the portable folder."""
    client_dir = output_dir / "pacchetto_client_root_ca"
    return CertificateFiles(
        root_cert=output_dir / "TinyWebServer_Local_Root_CA.crt.pem",
        root_key=output_dir / "TinyWebServer_Local_Root_CA.key.encrypted.pem",
        root_password=output_dir / "TinyWebServer_Local_Root_CA.password.txt",
        server_cert=output_dir / f"{common_name}.crt.pem",
        server_fullchain=output_dir / f"{common_name}.fullchain.pem",
        server_key=output_dir / f"{common_name}.key.pem",
        server_key_encrypted=output_dir / f"{common_name}.key.encrypted.pem",
        server_pfx=output_dir / "server-certificate.pfx",
        password=output_dir / "server-certificate.password.txt",
        client_dir=client_dir,
        client_root_cert=client_dir / "TinyWebServer_Local_Root_CA.crt.pem",
        client_ps1=client_dir / "installa_root_ca_tiny_client.ps1",
        client_cmd=client_dir / "ESEGUI_COME_AMMINISTRATORE.cmd",
    )


def build_root_ca(common_name: str) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    """Creates a local Root CA."""
    now = datetime.now(timezone.utc)
    key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "IT"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Tiny Web Server Local CA"),
            x509.NameAttribute(NameOID.COMMON_NAME, f"{common_name} Local Root CA"),
        ]
    )
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=ROOT_VALID_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    return key, certificate


def build_server_certificate(
    config: BuildConfig,
    root_key: rsa.RSAPrivateKey,
    root_cert: x509.Certificate,
) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    """Creates the server certificate signed by the local Root CA."""
    now = datetime.now(timezone.utc)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "IT"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Tiny Web Server"),
            x509.NameAttribute(NameOID.COMMON_NAME, config.common_name),
        ]
    )
    san_entries: list[x509.GeneralName] = [x509.DNSName(name) for name in config.dns_names]
    san_entries.extend(x509.IPAddress(address) for address in config.ip_addresses)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(root_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=SERVER_VALID_DAYS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(root_key.public_key()), critical=False)
        .sign(root_key, hashes.SHA256())
    )
    return key, certificate


def write_certificates(config: BuildConfig, files: CertificateFiles) -> None:
    """Writes PEM and Rebex-compatible PFX artifacts."""
    log("Genero Root CA, certificato server e PFX compatibile Rebex...")
    root_key, root_cert = build_root_ca(config.common_name)
    server_key, server_cert = build_server_certificate(config, root_key, root_cert)
    password_bytes = config.password.encode("utf-8")
    root_cert_pem = root_cert.public_bytes(serialization.Encoding.PEM)
    server_cert_pem = server_cert.public_bytes(serialization.Encoding.PEM)

    pfx_encryption = (
        PrivateFormat.PKCS12.encryption_builder()
        .kdf_rounds(50000)
        .key_cert_algorithm(pkcs12.PBES.PBESv1SHA1And3KeyTripleDESCBC)
        .hmac_hash(hashes.SHA1())
        .build(password_bytes)
    )
    pfx_bytes = pkcs12.serialize_key_and_certificates(
        name=b"Rebex Tiny Web Server TLS",
        key=server_key,
        cert=server_cert,
        cas=[root_cert],
        encryption_algorithm=pfx_encryption,
    )

    files.root_cert.write_bytes(root_cert_pem)
    files.root_key.write_bytes(
        root_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.BestAvailableEncryption(password_bytes),
        )
    )
    files.root_password.write_text(config.password + "\n", encoding="utf-8")
    files.server_cert.write_bytes(server_cert_pem)
    files.server_fullchain.write_bytes(server_cert_pem + root_cert_pem)
    files.server_key.write_bytes(
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    files.server_key_encrypted.write_bytes(
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.BestAvailableEncryption(password_bytes),
        )
    )
    files.server_pfx.write_bytes(pfx_bytes)
    validate_pfx(files.server_pfx, config.password)
    files.password.write_text(config.password + "\n", encoding="utf-8")


def validate_pfx(pfx_path: Path, password: str) -> None:
    """Validates that the generated PFX can be opened with its password."""
    key, certificate, _additional = pkcs12.load_key_and_certificates(
        pfx_path.read_bytes(),
        password.encode("utf-8"),
    )
    if key is None or certificate is None:
        raise RuntimeError(f"PFX non valido o privo di chiave privata: {pfx_path}")


def configure_rebex(config: BuildConfig, files: CertificateFiles) -> None:
    """Updates RebexTinyWebServer.exe.config for portable production use."""
    log("Configuro RebexTinyWebServer.exe.config...")
    config_path = config.output_dir / "RebexTinyWebServer.exe.config"
    document = minidom.parse(str(config_path))
    app_settings = document.getElementsByTagName("appSettings")[0]
    values = {
        "httpPort": config.http_port,
        "httpsPort": config.https_port,
        "webRootDir": "./wwwroot",
        "defaultFile": "index.html",
        "serverCertificateFile": files.server_pfx.name,
        "serverCertificatePassword": config.password,
        "tlsVersions": "TLS12,TLS13",
        "legacyMode": "false",
        "autoStart": "true",
        "minimizeOnStart": "false",
        "minimizeToTray": "false",
        "decodeUri": "true",
        "logLevel": "Info",
    }
    existing = {
        node.getAttribute("key"): node
        for node in app_settings.getElementsByTagName("add")
        if node.hasAttribute("key")
    }
    for key, value in values.items():
        node = existing.get(key)
        if node is None:
            node = document.createElement("add")
            node.setAttribute("key", key)
            app_settings.appendChild(node)
        node.setAttribute("value", value)

    config_path.write_text(document.toprettyxml(indent="  ", encoding=None), encoding="utf-8")


def write_client_package(files: CertificateFiles) -> None:
    """Creates Root CA installation helpers for clients."""
    files.client_dir.mkdir(parents=True, exist_ok=True)
    files.client_root_cert.write_bytes(files.root_cert.read_bytes())
    files.client_ps1.write_text(
        """$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$CertPath = Join-Path $ScriptDir "TinyWebServer_Local_Root_CA.crt.pem"

if (-not (Test-Path $CertPath)) {
    throw "Certificato Root CA non trovato: $CertPath"
}

$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($isAdmin) {
    certutil.exe -addstore -f Root $CertPath
} else {
    certutil.exe -user -addstore -f Root $CertPath
}

Write-Host ""
Write-Host "Root CA Tiny Web Server installata. Chiudere e riaprire browser/client, poi riprovare HTTPS."
pause
""",
        encoding="utf-8",
    )
    files.client_cmd.write_text(
        """@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installa_root_ca_tiny_client.ps1"
endlocal
""",
        encoding="utf-8",
    )


def write_launchers(output_dir: Path) -> None:
    """Creates launchers for admin execution and direct execution."""
    (output_dir / "AVVIA_TINY_WEB_SERVER_ADMIN.cmd").write_text(
        """@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~dp0RebexTinyWebServer.exe' -WorkingDirectory '%~dp0' -Verb RunAs"
endlocal
""",
        encoding="utf-8",
    )
    (output_dir / "AVVIA_TINY_WEB_SERVER_NORMALE.cmd").write_text(
        """@echo off
setlocal
cd /d "%~dp0"
start "" "%~dp0RebexTinyWebServer.exe"
endlocal
""",
        encoding="utf-8",
    )


def write_default_webroot(output_dir: Path) -> None:
    """Ensures the portable package has a basic first page."""
    webroot = output_dir / "wwwroot"
    webroot.mkdir(parents=True, exist_ok=True)
    index = webroot / "index.html"
    if not index.exists():
        index.write_text(
            """<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <title>Rebex Tiny Web Server</title>
</head>
<body>
  <h1>Rebex Tiny Web Server portabile attivo</h1>
  <p>HTTP porta 80 e HTTPS porta 443 sono configurati.</p>
</body>
</html>
""",
            encoding="utf-8",
        )


def import_root_ca_if_requested(config: BuildConfig, files: CertificateFiles) -> None:
    """Imports the generated Root CA on the build machine when requested."""
    if not config.import_root_ca:
        return
    if not is_windows():
        log("[WARN] Import Root CA saltato: sistema non Windows.")
        return
    args = ["certutil.exe", "-addstore", "-f", "Root", str(files.root_cert)]
    if not is_admin():
        args.insert(1, "-user")
        log("[WARN] Sessione non elevata: importo nello store Root utente.")
    else:
        log("Importo Root CA nello store Root computer locale.")
    completed = subprocess.run(args, text=True, capture_output=True, check=False)
    if completed.stdout.strip():
        log(completed.stdout.strip())
    if completed.stderr.strip():
        log(completed.stderr.strip())
    if completed.returncode != 0:
        raise RuntimeError(f"certutil fallito con exit code {completed.returncode}")


def verify_with_certutil(config: BuildConfig, files: CertificateFiles) -> None:
    """Uses Windows certutil to verify PFX/password compatibility where available."""
    if not is_windows():
        return
    log("Verifico PFX/password con certutil...")
    completed = subprocess.run(
        ["certutil.exe", "-f", "-p", config.password, "-dump", str(files.server_pfx)],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("certutil non riesce ad aprire il PFX con la password generata.")


def write_readme(config: BuildConfig, files: CertificateFiles, download_url: str) -> None:
    """Writes distribution instructions."""
    urls = [f"https://{name}/" for name in config.dns_names]
    urls.extend(f"https://{address}/" for address in config.ip_addresses)
    (config.output_dir / "ISTRUZIONI_PRODUZIONE_PORTABILE.txt").write_text(
        f"""Pacchetto produzione portabile Rebex Tiny Web Server
Generato il: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
Builder: {SCRIPT_VERSION}
Download Rebex usato: {download_url}

Avvio server:
1. Aprire questa cartella sul PC di produzione.
2. Eseguire come amministratore:
   AVVIA_TINY_WEB_SERVER_ADMIN.cmd
3. Il file RebexTinyWebServer.exe.config e gia configurato con:
   httpPort=80
   httpsPort=443
   serverCertificateFile={files.server_pfx.name}
   serverCertificatePassword={config.password}
   autoStart=true

Certificato server:
- PFX:      {files.server_pfx.name}
- Password: {files.password.name}

Client:
- Copiare sui client solo la cartella pacchetto_client_root_ca.
- Eseguire ESEGUI_COME_AMMINISTRATORE.cmd per installare la Root CA attendibile.
- Non distribuire PFX, file .key.pem o password a client non amministrati.

URL di prova:
{chr(10).join("- " + url for url in urls)}

Nota:
- Le porte 80 e 443 richiedono privilegi amministrativi o una prenotazione URL/porta.
- Se una porta e gia occupata da IIS, Apache, Nginx o altro software, fermare quel servizio o cambiare porta nel config.
""",
        encoding="utf-8",
    )


def build_portable_package(config: BuildConfig) -> None:
    """Runs the full build."""
    prepare_output_dir(config.output_dir, config.force)
    files = certificate_files(config.output_dir, config.common_name)
    download_url = resolve_download_url(config.download_url)
    with tempfile.TemporaryDirectory(prefix="rebex_tiny_web_") as tmp:
        zip_path = Path(tmp) / "RebexTinyWebServer-Binaries-Latest.zip"
        download_zip(download_url, zip_path)
        shutil.copy2(zip_path, config.output_dir / zip_path.name)
        extract_rebex_package(zip_path, config.output_dir)
    write_default_webroot(config.output_dir)
    write_certificates(config, files)
    configure_rebex(config, files)
    write_client_package(files)
    write_launchers(config.output_dir)
    import_root_ca_if_requested(config, files)
    verify_with_certutil(config, files)
    write_readme(config, files, download_url)
    log(f"[OK] Cartella produzione pronta: {config.output_dir}")


def parse_args() -> argparse.Namespace:
    """Parses CLI arguments."""
    parser = argparse.ArgumentParser(description="Genera pacchetto portabile Rebex Tiny Web Server.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--common-name", default=DEFAULT_COMMON_NAME)
    parser.add_argument("--dns", action="append", default=[], help="DNS SAN, ripetibile o separato da virgola.")
    parser.add_argument("--ip", action="append", default=[], help="IP SAN, ripetibile o separato da virgola.")
    parser.add_argument("--password", default=None, help="Password PFX. Se omessa viene generata.")
    parser.add_argument("--http-port", default="80")
    parser.add_argument("--https-port", default="443")
    parser.add_argument("--download-url", default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--import-root-ca", action="store_true")
    return parser.parse_args()


def main() -> int:
    """Entrypoint."""
    args = parse_args()
    dns_names = split_values([args.common_name, *DEFAULT_DNS_NAMES, *args.dns])
    ip_addresses = parse_ip_addresses(split_values([*DEFAULT_IP_ADDRESSES, *args.ip]))
    config = BuildConfig(
        output_dir=args.output_dir.resolve(),
        common_name=args.common_name.strip(),
        dns_names=dns_names,
        ip_addresses=ip_addresses,
        password=args.password or generate_password(),
        http_port=str(args.http_port),
        https_port=str(args.https_port),
        download_url=args.download_url,
        force=args.force,
        import_root_ca=args.import_root_ca,
    )
    build_portable_package(config)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[ERRORE] {exc}")
        raise SystemExit(1)
