from __future__ import annotations

import threading
import uuid
from dataclasses import asdict
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from typing import Any
from urllib.parse import quote

import uvicorn
from fastapi import FastAPI
from fastapi import Form
from fastapi.responses import HTMLResponse
from fastapi.responses import JSONResponse

from .config import MigrationConfig
from .config import OracleConfig
from .config import PostgresConfig
from .migrator import MigrationProgress
from .migrator import Migrator

app = FastAPI(title="Oracle to Postgres Converter")


@dataclass
class MigrationJob:
    id: str
    status: str
    created_at: str
    progress: MigrationProgress
    error: str | None = None


jobs: dict[str, MigrationJob] = {}
jobs_lock = threading.Lock()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return INDEX_HTML


@app.post("/api/migrations")
def start_migration(
    oracle_user: str = Form(...),
    oracle_password: str = Form(...),
    oracle_dsn: str = Form(...),
    oracle_schema: str = Form(...),
    oracle_config_dir: str = Form(""),
    postgres_host: str = Form(...),
    postgres_port: int = Form(5432),
    postgres_database: str = Form(...),
    postgres_user: str = Form(...),
    postgres_password: str = Form(...),
    postgres_schema: str = Form("public"),
    tables: str = Form(""),
    batch_size: int | None = Form(None),
    drop_existing: bool = Form(False),
    truncate: bool = Form(False),
    preserve_identifiers: bool = Form(False),
) -> JSONResponse:
    job_id = str(uuid.uuid4())
    job = MigrationJob(
        id=job_id,
        status="queued",
        created_at=datetime.now(UTC).isoformat(),
        progress=MigrationProgress(
            phase="queued",
            message="Migration queued.",
        ),
    )
    with jobs_lock:
        jobs[job_id] = job

    config = MigrationConfig(
        oracle=OracleConfig(
            user=oracle_user,
            password=oracle_password,
            dsn=oracle_dsn,
            schema=oracle_schema,
            config_dir=oracle_config_dir.strip() or None,
        ),
        postgres=PostgresConfig(
            dsn=build_postgres_dsn(
                host=postgres_host,
                port=postgres_port,
                database=postgres_database,
                user=postgres_user,
                password=postgres_password,
            ),
            schema=postgres_schema or "public",
        ),
        batch_size=batch_size or 1000,
        drop_existing=drop_existing,
        truncate=truncate,
        preserve_identifiers=preserve_identifiers,
    )
    requested_tables = parse_tables(tables)
    thread = threading.Thread(
        target=run_migration,
        args=(job_id, config, requested_tables),
        daemon=True,
    )
    thread.start()

    return JSONResponse({"job_id": job_id})


@app.get("/api/migrations/{job_id}")
def get_migration(job_id: str) -> JSONResponse:
    with jobs_lock:
        job = jobs.get(job_id)

    if job is None:
        return JSONResponse({"error": "Migration job not found."}, status_code=404)

    return JSONResponse(job_to_dict(job))


def run_migration(
    job_id: str,
    config: MigrationConfig,
    requested_tables: list[str] | None,
) -> None:
    def update_progress(progress: MigrationProgress) -> None:
        with jobs_lock:
            job = jobs[job_id]
            job.progress = progress
            if progress.phase != "completed":
                job.status = "running"

    with jobs_lock:
        jobs[job_id].status = "running"
        jobs[job_id].progress = MigrationProgress(
            phase="connecting",
            message="Connecting to source and target databases.",
        )

    try:
        Migrator(config, progress_callback=update_progress).migrate(requested_tables)
        with jobs_lock:
            jobs[job_id].status = "completed"
    except Exception as error:  # noqa: BLE001 - surfaced to the UI.
        with jobs_lock:
            jobs[job_id].status = "failed"
            jobs[job_id].error = str(error)
            jobs[job_id].progress = MigrationProgress(
                phase="failed",
                message=str(error),
                percent=jobs[job_id].progress.percent,
                inserted_rows=jobs[job_id].progress.inserted_rows,
                total_rows=jobs[job_id].progress.total_rows,
            )


def parse_tables(raw_tables: str) -> list[str] | None:
    tables = [table.strip() for table in raw_tables.split(",") if table.strip()]
    return tables or None


def build_postgres_dsn(
    *,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
) -> str:
    encoded_user = quote(user, safe="")
    encoded_password = quote(password, safe="")
    encoded_database = quote(database, safe="")
    return f"postgresql://{encoded_user}:{encoded_password}@{host}:{port}/{encoded_database}"


