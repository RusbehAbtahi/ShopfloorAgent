# ShopfloorAgent

ShopfloorAgent is a manufacturing AI prototype built around three clear layers:

- **Client** — our Python/LangGraph ProductionAgent or another MCP-compatible client
- **MCP Server** — a deterministic tool layer exposing manufacturing capabilities
- **MES Simulation** — the production-system source of truth for runtime state, incidents, repairs, and production history

The MCP layer is intentionally independent from the conversational client, allowing the same manufacturing capabilities to be reused by different MCP-compatible applications.

> **LLMs interpret language. Deterministic Python and the MES own production truth, validation, and calculations.**

### Diagram colors

- **Blue** — Client / AI layer
- **Orange** — MCP boundary
- **Green** — MES / production truth
- Infrastructure remains neutral to keep the diagrams readable.

---

## 1. Core idea

```mermaid
flowchart LR
    CLIENT["Client"]
    MCP["MCP Server"]
    MES["MES Simulation"]

    CLIENT --> MCP --> MES

    classDef client fill:#dbeafe,stroke:#2563eb,color:#111827,stroke-width:1.5px;
    classDef mcp fill:#ffedd5,stroke:#ea580c,color:#111827,stroke-width:1.5px;
    classDef mes fill:#dcfce7,stroke:#16a34a,color:#111827,stroke-width:1.5px;

    class CLIENT client;
    class MCP mcp;
    class MES mes;
```

---

## 2. Expanded architecture

```mermaid
flowchart LR

    subgraph CLIENTS["Clients"]
        PA["ProductionAgent<br/>Python + LangGraph"]
        EXT["Other MCP-Compatible Client<br/>ChatGPT / Claude / others*"]
    end

    subgraph MCP_LAYER["MCP Layer"]
        MCP["MCP Server<br/>7 Deterministic Tools"]
    end

    subgraph MES_LAYER["MES Simulation"]
        MES["4 Production Lines<br/>3 Stations per Line"]
        DB[("SQLite + Runtime Data<br/>Incidents + History")]
        MES --> DB
    end

    PA -->|"MCP<br/>tools/list + tools/call"| MCP
    EXT -->|"MCP"| MCP

    MCP -->|"Manufacturing operations"| MES
    MCP -->|"Deterministic reads"| DB

    classDef client fill:#dbeafe,stroke:#2563eb,color:#111827,stroke-width:1.5px;
    classDef mcp fill:#ffedd5,stroke:#ea580c,color:#111827,stroke-width:1.5px;
    classDef mes fill:#dcfce7,stroke:#16a34a,color:#111827,stroke-width:1.5px;

    class PA,EXT client;
    class MCP mcp;
    class MES,DB mes;
```

\* External clients are examples where MCP connectivity is supported and configured.

---

## 3. Manufacturing simulation

The MES is not only a database behind an AI application. It provides a deterministic manufacturing environment that can be investigated through MCP.

- **4 parallel production lines**
- **3 stations per line**
- deterministic production cycles and simulated timestamps
- **5 reproducible fault scenarios**
- open incidents, repairs, repair comments, and historical incident data
- persistent SQLite production and incident history
- diagnostic incident data retained in the MES backend
- deterministic troubleshooting knowledge

The MES remains the authoritative production system. The LLM does not simulate machine state or manufacture production facts.

---

## 4. ProductionAgent

Our ProductionAgent is one possible MCP client.

It uses Streamlit, Python, LangGraph, and LLM-based language interpretation while keeping tool execution and validation deterministic.

```mermaid
flowchart LR
    UI["User / Streamlit"]
    REQUEST["Request"]
    SELECT["Selector"]
    RESOLVE["Argument Resolver"]
    EXEC["MCP Execution"]
    POST["Post Processing"]
    RESPONSE["Response"]

    UI --> REQUEST
    REQUEST --> SELECT
    SELECT --> RESOLVE
    RESOLVE --> EXEC
    EXEC --> POST
    POST --> RESPONSE

    classDef client fill:#dbeafe,stroke:#2563eb,color:#111827,stroke-width:1.5px;

    class UI,REQUEST,SELECT,RESOLVE,EXEC,POST,RESPONSE client;
```

The LangGraph workflow is intentionally small:

