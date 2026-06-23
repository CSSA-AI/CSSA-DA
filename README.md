# CSSA-DA: RAG Chatbot for International Students

A Retrieval-Augmented Generation (RAG) chatbot designed for Chinese students and scholars studying in Australia. The system answers questions about education, university requirements, visa processes, and student life by retrieving relevant articles and generating contextual responses via ChatGPT.

---

## Architecture

```
User Query
    │
    ▼
[Retriever]   ──  FAISS semantic search over article question embeddings
    │
    ▼
[Reranker]    ──  CrossEncoder re-ranking (LoRA fine-tuning supported)
    │
    ▼
[Generator]   ──  OpenAI SDK generation with explicit chat history
    │
    ▼
Answer + Source Articles
```

The pipeline is orchestrated in [app/services/rag/orchestrator.py](app/services/rag/orchestrator.py) and exposed via a Streamlit demo at [scripts/demo.py](scripts/demo.py).

---

## Repo Layout

```
CSSA-DA/
├── app/
│   ├── main.py                              # FastAPI entry point (placeholder)
│   ├── api/
│   │   └── deps.py                          # Dependency injection (DB session, RAG pipeline)
│   ├── core/
│   │   └── config.py                        # Pydantic settings (placeholder)
│   ├── models/                              # SQLAlchemy DB models (planned)
│   │   ├── article.py
│   │   └── chat_log.py
│   ├── schemas/
│   │   ├── article.py                       # Article Pydantic schema
│   │   └── search_result.py                 # RAG output schema (article + score + rank)
│   └── services/
│       ├── question_generator/              # GPT-powered question generation for articles
│       │   ├── question_generator.py        # Main generation logic (OpenAI batch API)
│       │   ├── file_processor.py
│       │   ├── config.py
│       │   └── main.py
│       └── rag/                             # Core RAG pipeline
│           ├── orchestrator.py              # Wires retriever → reranker → generator
│           ├── retriever/
│           │   ├── base.py                  # Abstract base class
│           │   └── faiss_retriever.py       # FAISS + SentenceTransformer semantic search
│           ├── reranker/
│           │   ├── base.py                  # Abstract base class
│           │   ├── cross_encoder.py         # CrossEncoder with optional LoRA adapter
│           │   ├── qa_dataset.py            # QA dataset for reranker training
│           │   └── train_lora.py            # LoRA fine-tuning script
│           ├── generator/
│           │   ├── base.py                  # Abstract base class
│           │   └── chatgpt_generator.py     # OpenAI SDK generation + streaming
│           ├── eval/                        # Evaluation module (WIP)
│           └── tests/
│               ├── test_faiss_retriever.py
│               └── test_orchertrator.py
│
├── scripts/
│   ├── demo.py                              # Streamlit web demo
│   ├── merge_json.py                        # Merge multiple JSON data files
│   ├── run_question_generator.py            # CLI launcher for question generation
│   └── chunking/                            # Web scrapers and chunking notebooks
│       ├── aoji_harvester.py                # AOJI website scraper
│       ├── YI_XIANG_HAO_JU.ipynb
│       ├── YUN_XIAO_EDU_AU.ipynb
│       └── myoffer_harvester.ipynb
│
├── data/                                    # Local data files (not committed to git)
│   ├── demo_data.json                       # Merged article dataset used by demo
│   ├── qa_clean_data.json                   # Cleaned QA pairs for training
│   ├── qa_faiss_index_bert.index            # Saved FAISS index (BERT embeddings)
│   ├── qa_faiss_index_trans.index           # Saved FAISS index (transformer embeddings)
│   └── ...                                  # Raw scraped JSONs per source
│
├── tests/
│   └── test_db.py
│
├── Dockerfile.cpu                           # CPU Docker image
├── Dockerfile.gpu                           # GPU Docker image
├── docker-compose.yml                       # PostgreSQL + pgvector + app services
├── environment_cpu.yml                      # Conda environment (CPU)
├── environment_gpu.yml                      # Conda environment (GPU)
├── branch-policy.md                         # Git branching conventions
└── docker-command.md                        # Docker usage reference
```

---

## Setup

### 1. Conda (recommended)

```bash
# CPU
conda env create -f environment_cpu.yml
conda activate cssa-ai

# GPU
conda env create -f environment_gpu.yml
conda activate cssa-ai
```

To update an existing environment:
```bash
conda env update -f environment_cpu.yml --prune
```

### 2. Environment Variables

Copy `.env.example` to `.env` and fill in:

```
OPENAI_API_KEY=sk-...
```

### 3. Docker

```bash
docker-compose up
```

See [docker-command.md](docker-command.md) for detailed Docker usage.

---

## Running the Demo

```bash
streamlit run scripts/demo.py
```

This launches a chat UI at `http://localhost:8501` with streaming responses and source attribution.

### Running the API

```bash
uvicorn app.main:app --reload
```

The API is available at `http://localhost:8000`, with interactive documentation at
`http://localhost:8000/docs`. Use `GET /health` to check the service and `POST /chat`
to submit a message to the RAG pipeline.

---

## Key Components

### Retriever ([app/services/rag/retriever/faiss_retriever.py](app/services/rag/retriever/faiss_retriever.py))
- Encodes article questions using SentenceTransformers
- Stores and searches embeddings with FAISS
- Returns ranked `SearchResult` objects (article + similarity score)

### Reranker ([app/services/rag/reranker/cross_encoder.py](app/services/rag/reranker/cross_encoder.py))
- Re-scores retrieved results using a CrossEncoder model
- Supports loading a LoRA adapter for domain-specific fine-tuning
- Training script: [app/services/rag/reranker/train_lora.py](app/services/rag/reranker/train_lora.py)

### Generator ([app/services/rag/generator/chatgpt_generator.py](app/services/rag/generator/chatgpt_generator.py))
- OpenAI SDK integration without a LangChain dependency
- Explicit plain-dictionary chat history supplied by the calling application
- Context truncation plus synchronous and streaming output

The optional `LangChainRAGAdapter` wraps the framework-independent components as
LCEL runnables and returns shared pipeline state containing the answer and sources.

### Question Generator ([app/services/question_generator/](app/services/question_generator/))
- Uses GPT to generate natural Chinese questions for each article (used to build the FAISS search index)
- Detects content patterns (cost, requirements, process, comparison, etc.) to generate relevant question types
- Configurable via [app/services/question_generator/config.py](app/services/question_generator/config.py)

---

## Data Schema

**Article** (`app/schemas/article.py`):

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Unique identifier |
| `text` | str | Article body |
| `questions` | List[str] | GPT-generated questions (used for retrieval) |
| `source` | str | Origin website |
| `author` | str | Author name |
| `post_date` | date | Publication date |
| `language` | str | Content language |
| `tags` | List[str] | Topic tags |
| `link` | str | Original URL |

---

## Team Structure

| Squad | Responsibilities |
|-------|-----------------|
| **A — Data** | Web scrapers, data cleaning, text chunking |
| **B — AI** | RAG pipeline, reranker, generator, prompt engineering |
| **C — Platform** | FastAPI layer, database, security, DevOps |

See [branch-policy.md](branch-policy.md) for branching conventions (`feature/`, `bugfix/`, `hotfix/`, `release/`, `chore/`).