def job_to_dict(job: MigrationJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "status": job.status,
        "created_at": job.created_at,
        "progress": asdict(job.progress),
        "error": job.error,
    }


def main() -> None:
    uvicorn.run("oracle_to_postgres_converter.web:app", host="0.0.0.0", port=8000)


INDEX_HTML = """
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Oracle to Postgres Converter</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #18202a;
      --muted: #667085;
      --line: #d9dee7;
      --primary: #1769aa;
      --primary-dark: #0f4f82;
      --danger: #b42318;
      --ok: #027a48;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    main {
      max-width: 1120px;
      margin: 0 auto;
      padding: 32px 20px;
    }
    header {
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 24px;
      margin-bottom: 24px;
    }
    h1 {
      margin: 0 0 6px;
      font-size: 30px;
      line-height: 1.1;
    }
    p {
      margin: 0;
      color: var(--muted);
    }
    form {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 18px;
      align-items: start;
    }
    section,
    .progress-panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
    }
    section h2,
    .progress-panel h2 {
      margin: 0 0 14px;
      font-size: 17px;
    }
    .field {
      display: grid;
      gap: 6px;
      margin-bottom: 12px;
    }
    label {
      font-size: 13px;
      font-weight: 650;
      color: #344054;
    }
    input {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px 11px;
      font-size: 14px;
      background: #fff;
      color: var(--text);
    }
    input:focus {
      outline: 2px solid rgba(23, 105, 170, 0.18);
      border-color: var(--primary);
    }
    .full { grid-column: 1 / -1; }
    .options {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }
    .check {
      display: flex;
      align-items: center;
      gap: 9px;
      min-height: 42px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px 10px;
      font-size: 13px;
      font-weight: 600;
      color: #344054;
    }
    .check input {
      width: 16px;
      height: 16px;
      padding: 0;
      margin: 0;
    }
    .actions {
      display: flex;
      justify-content: flex-end;
      gap: 12px;
    }
    button {
      border: 0;
      border-radius: 6px;
      padding: 11px 16px;
      font-weight: 700;
      font-size: 14px;
      color: white;
      background: var(--primary);
      cursor: pointer;
    }
    button:hover { background: var(--primary-dark); }
    button:disabled {
      cursor: not-allowed;
      opacity: 0.55;
    }
    .progress-panel {
      margin-top: 18px;
    }
    .meter {
      width: 100%;
      height: 18px;
      border-radius: 999px;
      overflow: hidden;
      border: 1px solid var(--line);
      background: #eef2f6;
    }
    .meter > div {
      width: 0%;
      height: 100%;
      background: var(--primary);
      transition: width 220ms ease;
    }
    .progress-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-top: 14px;
    }
    .stat {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      min-height: 68px;
    }
    .stat span {
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 6px;
    }
    .stat strong {
      font-size: 18px;
    }
    .status {
      margin-top: 12px;
      min-height: 22px;
      color: var(--muted);
      overflow-wrap: anywhere;
    }
    .status.failed { color: var(--danger); }
    .status.completed { color: var(--ok); }
    @media (max-width: 780px) {
      header { display: block; }
      form,
      .progress-grid,
      .options {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>Oracle to Postgres Converter</h1>
        <p>Informe as conexões, selecione as opções e acompanhe a migração em tempo real.</p>
      </div>
    </header>

    <form id="migration-form">
      <section>
        <h2>Origem Oracle</h2>
        <div class="field">
          <label for="oracle_user">Usuário</label>
          <input id="oracle_user" name="oracle_user" autocomplete="username" required>
        </div>
        <div class="field">
          <label for="oracle_password">Senha</label>
          <input id="oracle_password" name="oracle_password" type="password" autocomplete="current-password" required>
        </div>
        <div class="field">
          <label for="oracle_dsn">DSN</label>
          <input id="oracle_dsn" name="oracle_dsn" placeholder="host.docker.internal:1521/service" required>
        </div>
        <div class="field">
          <label for="oracle_config_dir">Diretório config/wallet</label>
          <input id="oracle_config_dir" name="oracle_config_dir" placeholder="/opt/oracle/network/admin">
        </div>
        <div class="field">
          <label for="oracle_schema">Schema</label>
          <input id="oracle_schema" name="oracle_schema" placeholder="HR" required>
        </div>
      </section>

      <section>
        <h2>Destino Postgres</h2>
        <div class="field">
          <label for="postgres_host">Host</label>
          <input id="postgres_host" name="postgres_host" placeholder="host.docker.internal" required>
        </div>
        <div class="field">
          <label for="postgres_port">Porta</label>
          <input id="postgres_port" name="postgres_port" type="number" min="1" max="65535" value="5432" required>
        </div>
        <div class="field">
          <label for="postgres_database">Banco</label>
          <input id="postgres_database" name="postgres_database" placeholder="app" required>
        </div>
        <div class="field">
          <label for="postgres_user">Usuário</label>
          <input id="postgres_user" name="postgres_user" autocomplete="username" required>
        </div>
        <div class="field">
          <label for="postgres_password">Senha</label>
          <input id="postgres_password" name="postgres_password" type="password" autocomplete="current-password" required>
        </div>
        <div class="field">
          <label for="postgres_schema">Schema</label>
          <input id="postgres_schema" name="postgres_schema" value="public" required>
        </div>
        <div class="field">
          <label for="tables">Tabelas</label>
          <input id="tables" name="tables" placeholder="EMPLOYEES,DEPARTMENTS">
        </div>
        <div class="field">
          <label for="batch_size">Tamanho do lote</label>
          <input id="batch_size" name="batch_size" type="number" min="1" placeholder="1000">
        </div>
      </section>

      <section class="full">
        <h2>Opções</h2>
        <div class="options">
          <label class="check"><input type="checkbox" name="drop_existing"> Apagar tabelas existentes</label>
          <label class="check"><input type="checkbox" name="truncate"> Limpar antes de inserir</label>
          <label class="check"><input type="checkbox" name="preserve_identifiers"> Preservar maiúsculas/minúsculas</label>
        </div>
      </section>

      <div class="actions full">
        <button id="start-button" type="submit">Iniciar migração</button>
      </div>
    </form>

    <section class="progress-panel">
      <h2>Progresso</h2>
      <div class="meter" aria-label="Progresso da migração">
        <div id="meter-fill"></div>
      </div>
      <div class="progress-grid">
        <div class="stat"><span>Status</span><strong id="status">Pronto</strong></div>
        <div class="stat"><span>Percentual</span><strong id="percent">0%</strong></div>
        <div class="stat"><span>Linhas</span><strong id="rows">0 / 0</strong></div>
        <div class="stat"><span>Tabela</span><strong id="table">-</strong></div>
      </div>
      <div id="message" class="status">Aguardando início.</div>
    </section>
  </main>

  <script>
    const form = document.querySelector("#migration-form");
    const startButton = document.querySelector("#start-button");
    const meterFill = document.querySelector("#meter-fill");
    const statusEl = document.querySelector("#status");
    const percentEl = document.querySelector("#percent");
    const rowsEl = document.querySelector("#rows");
    const tableEl = document.querySelector("#table");
    const messageEl = document.querySelector("#message");
    let pollTimer = null;

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      startButton.disabled = true;
      updateMessage("Enviando configuração da migração.", "running");

      const response = await fetch("/api/migrations", {
        method: "POST",
        body: new FormData(form)
      });

      if (!response.ok) {
        updateMessage("Não foi possível iniciar a migração.", "failed");
        startButton.disabled = false;
        return;
      }

      const payload = await response.json();
      pollJob(payload.job_id);
    });

    function pollJob(jobId) {
      if (pollTimer) window.clearInterval(pollTimer);
      pollTimer = window.setInterval(async () => {
        const response = await fetch(`/api/migrations/${jobId}`);
        if (!response.ok) return;

        const job = await response.json();
        renderJob(job);

        if (job.status === "completed" || job.status === "failed") {
          window.clearInterval(pollTimer);
          startButton.disabled = false;
        }
      }, 1000);
    }

    function renderJob(job) {
      const progress = job.progress || {};
      const percent = Number(progress.percent || 0);
      meterFill.style.width = `${percent}%`;
      statusEl.textContent = job.status;
      percentEl.textContent = `${percent.toFixed(2)}%`;
      rowsEl.textContent = `${progress.inserted_rows || 0} / ${progress.total_rows || 0}`;
      tableEl.textContent = progress.current_table || "-";
      updateMessage(job.error || progress.message || "", job.status);
    }

    function updateMessage(message, status) {
      messageEl.textContent = message;
      messageEl.className = `status ${status || ""}`;
    }
  </script>
</body>
</html>
"""
