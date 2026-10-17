import csv, json, os, platform, re, subprocess, threading, time
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import streamlit as st
try:
    import psutil
except ImportError:
    psutil = None

APP_DIR = Path(__file__).resolve().parent.parent
DATA = APP_DIR / "data"
LOGS = DATA / "logs"
RESULTS = DATA / "results.csv"
RUNS = DATA / "runs.jsonl"
DATA.mkdir(exist_ok=True); LOGS.mkdir(exist_ok=True)
COLS = ["run_id","timestamp_utc","threads","cc_alg","index_struct","workload","status","exit_code","duration_seconds","completed_txns","aborts","reported_runtime_seconds","throughput_txn_s","cpu_percent_mean","rss_mb_peak","context_switches_voluntary","context_switches_involuntary","git_commit","log_file","command"]

def read_config(repo):
    path = repo / "config.h"; out = {}
    if path.exists():
        txt = path.read_text(errors="replace")
        for key in ("CC_ALG","INDEX_STRUCT","WORKLOAD","ENABLE_LATCH"):
            m = re.search(r"^\s*#\s*define\s+" + key + r"\s+([^\s/]+)", txt, re.M)
            if m: out[key] = m.group(1)
    return out

def git_commit(repo):
    try:
        return subprocess.run(["git","rev-parse","--short","HEAD"], cwd=repo, capture_output=True, text=True, timeout=4, check=True).stdout.strip()
    except Exception:
        return "unknown"

def parse_log(txt):
    def find(patterns, cast):
        for pattern in patterns:
            m = re.search(pattern, txt, re.I | re.M)
            if m:
                try: return cast(m.group(1).replace(",", ""))
                except (ValueError, TypeError): pass
        return None
    txns = find([r"(?:#\s*of\s*completed\s*txns|completed[_ ]txn(?:s|_cnt)?|total_txn_cnt|txn_cnt)\s*[:=]\s*([0-9,]+)"], int)
    aborts = find([r"(?:#\s*of\s*aborts|total_abort_cnt|abort[_ ]cnt|abort_cnt)\s*[:=]\s*([0-9,]+)"], int)
    runtime = find([r"(?:run_time|runtime|run time|elapsed(?:_seconds)?)\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)"], float)
    throughput = find([r"(?:throughput|txn(?:s|_per_second)?/s)\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)"], float)
    if throughput is None and txns is not None and runtime and runtime > 0: throughput = txns / runtime
    return {"completed_txns":txns,"aborts":aborts,"reported_runtime_seconds":runtime,"throughput_txn_s":throughput,"pass_marker":bool(re.search(r"PASS!",txt,re.I))}

def sample(proc, samples):
    if psutil is None: return
    try:
        p = psutil.Process(proc.pid); p.cpu_percent(interval=None)
        while proc.poll() is None:
            try:
                cpu = p.cpu_percent(interval=.5); rss = p.memory_info().rss/(1024*1024); cs = p.num_ctx_switches()
                samples.append({"cpu":cpu,"rss":rss,"vol":cs.voluntary,"invol":cs.involuntary})
            except (psutil.NoSuchProcess, psutil.AccessDenied): break
    except (psutil.NoSuchProcess, psutil.AccessDenied): pass

def ensure_results():
    if not RESULTS.exists():
        with RESULTS.open("w",newline="",encoding="utf-8") as f: csv.DictWriter(f,fieldnames=COLS).writeheader()

def save(row):
    ensure_results()
    with RESULTS.open("a",newline="",encoding="utf-8") as f: csv.DictWriter(f,fieldnames=COLS).writerow({k:row.get(k) for k in COLS})
    with RUNS.open("a",encoding="utf-8") as f: f.write(json.dumps(row)+"\n")
