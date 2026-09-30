# FMSE 2026 course labs

Google Colab notebooks and the `fmse_labkit` package for **Foundation Model Systems Engineering
(FMSE 2026)**. The course home, progress and Engineering Notebook are on
[agentic-ai.es/academy/fmse](https://agentic-ai.es/academy/fmse) (free account required); this
repository is the lab runtime. Open a lab from its module page, or in Colab directly:
`https://colab.research.google.com/github/farithjhg/fmse-course-labs/blob/main/<notebook>`.

| Lab | Notebook |
| --- | --- |
| 00 Task Framing Laboratory | `labs/lab-00-task-framing.ipynb` |
| 01 Build a Typed Model Call | `labs/lab-01-typed-model-call.ipynb` |
| 02 ConOps Builder | `labs/lab-02-conops-builder.ipynb` |
| 03 Requirements and AI-FMEA Workbench | `labs/lab-03-ai-fmea.ipynb` |
| 04 Model Profiler | `labs/lab-04-model-profiler.ipynb` |
| 05 RAG from First Principles | `labs/lab-05-rag-first-principles.ipynb` |
| 06 Architecture Trade Study Workbench | `labs/lab-06-trade-study.ipynb` |
| 07 Prompt Manifest Laboratory | `labs/lab-07-prompt-systems.ipynb` |
| 08 Typed Extraction and Tool Contract | `labs/lab-08-tool-contracts.ipynb` |
| 09 Context Budget Optimizer | `labs/lab-09-context-budget.ipynb` |
| 10 Safe Tool-Using Agent | `labs/lab-10-safe-agent-mcp.ipynb` |
| 11 Multimodal Document Verification | `labs/lab-11-multimodal-verification.ipynb` |
| 12 Evaluation Harness | `labs/lab-12-evaluation-harness.ipynb` |
| 13 Break the Agent | `labs/lab-13-break-the-agent.ipynb` |
| 14 Optimize a Measured Pipeline | `labs/lab-14-optimization.ipynb` |
| 15 CI Gate Simulator | `labs/lab-15-production.ipynb` |
| 16 Capstone Studio | `capstone/capstone-studio.ipynb` (+ `capstone/templates`, `capstone/datasets`) |

Every notebook follows the same structure (mission, requirements, setup, secrets check, guided
experiment, predict-before-you-run, challenge, public validation, robustness probes, reflection,
export) and runs **offline** on a free runtime: model behaviour comes from documented simulators
unless you configure your own provider in Colab Secrets (`FMSE_PROVIDER`, `FMSE_MODEL` and a key).
Keys are never printed or exported.

**En español:** every notebook has a Spanish version next to it (`labs/lab-NN-*.es.ipynb`,
`capstone/capstone-studio.es.ipynb`), with Spanish explanations and validator feedback. Code and
data keys stay English, and answers may be written in either language.

Public validators report which requirement failed and why, never the expected implementation. The
completion record each notebook prints is a learning-workflow document, not a certificate.

Maintainers: edit `labsrc/*.lab` and its Spanish twin in `labsrc/es/`, then `python3 tools/build_notebooks.py`; test with
`python3 -m unittest discover -s tests`. The source of truth is the `fmse-course-labs/` folder of
the portal repository, published here with `scripts/fmse/publish-labs.sh`; changes made directly in
this repository are overwritten by the next publish.
