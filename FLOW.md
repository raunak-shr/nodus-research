## 🔁 **End-to-End Agentic Workflow for Nodus**

### 🧑‍💻 Step 0: User Input

> **User enters:**
> *"What are the recent developments in European AI regulation?"*

---

### 🧠 Step 1: Task Planning Agent

* Receives raw query
* Breaks it into subtasks or goals:

  * Search the web for recent and relevant information
  * Summarize findings from each source
  * Synthesize an overall answer
  * Validate key facts across sources
  * Generate citations

📌 *Optional*: Classify query type (trend, regulation, comparison) → plan path dynamically.

---

### 🌍 Step 2: Web Search Tool

* Planner calls the **Search Tool**
* Tool uses Tavily to fetch \~5–10 relevant URLs
* Extracts clean text (no urls, images, etc.)
* Returns list of URLs ranked by relevance or recency

---

### 🧠 Step 3: Summarization Agent

For each clean article:

* Agent calls the **LLM Tool** (via Ollama)

* Uses a prompt template like:

  > "Summarize the following article in 3 bullet points with focus on AI regulation. Avoid hallucination. Do not include your opinion."

* Each article is now:

  * Summarized (few sentences or bullets)
  * Tagged with its source

---

### ✅ Step 4: Fact Checker Agent

* Accepts all article summaries.

* Calls the Fact Checker Tool to:

  * Compare claims across sources.

  * Highlight inconsistencies.

  * Flag hallucinations or unsupported points.

✅ Adds confidence scores or validation metadata per claim:

```json
{
  "claim": "The EU AI Act was passed in March 2024",
  "valid": true,
  "supporting_sources": [1, 3]
}
```

---
### 🧮 Step 5: Aggregation Agent

* Takes all summaries
* Runs **final synthesis** via another LLM call:

  * De-duplicates
  * Clusters insights
  * Builds a coherent answer
  * Adds inline \[1], \[2] citations mapped to source URLs

---

### 📎 Step 6: Citation Tool

* Formats the original source links in standard citation format:

  * `[1] EU Commission Press Release (2024). https://ec.europa.eu/ai-act`
  * `[2] Wired Article on AI Regulation. https://wired.com/ai-europe...`

---

### 🧾 Step 7: Output Generation

* Final output includes:

  * ✅ Concise summary (1–2 paragraphs or bullets)
  * 🔗 Inline citations
  * 📤 Option to export (Markdown / PDF / Clipboard)
* Optionally stored in `/data/` with timestamped filename

---

### 🎛️ Optional (Enterprise Mode)

* [ ] Log query/flow metadata for observability
* [ ] Compare with previous run if query was asked before
* [ ] Store output in ChromaDB for RAG enhancement

---

## 📈 Example Output

**Query**: *What are the recent developments in European AI regulation?*

---

**Answer**:

* The EU Parliament passed the AI Act in March 2025, introducing tiered risk categories and stricter compliance for foundation models \[1].
* Germany proposed additional national guidelines to address explainability and data governance \[2].
* Critics argue enforcement mechanisms remain weak, especially for cross-border AI providers \[3].

**Citations**:
[1] [https://europa.eu/ai-act-release](https://europa.eu/ai-act-release)
[2] [https://zeit.de/2025/ai-gesetz](https://zeit.de/2025/ai-gesetz)
[3] [https://techcrunch.com/eu-ai-act-debate](https://techcrunch.com/eu-ai-act-debate) 
