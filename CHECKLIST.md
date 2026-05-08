# ✅ **Nodus Academic Research System Checklist**

---

# 🏗️ 1. Research-Oriented Architecture

### Core Design

* [ ] Modular structure:

  ```
  agents/
  orchestrator/
  tools/
  schemas/
  templates/
  reports/
  validation/
  ```
* [ ] LangGraph-based deterministic workflow
* [ ] Explicit **agent boundaries**:

  * Discovery
  * Validation
  * Summarization
  * Analysis
  * Citation
  * Report
* [ ] Separate:

  * Retrieval logic
  * Claim extraction
  * Cross-paper analysis
* [ ] All intermediate outputs stored as structured JSON
* [ ] Versioned report templates (survey, related-work, annotated bibliography)

---

# 📚 2. Scholarly Rigor & Methodological Integrity

* [ ] Explicit literature selection strategy
* [ ] Inclusion / exclusion criteria documented
* [ ] Minimum source threshold enforced (e.g., ≥ 5 peer-reviewed papers)
* [ ] Venue credibility scoring (ACL / NeurIPS / ICML tiers)
* [ ] DOI validation via CrossRef
* [ ] Deduplicate papers via title/DOI hash
* [ ] Preserve:

  * Methodology
  * Dataset
  * Evaluation metrics
  * Limitations per paper
* [ ] Prevent unsupported synthesis (no uncited claims)
* [ ] Ensure every claim in report links to ≥1 validated paper

---

# 🔬 3. Validation & Academic Quality Gates

* [ ] Reject non-academic sources by default
* [ ] Flag preprints vs peer-reviewed
* [ ] Citation count threshold (configurable)
* [ ] Detect contradictory findings across papers
* [ ] Track confidence level per thematic claim
* [ ] Track evidence density (claims per source)
* [ ] Store validation trace for reproducibility

---

# 🧪 4. Testing & Evaluation (Research-Focused)

* [ ] Unit tests for:

  * arXiv API wrapper
  * Semantic Scholar API
  * CrossRef validation
* [ ] Golden dataset of known survey topics
* [ ] Measure:

  * Citation correctness
  * Coverage depth
  * Missing key-paper rate
* [ ] Factual consistency evaluation
* [ ] Re-run reproducibility test (same query → stable taxonomy)
* [ ] Human academic review scoring rubric

---

# 📊 5. Observability & Reproducibility

* [ ] UUID per research session
* [ ] Store:

  * Search queries
  * Retrieved papers
  * Rejected papers + reason
* [ ] Persist:

  * Agent outputs
  * Taxonomy decisions
* [ ] Generate reproducibility artifact:

  ```
  /reports/<query_hash>/
      papers.json
      taxonomy.json
      report.md
      references.bib
  ```
* [ ] Log model versions used
* [ ] Track changes across runs (differential analysis)

---

# 🧠 6. Analysis & Synthesis Integrity

* [ ] Enforce taxonomy generation before synthesis
* [ ] Minimum papers per category
* [ ] Cross-category comparison matrix
* [ ] Open-problem extraction logic
* [ ] No hallucinated citations
* [ ] Claim-evidence traceability map

---

# 📎 7. Citation & Export Quality

* [ ] Automatic BibTeX generation
* [ ] DOI resolution
* [ ] LaTeX-ready output
* [ ] Markdown export
* [ ] DOCX / PDF via Pandoc
* [ ] Zotero-compatible export
* [ ] Reference consistency check (in-text vs bibliography)

---

# 🔐 8. Security & Governance (Academic Context)

* [ ] Prevent prompt injection from PDFs or scraped text
* [ ] Sanitize LaTeX output
* [ ] Secure API keys via `.env` or secrets manager
* [ ] Role-based access (student / researcher / reviewer)
* [ ] Avoid storing full PDFs unless user-approved

---

# 🔁 9. Extensibility

* [ ] Pluggable source adapters:

  * arXiv
  * PubMed
  * IEEE
  * Google Scholar (if API available)
* [ ] Modular taxonomy strategies
* [ ] Custom report templates
* [ ] Configurable depth levels:

  * Quick review
  * Standard survey
  * Deep meta-analysis
* [ ] Multi-domain support (NLP, Systems, Bio, Policy)

---

# 📈 10. Advanced Research Capabilities

* [ ] Trend detection over time
* [ ] Citation network graph generation
* [ ] Methodology clustering via embeddings
* [ ] Contradiction detection across papers
* [ ] Research gap scoring
* [ ] Benchmark usage frequency analysis
* [ ] Identify most influential datasets

---

# 📁 Required Repository Files

| File                 | Purpose                        |
|----------------------|--------------------------------|
| `.env.example`       | API key template               |
| `pyproject.toml`     | Dependency locking             |
| `Dockerfile`         | Reproducible environment       |
| `README.md`          | Architecture + usage           |
| `REPRODUCIBILITY.md` | Research trace documentation   |
| `templates/`         | Survey & report templates      |
| `schemas/`           | JSON schemas for agent outputs |

