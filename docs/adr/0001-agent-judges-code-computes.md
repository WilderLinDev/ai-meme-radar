# 1. The agent judges, Python computes

Status: accepted (2026-11-13, rebuild)

Python owns everything deterministic: API calls and their records, sync, storage, normalization, dedupe, time series, change detection, link suggestions, backtests and report assembly. The agent owns everything that needs understanding: finding trends, reading formats, linking entities, judging demand, competition and feasibility, and the final four attributes with their reasons.

The boundary is enforced by the inputs. The agent writes `research.json` and `assessments.json`; Python validates them (schemas, duplicate entities, undefined refs, cited numbers present in the recorded API response) and refuses rather than guesses. Facts in the assessment draft are read-only and ignored on ingest.

Consequence: an agent cannot "adjust" a metric to fit a conclusion, and every number in a report can be traced to an evidence row or an API call.