```text
REQUEST
  → SELECTOR
  → ARGUMENT_RESOLVER
  → EXECUTION
  → POST_PROCESSING
  → RESPONSE
```

The LLM helps interpret natural-language requests.

Deterministic Python remains responsible for:

- executable tool contracts
- validation
- defaults
- production-data lookups
- production-impact calculations
- MCP execution

---

## 5. MCP tools

The MCP server exposes seven focused manufacturing capabilities:

- `get_status`
- `get_production_statistics`
- `list_prior_incidents`
- `get_incident_details`
- `get_resolution_instructions`
- `get_repair_experience`
- `calculate_production_impact`

The tools expose structured deterministic results through a real **Streamable HTTP MCP server**.

MCP is therefore both an execution boundary and a reusable interface between the production system and AI clients.

---

## 6. Local and AWS deployment

The same architecture can run locally or with MES + MCP deployed remotely on AWS.

```mermaid
flowchart LR

    subgraph CLIENTS["Client Options"]
        PA["ProductionAgent<br/>Python + LangGraph"]
        PUBLIC["Other MCP-Compatible Client*"]
    end

    subgraph AWS["AWS"]
        DNS["Route 53"]
        NGINX["Nginx + HTTPS"]
        EC2["Amazon EC2"]

        MCP["MCP Container"]
        MES["MES Container"]
        DATA[("Persistent MES Data")]

        DNS --> NGINX
        NGINX --> MCP

        EC2 --> MCP
        EC2 --> MES

        MCP -->|"Read"| DATA
        MES -->|"Read / Write"| DATA
    end

    PA -->|"HTTPS /mcp"| DNS
    PUBLIC -->|"HTTPS /mcp"| DNS

    classDef client fill:#dbeafe,stroke:#2563eb,color:#111827,stroke-width:1.5px;
    classDef mcp fill:#ffedd5,stroke:#ea580c,color:#111827,stroke-width:1.5px;
    classDef mes fill:#dcfce7,stroke:#16a34a,color:#111827,stroke-width:1.5px;

    class PA,PUBLIC client;
    class MCP mcp;
    class MES,DATA mes;
```

\* Where MCP connectivity is supported and configured by the client.

For the AWS deployment, the **ProductionAgent remains client-side**, while MES and MCP run remotely and are accessed through HTTPS.

---

## 7. CI/CD

The project also includes a deployment path from source code to the AWS runtime.

```mermaid
flowchart LR

    GH["GitHub"]
    ACTIONS["GitHub Actions"]
    ECR["Amazon ECR"]
    EC2["Amazon EC2"]

    MCP["MCP Container"]
    MES["MES Container"]

    GH --> ACTIONS
    ACTIONS -->|"Build + Push"| ECR
    ECR -->|"Pull Image"| EC2

    EC2 --> MCP
    EC2 --> MES

    classDef mcp fill:#ffedd5,stroke:#ea580c,color:#111827,stroke-width:1.5px;
    classDef mes fill:#dcfce7,stroke:#16a34a,color:#111827,stroke-width:1.5px;

    class MCP mcp;
    class MES mes;
```

The deployed runtime includes:

- Docker
- Amazon ECR
- Amazon EC2
- GitHub Actions
- persistent MES storage
- Nginx
- HTTPS/TLS
- Route 53
- systemd startup

---

## 8. What was implemented

The project combines:

- deterministic manufacturing simulation
- persistent production and incident history
- deterministic fault and repair scenarios
- seven MCP manufacturing tools
- real Streamable HTTP MCP communication
- Python + LangGraph agent orchestration
- LLM-based natural-language interpretation
- deterministic argument validation
- structured conversational context
- local development environment
- Docker containerization
- AWS deployment
- HTTPS public MCP endpoint
- GitHub Actions CI/CD

The latest verified automated test checkpoint is:

```text
75 passed, 25 subtests passed
```

---

## Design principles

**MES owns production truth.**

**MCP exposes deterministic capabilities.**

**LLMs interpret language rather than manufacturing reality.**

**Executable arguments are validated before tool execution.**

**The conversational client can be replaced without redesigning the MES.**

**Local and cloud deployments preserve the same logical MCP boundary.**

---

## In one sentence

**ShopfloorAgent demonstrates how deterministic manufacturing systems can expose production knowledge and operations to modern AI applications through a reusable MCP interface while keeping production truth outside the language model.**
