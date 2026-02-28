# Knowledge Service v0 - Development Handoff

## 📍 Current Status: Phase 1 Complete

**Completed:** 2026-02-19  
**Next Phase:** Phase 2 - Layer 1 (QMD Adapter)

---

## ✅ What's Been Built

### Phase 1: Python Project Scaffold

1. **Project Structure** - Complete folder hierarchy
   ```
   knowledge-service/
   ├── README.md                  # Architecture overview
   ├── requirements.txt           # All 7 dependencies
   ├── config/                    # Config directory
   └── src/
       ├── __init__.py
       ├── layer1/__init__.py
       ├── layer2/__init__.py
       ├── api/
       │   ├── __init__.py
       │   └── models.py          # ✅ Complete Pydantic models
       └── sync/__init__.py
   ```

2. **API Contract** - All 5 operations defined in `src/api/models.py`
   - `resolve-context` - Resolve scope chain, return operational pages
   - `search` - Full-text + semantic search with progressive disclosure
   - `get-page` - Retrieve full page by identifier
   - `get-related` - Follow links to related pages
   - `list-by-scope` - Browse/filter by scope, mode, type, tags

3. **Data Models** - Complete Pydantic models
   - `PageSummary` - Progressive disclosure (description only)
   - `PageFull` - Complete page with body and relationships
   - `ScopeFilter` - Hierarchical scope filtering
   - Request/Response models for each operation

---

## 🔜 Next Steps: Phase 2 - Layer 1 (QMD Adapter)

### Task 2.1: Define Abstract SearchStore Interface

**File:** `src/layer1/interface.py`

Create an ABC (Abstract Base Class) that defines the contract for search/storage operations. This allows QMD to be swapped out later for Elasticsearch or Document Service.

**Methods to define:**
```python
class SearchStore(ABC):
    @abstractmethod
    def search(self, query: str, collection: str | None = None, limit: int = 10) -> list[SearchResult]
    
    @abstractmethod
    def semantic_search(self, query: str, collection: str | None = None, limit: int = 10) -> list[SearchResult]
    
    @abstractmethod
    def hybrid_search(self, query: str, collection: str | None = None, limit: int = 10) -> list[SearchResult]
    
    @abstractmethod
    def get_document(self, file_path: str) -> str | None
    
    @abstractmethod
    def get_documents_by_glob(self, pattern: str) -> list[Document]
    
    @abstractmethod
    def list_documents(self, collection: str | None = None) -> list[str]
    
    @abstractmethod
    def reindex(self) -> None
    
    @abstractmethod
    def status(self) -> dict
```

**Also define:**
- `SearchResult` dataclass: `file_path`, `score`, `snippet`, `collection`
- `Document` dataclass: `file_path`, `content`, `collection`

### Task 2.2: Implement QMD Adapter

**File:** `src/layer1/qmd_adapter.py`

Implement `QMDAdapter(SearchStore)` that shells out to QMD CLI via `subprocess.run()`.

**Key implementation details:**
- Use `--index knowledge` flag to isolate from user's personal QMD index
- All commands use `--json` for structured output
- Helper method `_run_qmd(args: list[str]) -> str` for subprocess execution
- Parse JSON output into dataclass instances

**QMD commands to use:**
- `qmd --index knowledge search "<query>" --json -n <limit>` - BM25 keyword search
- `qmd --index knowledge vsearch "<query>" --json -n <limit>` - Semantic vector search
- `qmd --index knowledge query "<query>" --json -n <limit>` - Hybrid (best quality)
- `qmd --index knowledge get "<file_path>"` - Retrieve full document
- `qmd --index knowledge multi-get "<pattern>" --json` - Retrieve multiple docs
- `qmd --index knowledge ls [collection]` - List indexed documents
- `qmd --index knowledge update` - Re-index all collections
- `qmd --index knowledge embed` - Rebuild vector embeddings
- `qmd --index knowledge status` - Index health info

### Task 2.3: Collection Setup Logic

**File:** `src/layer1/qmd_adapter.py` (add to QMDAdapter class)

Add `ensure_collections(self, shared_path: str, workspace_path: str)` method that:
1. Checks existing collections via `qmd --index knowledge collection list`
2. Adds "shared" collection if missing: `qmd --index knowledge collection add {shared_path} --name shared --mask "**/*.md"`
3. Adds "workspace" collection if missing: `qmd --index knowledge collection add {workspace_path} --name workspace --mask "**/*.md"`
4. Runs initial index: `qmd --index knowledge update`
5. Runs initial embed: `qmd --index knowledge embed`

Must be idempotent - safe to call multiple times.

---

