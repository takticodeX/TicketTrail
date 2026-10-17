"""End-to-end fixtures: a Git server and a fake Azure DevOps, over HTTPS, offline.

Runs in the backend image (it has git, FastAPI, uvicorn and cryptography):
  - creates a certificate authority and a certificate for the host "fixtures",
    and writes the CA to /certs/ca.pem so the worker can trust it;
  - creates a small Git repository and serves it over dumb HTTP at /git/demo.git;
  - fakes the Azure DevOps endpoints TicketTrail calls, under /acme (project "Web"),
    and lists every comment it received at /__fake__/comments for the test to check.
"""

import datetime as dt
import ipaddress
import os
import subprocess
import tempfile
from itertools import count
from pathlib import Path

import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

CERTS = Path(os.environ.get("CERTS_DIR", "/certs"))
WORK = Path(tempfile.mkdtemp(prefix="fixtures-"))
PROJECT = "Web"
WORK_ITEMS = {1, 2, 3}
EXPECTED_PAT = os.environ.get("FAKE_AZURE_PAT", "e2e-azure-pat-canary")


def make_certificates() -> tuple[Path, Path]:
    now = dt.datetime.now(dt.UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "TicketTrail e2e CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "fixtures")]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=2))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("fixtures"),
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    CERTS.mkdir(parents=True, exist_ok=True)
    (CERTS / "ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    cert_file, key_file = WORK / "server.pem", WORK / "server.key"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_file, key_file


def make_repository() -> Path:
    """demo.git on main: three commits referencing AB#1-3, one without a reference."""
    work, bare = WORK / "demo", WORK / "repos" / "demo.git"
    work.mkdir()

    def git(*args: str, cwd: Path = work) -> None:
        subprocess.run(
            ["git", "-c", "user.name=Ada Lovelace", "-c", "user.email=ada@example.com", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
        )

    git("init", "-q", "-b", "main")
    for message in (
        "Fix login redirect AB#1",
        "chore: bump dependencies",
        "Add billing export AB#2\n\nAlso closes AB#3.",
    ):
        git("commit", "-q", "--allow-empty", "-m", message)
    bare.parent.mkdir()
    git("clone", "-q", "--bare", str(work), str(bare), cwd=WORK)
    git("update-server-info", cwd=bare)  # what the dumb HTTP protocol reads
    return bare.parent


app = FastAPI(title="TicketTrail e2e fixtures")
comments: dict[int, list[dict[str, object]]] = {}
ids = count(5000)


def authorised(request: Request) -> bool:
    import base64

    expected = "Basic " + base64.b64encode(f":{EXPECTED_PAT}".encode()).decode()
    return request.headers.get("authorization") == expected


@app.get(f"/acme/_apis/projects/{PROJECT}")
def project(request: Request) -> JSONResponse:
    if not authorised(request):
        return JSONResponse(status_code=401, content={"message": "unauthorised"})
    return JSONResponse({"id": "web", "name": PROJECT})


@app.get(f"/acme/{PROJECT}/_apis/wit/workitems")
def work_items(request: Request, ids: str) -> JSONResponse:  # noqa: A002
    if not authorised(request):
        return JSONResponse(status_code=401, content={"message": "unauthorised"})
    wanted = [int(i) for i in ids.split(",")]
    return JSONResponse({"value": [{"id": i} if i in WORK_ITEMS else None for i in wanted]})


@app.post(f"/acme/{PROJECT}/_apis/wit/workItems/{{work_item_id}}/comments")
async def add_comment(work_item_id: int, request: Request) -> JSONResponse:
    if not authorised(request):
        return JSONResponse(status_code=401, content={"message": "unauthorised"})
    if work_item_id not in WORK_ITEMS:
        return JSONResponse(status_code=404, content={"message": "not found"})
    body = await request.json()
    comment = {"id": next(ids), "text": body["text"]}
    comments.setdefault(work_item_id, []).append(comment)
    return JSONResponse(comment)


@app.get(f"/acme/{PROJECT}/_apis/wit/workItems/{{work_item_id}}/comments")
def list_comments(work_item_id: int, request: Request) -> JSONResponse:
    if not authorised(request):
        return JSONResponse(status_code=401, content={"message": "unauthorised"})
    return JSONResponse({"comments": comments.get(work_item_id, [])})


@app.get("/__fake__/comments")
def all_comments() -> dict[str, list[dict[str, object]]]:
    """For the end-to-end test to check what was posted."""
    return {str(k): v for k, v in comments.items()}


@app.post("/__fake__/reset")
def reset() -> dict[str, str]:
    """Forget every comment, so each test run starts clean."""
    comments.clear()
    return {"status": "reset"}


@app.get("/__fake__/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    cert_file, key_file = make_certificates()
    app.mount("/git", StaticFiles(directory=make_repository()), name="git")
    uvicorn.run(
        app,
        host="0.0.0.0",  # noqa: S104 (a test container)
        port=8443,
        ssl_certfile=str(cert_file),
        ssl_keyfile=str(key_file),
        log_level="info",
    )
