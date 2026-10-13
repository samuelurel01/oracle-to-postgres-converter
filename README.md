# Oracle to Postgres Converter

Conversor simples de tabelas Oracle para PostgreSQL usando a estratégia:

1. Lê a estrutura das tabelas no Oracle.
2. Cria schema e tabelas equivalentes no PostgreSQL quando não existem.
3. Executa `SELECT` no Oracle.
4. Executa `INSERT` em lotes no PostgreSQL.

O projeto fornece uma CLI e uma interface web simples para informar conexões e acompanhar o progresso da migração.

## Requisitos

- Python 3.11+
- Acesso ao banco Oracle de origem
- Acesso ao banco PostgreSQL de destino

Instalação local:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Rodando com Docker

Build e execução:

```bash
docker compose up --build
```

Acesse:

```text
http://localhost:8000
```

Observações sobre conexões dentro do container:

- Para bancos em outros servidores, use o host/IP acessível pela máquina.
- Para acessar serviços rodando na máquina host, use `host.docker.internal`.
- O `docker-compose.yml` já inclui `host.docker.internal:host-gateway` para funcionar também no Linux.

Se você conecta no IntelliJ usando um IP, DNS ou hostname real, use esse mesmo endereço na interface. O `host.docker.internal` só é necessário quando o Oracle ou Postgres está rodando localmente na mesma máquina do Docker.

O container instala Oracle Instant Client Basic Light e usa `python-oracledb` em modo thick por padrão. Isso permite conectar em bancos Oracle antigos ou contas que usam password verifier 10G, cenário que gera o erro `DPY-3015` no modo thin.

## Variáveis de ambiente

```bash
export ORACLE_USER="system"
export ORACLE_PASSWORD="oracle"
export ORACLE_DSN="localhost:1521/XEPDB1"
export ORACLE_SCHEMA="HR"

export POSTGRES_DSN="postgresql://postgres:postgres@localhost:5432/app"
export POSTGRES_SCHEMA="public"
```

## Uso

### Interface web

Rodando localmente:

```bash
oracle-to-postgres-web
```

Acesse:

```text
http://localhost:8000
```

Preencha:

- Origem Oracle: usuário, senha, DSN, schema e opcionalmente o diretório config/wallet.
- Destino Postgres: host, porta, banco, usuário, senha e schema.
- Tabelas opcionais, separadas por vírgula.
- Tamanho do lote opcional e opções de recriação/limpeza.

Se o campo de tabelas ficar vazio, todas as tabelas encontradas no schema Oracle informado serão migradas.

Se o tamanho do lote ficar vazio, o sistema usa `1000`. O lote não define quantas linhas serão migradas no total; ele só define quantas linhas são lidas do Oracle e inseridas no Postgres por vez. A migração continua até terminar 100% dos dados das tabelas selecionadas.

#### Datas Oracle fora do intervalo válido

Algumas bases Oracle antigas podem ter valores de data que o Python ou o PostgreSQL não conseguem representar diretamente, por exemplo datas BC/ano negativo. Quando isso acontece, a importação pode falhar com erro como `year -1 is out of range`.

Para manter o tipo correto no destino, o conversor cria colunas Oracle `DATE` e `TIMESTAMP` como tipos temporais no Postgres. Durante a leitura, ele usa `TO_CHAR(...)` apenas para evitar erro do driver em valores fora do intervalo. Antes do `INSERT`, valores temporais válidos são convertidos de volta para `datetime`.

Quando uma data/timestamp é inválida ou tem ano fora de `1..9999`, o conversor usa:

- `NULL`, se a coluna permite nulo.
- `1900-01-01 00:00:00`, se a coluna é `NOT NULL`.

Cada linha saneada é registrada em:

```text
./logs/migration-problems.log
```

O arquivo é texto em formato JSON Lines. Cada linha contém tabela, coluna, motivo, valor original, valor substituto e a linha completa como foi lida da origem Oracle.

#### Textos com byte NUL

O PostgreSQL não aceita `NUL (0x00)` em campos textuais. Se um campo textual Oracle vier com esse caractere, o conversor remove apenas o `NUL` e mantém o restante do texto. A linha também é registrada em `./logs/migration-problems.log` com evento `nul_byte_sanitized`.

#### XML grande e `ORA-19011`

Colunas Oracle `XMLTYPE` são lidas com `XMLSERIALIZE(... AS CLOB)` para evitar o erro `ORA-19011: Character string buffer too small`. Se ainda ocorrer erro durante a leitura de uma tabela, o conversor registra o SQL e a tabela em `./logs/migration-problems.log` com evento `oracle_fetch_error`.

