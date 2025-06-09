# 🧠 Nodus — Agentic Research Assistant

**Nodus** is a local-first, agent-powered research assistant that autonomously searches the web, extracts and summarizes key insights, and attributes sources — giving you trustworthy, multi-source answers in minutes.

---

## 🚀 Features

- 🔍 Multi-agent system: planner, searcher, summarizer, fact-checker
- ➡️ Follow up Query Response with Conditional Recursive Search
- 🌐 Web search + clean content extraction
- 🧠 Local LLM summarization (via Ollama)
- 📎 Source attribution and citation formatting
- 📤 Export to markdown or PDF

[//]: # (- 🔁 Scheduled auto-refresh with change detection)

---

## 🛠️ Tech Stack

- Python 3.10+
- LangChain / LangGraph
- Ollama (for local LLMs like `phi-3`, `mistral`)
- `newspaper3k`, `trafilatura`, `duckduckgo-search`
- Streamlit

---

## 📦 Setup

```bash
git clone https://github.com/your-username/scope-research-agent
cd nodus-research-agent
poetry install
````
Launch the UI:

```bash
streamlit run main.py
```

---

## 📌 Example Query

> "What are the latest developments in EU AI regulation?"

The agent returns a concise report with:

* ✅ Clean summary of findings
* 📎 Inline citations
* 📝 Exportable report

---

## 🔓 License

MIT — build, modify, or extend freely.

---

## 🧱 Project Structure
```text
nodus-research-agent/
│
├── main.py                          # Entry point — Streamlit
├── config.py                        # Configs (API keys, LLM, settings)
├── pyproject.toml                   # All dependencies
├── README.md                        # Usage & setup docs
│
├── agents/                         # Modular agents (LangChain/ LangGraph)
│   ├── planner.py                  # Task planner agent
│   ├── search_agent.py             # Web search agent
│   ├── summarizer_agent.py         # Per-source summarizer
│   ├── aggregator_agent.py         # Combines summaries + source mapping
│   ├── fact_checker_agent.py       # Cross-article fact validation
│   ├── citation_agent.py           # Citation formatter
│
├── tools/                           # LangChain tools or utility classes
│   ├── search.py                    # Tavily API wrapper
│   ├── summarizer.py                # Local LLM summarization calls
│   ├── fact_check.py                # Source consistency checker
│   ├── citation.py                  # Format and assign reference numbers
│   ├── exporter.py                  # Markdown/PDF report export
│
├── utils/                           # Helper functions, shared logic
│   ├── logger.py                    # Logging utility
│   ├── clean_text.py                # HTML cleanup, regex fixes
│   ├── memory.py                    # Local cache/memory (JSON or Chroma)
│   ├── embeddings.py                # For clustering/fact-checking
│
├── data/                            # Local saved data, memory
    ├── cache/                       # Previously fetched articles
    ├── reports/                     # Saved outputs (md, pdf)
    └── memory.json                  # Simple local memory
```