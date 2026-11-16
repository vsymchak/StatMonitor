# Roadmap diagram

8 of 17 steps shipped · 1 in progress · source: [roadmap.md](roadmap.md)

🟩 shipped · 🟧 in progress (specified, designed or being built) · 🟪 idea · ⬜ fog: not yet formulated. Columns are the execution waves; steps outside a column are not scheduled yet. An arrow means «needed by».

```mermaid
flowchart LR
    classDef shipped fill:#1b4332,stroke:#40916c,color:#d8f3dc,stroke-width:2px;
    classDef in_progress fill:#7f4f24,stroke:#d4a373,color:#faedcd,stroke-width:2px;
    classDef idea fill:#2b2d42,stroke:#8d99ae,color:#edf2f4,stroke-width:1px;
    classDef fog fill:#1e1e24,stroke:#4a4e69,color:#9a8c98,stroke-width:1px,stroke-dasharray: 4 4;

    subgraph Wave1["Wave 1: Data Ingestion"]
        1["1 · Dynamic schema<br>detection & ingestion<br><b>S</b>"]:::shipped
        2["2 · Odds history &<br>4-day retention<br><b>S</b>"]:::shipped
        3["3 · Telegram delivery<br>& HTML chunking<br><b>S</b>"]:::shipped
    end

    subgraph Wave2["Wave 2: Analytics & Paper Trading"]
        4["4 · Matplotlib drop<br>chart generator<br><b>S</b>"]:::shipped
        5["5 · Gemini AI analyzer<br>with failover<br><b>M</b>"]:::shipped
        6["6 · Paper Bank &<br>auto-staking<br><b>S</b>"]:::shipped
        7["7 · Score settlement<br>& daily report<br><b>M</b>"]:::shipped
    end

    subgraph Wave3["Wave 3: Scheduler Evolution"]
        8["8 · Dynamic schedule<br>by match kickoffs<br><b>M</b>"]:::shipped
        9["9 · GH Actions cron<br>healthcheck watchdog<br><b>S</b>"]:::in_progress
        10["10 · Smart rate-limiter<br>& quota allocator<br><b>S</b>"]:::idea
        11["11 · Hybrid external<br>runner webhook<br><b>M</b>"]:::idea
    end

    subgraph Wave4["Wave 4: Architecture & Reliability"]
        12["12 · Unit test suite<br>for picks & settlement<br><b>S</b>"]:::idea
        13["13 · Modular code<br>decomposition<br><b>M</b>"]:::idea
        14["14 · Dedicated DB<br>migrations & indexes<br><b>S</b>"]:::idea
    end

    subgraph Wave5["Wave 5: Advanced Features"]
        15["15 · Telegram bot<br>interactive commands<br><b>M</b>"]:::idea
        16["16 · Multi-sport &<br>leagues matrix<br><b>S</b>"]:::idea
    end

    17["17 · Web dashboard &<br>Observability UI<br><b>L</b>"]:::fog

    %% Dependencies
    1 --> 2
    2 --> 4
    3 --> 4
    3 --> 5
    5 --> 6
    6 --> 7
    3 --> 7

    %% Scheduler wave connections
    2 --> 8
    7 --> 8
    8 --> 9
    1 --> 10
    8 --> 10
    9 --> 11

    %% Wave 4 connections
    7 --> 12
    12 --> 13
    2 --> 14

    %% Wave 5 connections
    13 --> 15
    13 --> 16

    %% Fog connections
    13 -.-> 17
```