Se uma tabela já tiver sido criada em tentativa anterior com tipo diferente do esperado, execute novamente marcando `Apagar tabelas existentes`, porque `Limpar antes de inserir` remove dados, mas não altera tipos de coluna.

#### Erro `DPY-4027: no configuration directory specified`

Esse erro acontece quando o DSN Oracle foi interpretado como alias TNS, por exemplo `PROD`, `ORCL` ou `MEUBANCO`. Nesse modo o driver precisa localizar um `tnsnames.ora` ou wallet/configuração Oracle Net.

Você pode resolver de duas formas:

1. Usar Easy Connect no campo DSN, sem depender de `tnsnames.ora`:

```text
host:1521/service_name
```

Exemplo:

```text
192.168.0.10:1521/XEPDB1
```

2. Usar alias TNS e informar o diretório que contém `tnsnames.ora`, `sqlnet.ora` e/ou wallet:

```text
DSN: PROD
Diretório config/wallet: /opt/oracle/network/admin
```

No Docker, monte esse diretório como volume no `docker-compose.yml`:

```yaml
services:
  converter:
    volumes:
      - ./oracle-network-admin:/opt/oracle/network/admin:ro
```

Nesse exemplo, coloque os arquivos Oracle em `./oracle-network-admin` no projeto e informe `/opt/oracle/network/admin` na tela.

#### Erro `DPY-6005` com `[Errno 111] Connection refused`

Esse erro significa que o container chegou até o endereço/porta informados, mas não conseguiu abrir conexão TCP com o Oracle. As causas mais comuns são:

- Usar `localhost` no DSN Oracle dentro do container. Dentro do container, `localhost` é o próprio container, não sua máquina.
- Listener Oracle não está ativo na porta informada.
- Porta errada, normalmente diferente de `1521`.
- Service name/SID incorreto.
- Firewall ou regra de rede bloqueando a conexão.
- Oracle aceitando conexão só em `127.0.0.1` e não na interface da máquina.

Se o Oracle está rodando na sua máquina, use no campo DSN:

```text
host.docker.internal:1521/NOME_DO_SERVICE
```

Se o Oracle está em outro servidor, use o IP ou DNS desse servidor:

```text
10.0.0.50:1521/NOME_DO_SERVICE
```

Teste rápido a partir do container:

```bash
docker compose exec converter python - <<'PY'
import socket
host = "host.docker.internal"
port = 1521
socket.create_connection((host, port), timeout=5).close()
print("porta acessivel")
PY
```

Se esse teste falhar com `Connection refused`, o problema ainda está no host/porta/listener antes de chegar em usuário, senha ou schema.

#### Erro `DPY-3015: password verifier type 0x939`

Esse erro ocorre quando o banco/usuário Oracle usa um password verifier antigo, normalmente 10G. O modo thin do `python-oracledb` não suporta esse verifier; o modo thick suporta. Por isso o Dockerfile instala Oracle Instant Client e a aplicação inicializa o driver em modo thick automaticamente.

Depois dessa alteração, reconstrua a imagem:

```bash
docker compose up -d --build
```

### CLI

Migrar todas as tabelas do schema Oracle:

```bash
oracle-to-postgres migrate
```

Migrar tabelas específicas:

```bash
oracle-to-postgres migrate --tables EMPLOYEES,DEPARTMENTS
```

Apagar e recriar tabelas de destino:

```bash
oracle-to-postgres migrate --drop-existing
```

Limpar dados da tabela de destino antes de inserir:

```bash
oracle-to-postgres migrate --truncate
```

Simular DDL sem copiar dados:

```bash
oracle-to-postgres migrate --dry-run
```

Também é possível passar conexões por argumento:

```bash
oracle-to-postgres migrate \
  --oracle-user system \
  --oracle-password oracle \
  --oracle-dsn localhost:1521/XEPDB1 \
  --oracle-schema HR \
  --oracle-config-dir /opt/oracle/network/admin \
  --postgres-dsn postgresql://postgres:postgres@localhost:5432/app \
  --postgres-schema public
```

## Escopo atual

- Tabelas e colunas.
- Chaves primárias.
- Tipos Oracle comuns para tipos PostgreSQL.
- Cópia em lotes com `fetchmany` e `executemany`.

Ainda não cobre automaticamente:

- Foreign keys, indexes secundários e triggers.
- Views, procedures, packages e sequences.
- Transformações complexas de dados.
- Resume/checkpoint em caso de falha no meio de uma tabela.
