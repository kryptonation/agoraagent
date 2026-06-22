# AgoraAgent: Autonomous Negotiation Simulation (2026)

This repository contains a stateful, autonomous, multi-agent negotiation platform prototype. It is built using **LangChain**, **LangGraph**, and **AWS Bedrock** models (e.g., Claude 3.5 Sonnet) as the underlying reasoning engine.

The system is designed to simulate a machine-to-machine social marketplace where autonomous agent delegates representing human buyers and sellers negotiate transaction agreements within private human-defined constraints.

---

## Key Features

1. **Direct Peer-to-Peer State Machine (LangGraph):** The Buyer Agent and Seller Agent alternate turns, counter-proposing prices and terms in a shared thread state until agreement, timeout (10 rounds max), or walking away (`abort`).
2. **Isolated Private Constraints:** Sensitive constraints (e.g., maximum budget for the buyer, minimum price for the seller, target prices) are loaded in memory directly at execution time and are *never* written to the public chat state, preventing leakage.
3. **Human-in-the-Loop (HITL) Interruption:** When the agents negotiate a mutually agreeable draft contract, the graph triggers a breakpoint (pauses) to await signatures. Human owners can review the draft, approve/sign it, reject it, or request revisions by providing natural language feedback.
4. **SQLite-based Semantic Memory Store:** Once a negotiation completes, the system summarizes the counterpart's traits (flexibility, aggressiveness, trust) and stores it in a SQLite relationship database (`memory.db`), which is reloaded as memory in future sessions.

---

## File Structure

- `src/morekick/config.py`: Initializer for the AWS Bedrock client (`ChatBedrock`) using Claude 3.5 Sonnet.
- `src/morekick/state.py`: Definition of the shared state (`NegotiationState`) and structured LLM outputs (`NegotiationOffer`).
- `src/morekick/agents.py`: System prompt formatting and execution nodes for the Buyer and Seller agents.
- `src/morekick/memory.py`: Database routines for saving agent interaction notes and logs to SQLite.
- `src/morekick/graph.py`: LangGraph workflow wiring, transition routers, checkpointers, and signature interrupts.
- `src/morekick/main.py`: Interactive CLI to configure constraints, stream agent communication, handle breakpoints, and view logs.
- `src/morekick/server.py`: FastAPI server exposing LangGraph workflow actions via REST APIs and Server-Sent Events (SSE) streaming.
- `frontend/`: Complete React/Vite TypeScript web dashboard client with modular state controls.
- `run_dashboard.sh`: Single-command local dev environment launcher.
- `Dockerfile`: Multi-stage Docker production deployment configuration.

---

## Setup & Running the Simulation

### Prerequisites
Make sure you have configured your AWS credentials (e.g., in `~/.aws/credentials` or via environment variables) for Bedrock access:
```bash
export AWS_ACCESS_KEY_ID="your_access_key"
export AWS_SECRET_ACCESS_KEY="your_secret_key"
export AWS_REGION="us-east-1"
```

### Option A: Web Dashboard (Recommended)
You can run a local server and watch the agents interact in a premium React UI.
1. Make sure Node.js (v20+) and Python (v3.13+) are installed.
2. Launch both servers with a single command:
   ```bash
   ./run_dashboard.sh
   ```
3. Open your browser and navigate to **http://localhost:5173** to use the application.

### Option B: Terminal CLI Simulation
Alternatively, you can run the original command line interface:
1. Sync packages:
   ```bash
   uv sync
   ```
2. Launch the CLI:
   ```bash
   PYTHONPATH=src .venv/bin/python src/morekick/main.py
   ```

---

## Docker & Cloud Deployment (AWS)

The project includes a multi-stage `Dockerfile` which bundles the built React frontend static assets directly inside the FastAPI image.

1. **Docker Build (AMD64 target):**
   ```bash
   docker build --platform linux/amd64 -t agoraagent:latest .
   ```
2. **Deploy on AWS (App Runner):**
   Push the image to your AWS Elastic Container Registry (ECR) and point an AWS App Runner service (using standard port `8000`) to it.
   Make sure to associate an IAM Instance Role with the App Runner service that grants access to AWS Bedrock:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": [
           "bedrock:InvokeModel",
           "bedrock:InvokeModelWithResponseStream"
         ],
         "Resource": "*"
       }
     ]
   }
   ```

---

## Example Flow

1. You start the script and configure the transaction (e.g., buying a **Custom API Integration**):
   - Buyer Max Budget: `$1500.00`
   - Seller Min Price: `$900.00`
2. The graph starts. The console streams the agents counter-proposing values back and forth.
3. When they agree (e.g., at `$1200.00`), a breakpoint pauses execution.
4. You are prompted to act as both human owners to sign, reject, or request changes.
5. Once signed, the database logs the finalized contract, summarizes the counterpart's behaviors, and updates the permanent semantic memory database.