## 📚 Key Resources

### Documentation
- **Story file:** `/Users/akhera/Desktop/Repositories/Notes/Projects/Agent-Automation/stories/Knowledge-Service-v0.md`
- **Sample pages:** `/Users/akhera/Desktop/Repositories/Notes/Tasks/examples/knowledge-service-page-samples.md`
- **This README:** `automation/knowledge-service/README.md`

### Code Repositories
- **Service code:** `/Users/akhera/Desktop/Repositories/automation/knowledge-service/`
- **QMD location:** `/Users/akhera/Desktop/Repositories/qmd` (already cloned)
- **Data repo (future):** `akhera/knowledge-base` (markdown pages - not created yet)

### Architecture
```
┌─ Docker Container ─────────────────────────────────────────┐
│  REST API (:8000, FastAPI)                                  │
│    ├── Layer 2: Knowledge Logic                             │
│    │     (scope-chain, mode filter, progressive disclosure) │
│    └── Layer 1: QMD Adapter (subprocess)                    │
│          ├── Collection: "shared"                            │
│          │     └── /data/knowledge-repo/ (cloned inside)    │
│          └── Collection: "workspace"                         │
│                └── /workspace/ (mounted from host, ro)      │
└─────────────────────────────────────────────────────────────┘
```

---

## 🛠️ Development Setup

### Install Dependencies
```bash
cd /Users/akhera/Desktop/Repositories/automation/knowledge-service
pip install -r requirements.txt
```

### Verify QMD is Available
```bash
qmd --version
# Should show QMD version info
```

### Run Tests (Phase 2+)
```bash
# After implementing Layer 1, test QMD integration:
python -c "from src.layer1.qmd_adapter import QMDAdapter; adapter = QMDAdapter(); print(adapter.status())"
```

---

## 📋 Phase Checklist

- [x] **Phase 1**: Python Project Scaffold ✅ COMPLETE
  - [x] Task 1.1: Project structure + requirements.txt
  - [x] Task 1.2: Pydantic models

- [ ] **Phase 2**: Layer 1 - QMD Adapter
  - [ ] Task 2.1: Abstract SearchStore interface
  - [ ] Task 2.2: QMD adapter implementation
  - [ ] Task 2.3: Collection setup logic

- [ ] **Phase 3**: Layer 2 - Knowledge Logic
  - [ ] Task 3.1: Frontmatter parser
  - [ ] Task 3.2: Scope-chain resolver
  - [ ] Task 3.3: Mode filtering + progressive disclosure
  - [ ] Task 3.4: Link navigator

- [ ] **Phase 4**: REST API
  - [ ] Task 4.1: 5 REST endpoints
  - [ ] Task 4.2: FastAPI app entry point

- [ ] **Phase 5**: Sync Daemon
  - [ ] Task 5.1: Git pull loop + file watcher
  - [ ] Task 5.2: Wire into entrypoint

- [ ] **Phase 6**: Docker Image
  - [ ] Task 6.1: Dockerfile
  - [ ] Task 6.2: docker-compose.yml

- [ ] **Phase 7**: MCP Thin Client
  - [ ] Task 7.1: npm package scaffold
  - [ ] Task 7.2: MCP server implementation

- [ ] **Phase 8**: Validation
  - [ ] Task 8.1: Local integration test
  - [ ] Task 8.2: Docker end-to-end test

---

## 💡 Tips for Next Developer

1. **Read the sample pages first** - Understanding the frontmatter schema is crucial. See `Tasks/examples/knowledge-service-page-samples.md` for 10 validated examples.

2. **Test QMD commands manually** - Before implementing the adapter, run QMD commands in your terminal to understand the output format.

3. **Start simple** - Implement the interface first, then add one QMD command at a time to the adapter.

4. **Use subprocess with caution** - Always capture stderr, handle non-zero exit codes, and parse JSON carefully.

5. **The two-layer architecture is key** - Layer 1 (search/storage) is swappable. Layer 2 (knowledge logic) is stable. Keep them decoupled.

---

## 🐛 Known Issues / Gotchas

- QMD requires Bun runtime - will be bundled in Docker image (Phase 6)
- QMD uses `--index` flag to isolate indexes - always use `--index knowledge`
- Collection paths must be absolute in Docker container
- File watcher (Phase 5) needs debouncing to avoid re-indexing on every keystroke

---

## 📞 Questions?

Refer back to the story file for detailed implementation guidance. Each phase has step-by-step instructions with code examples.

**Story location:** `/Users/akhera/Desktop/Repositories/Notes/Projects/Agent-Automation/stories/Knowledge-Service-v0.md`
