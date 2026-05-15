# AI Inference Microservice

A production-grade gRPC microservice that exposes **all four gRPC communication patterns** backed by **Google Gemini**, deployed behind a **Nginx Layer 7 Load Balancer** across three replicated backend instances.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                       Docker Network: ai_mesh                   │
│                                                                 │
│  ┌──────────┐        ┌────────────────────────────────────┐    │
│  │  Client  │──────► │   Nginx (HTTP/2 · grpc_pass · :80) │    │
│  │  CLI     │        │     Round-Robin Load Balancer       │    │
│  └──────────┘        └──────┬──────────┬──────────┬───────┘    │
│                             │          │          │             │
│                    ┌────────▼─┐  ┌─────▼────┐  ┌─▼────────┐  │
│                    │ Server 1 │  │ Server 2 │  │ Server 3 │  │
│                    │  :50051  │  │  :50051  │  │  :50051  │  │
│                    └──────────┘  └──────────┘  └──────────┘  │
│                         └─────────────┬─────────────┘          │
│                                       │                         │
│                               ┌───────▼──────┐                 │
│                               │ Google Gemini │                 │
│                               │  (external)   │                 │
│                               └──────────────┘                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
ai_inference_microservice/
├── protos/
│   └── ai_inference.proto          ← API contract (source of truth)
├── server/
│   ├── server.py                   ← gRPC server (all 4 RPC types + interceptor)
│   ├── ai_inference_pb2.py         ← generated (run `make proto`)
│   ├── ai_inference_pb2_grpc.py    ← generated
│   ├── requirements.txt
│   └── Dockerfile
├── client/
│   ├── client.py                   ← CLI tester (all 4 RPC types)
│   ├── ai_inference_pb2.py         ← generated
│   ├── ai_inference_pb2_grpc.py    ← generated
│   ├── requirements.txt
│   └── Dockerfile
├── nginx/
│   └── nginx.conf                  ← HTTP/2 + grpc_pass + upstream block
├── docker-compose.yml
├── Makefile
└── README.md
```

---

## Quick Start

### Prerequisites
- Docker ≥ 24 & Docker Compose v2
- Python 3.11+ (only needed to regenerate stubs locally)
- A **Google Gemini API key** from https://aistudio.google.com

### 1. Clone & Configure

```bash
git clone https://github.com/p3ter-dev/AI_Inference_Microservice
cd AI_Inference_Microservice

# Create a .env file (never commit this)
cat > .env <<EOF
GEMINI_API_KEY=your_gemini_api_key_here
API_SECRET_KEY=my-secret-key
EOF
```

### 2. (Optional) Regenerate Protobuf Stubs

The compiled stubs are included. Only run this if you edit the `.proto` file.

```bash
pip install grpcio-tools
make proto
```

### 3. Build & Start the Mesh

```bash
make build   # builds server and client Docker images
make up      # starts nginx + 3 backend replicas in detached mode
```

### 4. Run the CLI Tester

**Option A – Using Makefile (recommended)**
```bash
make test
```

**Option B – Direct Docker Compose Command**
```bash
docker compose --profile test run --rm client
```
This builds and runs the test client container, automatically waiting for all backend services to be healthy before starting.

**Option C – Locally (mesh must be running)**
```bash
pip install grpcio google-generativeai
make run-local
```

### 5. Expected Output

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   AI INFERENCE MICROSERVICE – CLI TESTER
   Target : localhost:80
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

──────────── Task 2 · Unary · Sentiment Analysis ────────────
  Input : Absolutely loved this product! ...
  Deadline: 60 seconds (waiting for AI analysis)

  ✔ Label      : POSITIVE
  ✔ Confidence : 0.92
  ✔ Reasoning  : The review uses enthusiastic language and recommends the product.

──────── Task 3 · Server-Streaming · Text Generation ────────
  Prompt: Explain gRPC streaming in three sentences, simply.
  Response: gRPC streaming allows ... [live tokens appear here]

  ✔ Stream complete.

────── Task 4 · Client-Streaming · Batch Summarization ──────
  → Sending chunk 0 (312 chars)…
  → Sending chunk 1 (298 chars)…
  → Sending chunk 2 (287 chars)…

  ✔ Chunks received by server : 3
  ✔ Summary:
     gRPC is a high-performance RPC framework developed by Google ...

────── Task 5 · Bidirectional-Streaming · Live Chat ─────────
  You [turn-1]: Hello! What is Protocol Buffers in one sentence?
  Assistant [turn-1]: Protocol Buffers is a language-neutral ...

  You [turn-2]: And what makes HTTP/2 different from HTTP/1.1?
  Assistant [turn-2]: HTTP/2 introduces multiplexing ...

  ✔ Chat session complete.
────────────────────────────────────────────────────────────

  ✔  All tests completed.
```

---

## RPC Pattern Reference

| Task | Pattern | Proto RPC | Use-case |
|------|---------|-----------|---------|
| 2 | Unary | `AnalyzeSentiment` | Single request → single response |
| 3 | Server-Streaming | `GenerateText` | Single request → stream of tokens |
| 4 | Client-Streaming | `SummarizeDocument` | Stream of chunks → single summary |
| 5 | Bidirectional | `LiveChat` | Concurrent message/response streams |

---

## Bonus Features

### Auth Interceptor (gRPC Metadata)
Every call must include `Authorization: Bearer my-secret-key` in metadata.
The `AuthInterceptor` validates this **before** any service logic runs.

Test with a bad key:
```python
# In client.py, change:
AUTH_META = [("authorization", "Bearer wrong-key")]
# Server responds: StatusCode.UNAUTHENTICATED "Invalid API key"
```

### Timeout Configuration
`AnalyzeSentiment` uses a **60-second timeout** to allow time for API calls to Google Gemini. If the server cannot reach Gemini within this window, the client receives an error. This demonstrates gRPC's deadline propagation and error handling.

### API Quotas & Limits
The free tier of Google Gemini API allows **20 requests/day**. If you exhaust the quota, either:
- Wait until the next UTC day for the quota to reset
- Comment out `GEMINI_API_KEY` in `.env` to use **stub responses** (mock data) instead
- Upgrade your Gemini API plan for higher limits

---

## Makefile Commands

| Command | Description |
|---------|-------------|
| `make proto` | Regenerate gRPC stubs from `.proto` |
| `make build` | Build Docker images |
| `make up` | Start the full mesh (detached) |
| `make down` | Stop all containers |
| `make test` | Run CLI tester inside Docker |
| `make logs` | Tail all container logs |
| `make logs-nginx` | Tail Nginx logs only |
| `make run-local` | Run client locally vs live mesh |
| `make clean` | Remove all containers, images, volumes |

---

## Nginx – Layer 7 Load Balancing Details

```nginx
upstream grpc_backends {
    server grpc_server_1:50051;
    server grpc_server_2:50051;
    server grpc_server_3:50051;
    keepalive 32;
}

server {
    listen 80 http2;        # HTTP/2 mandatory for gRPC

    location / {
        grpc_pass grpc://grpc_backends;   # native gRPC proxy
    }
}
```

**Why `grpc_pass` and not `proxy_pass`?**  
`proxy_pass` operates at the HTTP/1.1 level. gRPC uses HTTP/2 framing (binary multiplexed streams with trailers). `grpc_pass` understands this framing, correctly forwards `Content-Type: application/grpc` headers, and propagates gRPC status trailers back to the client.

---

## Stopping & Cleanup

```bash
make down          # stop containers, keep images
make clean         # remove everything including images and volumes
```
