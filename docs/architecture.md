# Architecture

## Application architecture

The UI orchestrates the simulation engine, analysis, challenges, and saved-run library. The engine and comparison logic are separate from the Streamlit presentation layer.

```mermaid
flowchart TB
    Browser["Browser"] <-->|"Streamlit session"| UI["app.py + run_library_ui.py<br/>Controls, results, saved runs"]

    subgraph Core["Python application"]
        Config["config.py<br/>Design, workload, illustrative costs"]
        Engine["engine.py / SimPy<br/>Discrete-event simulation"]
        Analysis["analysis.py<br/>Summaries, timelines, findings"]
        Charts["charts.py / Plotly<br/>Architecture, replay, charts"]
        Challenges["challenges.py + predict.py<br/>Hidden checks and scoring"]
        History["history.py<br/>Snapshot storage and comparison"]
        Progress["progress.py<br/>XP, stars, badges"]
    end

    UI --> Config
    Config --> Engine
    UI -->|"Run or experiment"| Engine
    Engine -->|"Request records and tier samples"| Analysis
    Analysis --> Charts
    Charts --> UI
    UI --> Challenges
    Challenges -->|"Run hidden checks"| Engine
    UI <-->|"Save, list, compare, delete"| History
    UI <--> Progress

    subgraph Storage["State and storage"]
        SQLite[("SQLite<br/>.local/runs.sqlite3")]
        Session["Session state<br/>Campaign progress"]
        Optima["data/optima.json<br/>Reference designs"]
    end

    History <--> SQLite
    Progress <--> Session
    Optima --> Challenges
    Optimizer["tools/optimize.py<br/>Offline optimizer"] --> Optima
```

In local mode, simulations run synchronously and expensive results are cached with Streamlit. The multi-user deployment runs experiments in bounded Celery workers, uses Redis for transient jobs/results, and stores account-owned snapshots in PostgreSQL. See the [production architecture and runbook](production.md) for the service diagram and deployment instructions.

## Simulated system architecture

This diagram represents the system **inside the simulator**, rather than the infrastructure hosting the app. CDN, cache, queue, and read replicas are optional.

```mermaid
flowchart LR
    Clients["Clients<br/>Poisson arrivals"] --> Edge{"CDN enabled<br/>and read hit?"}
    Edge -->|"Yes: edge response"| Done["Request complete"]
    Edge -->|"No"| LB["Load balancer"]
    LB --> App["App replica pool"]
    App --> Kind{"Read or write?"}

    Kind -->|"Read"| Cache{"Cache enabled<br/>and hit?"}
    Cache -->|"Hit"| Done
    Cache -->|"Miss or disabled"| ReadDB["Shard read target<br/>Read replica if configured, else primary"]
    ReadDB --> Done

    Kind -->|"Write"| Async{"Async queue enabled?"}
    Async -->|"No"| Primary["Shard primary<br/>Database write"]
    Primary -->|"Synchronous completion"| Done
    Async -->|"Yes"| Queue["Bounded write queue"]
    Queue -->|"Acknowledge after enqueue"| Done
    Queue --> Consumers["Background consumers"]
    Consumers --> Applied["Same shard primary<br/>Apply queued write; measure lag"]
```

The model tracks timeouts, dropped requests, replica errors, queue backlogs, and shard hot spots. An asynchronous write can be acknowledged before it reaches the database, so response latency and write-apply lag are reported separately.
