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

def run_one(repo, threads, timeout):
    cfg = read_config(repo); binary = repo / "rundb"
    if not binary.exists(): raise FileNotFoundError(f"Missing {binary}; build DBx1000 first.")
    if not os.access(binary,os.X_OK): raise PermissionError("rundb is not executable; run chmod +x rundb")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+f"_t{threads}"
    stamp = datetime.now(timezone.utc).isoformat(); cmd=[str(binary),f"-t{threads}"]; logpath=LOGS/f"{run_id}.log"; samples=[]
    start=time.monotonic(); code=None; status="failed"; error=None
    try:
        with logpath.open("w",encoding="utf-8",errors="replace") as log:
            log.write(f"# command: {' '.join(cmd)}\n# config: {json.dumps(cfg)}\n# started_utc: {stamp}\n\n"); log.flush()
            proc=subprocess.Popen(cmd,cwd=repo,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            mon=threading.Thread(target=sample,args=(proc,samples),daemon=True); mon.start()
            try:
                code=proc.wait(timeout=int(timeout)); status="completed" if code==0 else "failed"
            except subprocess.TimeoutExpired:
                proc.terminate()
                try: proc.wait(timeout=5)
                except subprocess.TimeoutExpired: proc.kill(); proc.wait()
                status="timeout"; error=f"Timed out after {timeout} seconds."
            mon.join(timeout=2)
    except Exception as e: error=str(e)
    duration=round(time.monotonic()-start,3); parsed=parse_log(logpath.read_text(errors="replace") if logpath.exists() else "")
    row={"run_id":run_id,"timestamp_utc":stamp,"threads":threads,"cc_alg":cfg.get("CC_ALG","unknown"),"index_struct":cfg.get("INDEX_STRUCT","unknown"),"workload":cfg.get("WORKLOAD","unknown"),"status":status,"exit_code":code,"duration_seconds":duration,**{k:parsed[k] for k in ("completed_txns","aborts","reported_runtime_seconds","throughput_txn_s")},"cpu_percent_mean":round(sum(x["cpu"] for x in samples)/len(samples),2) if samples else None,"rss_mb_peak":round(max((x["rss"] for x in samples),default=0),2) if samples else None,"context_switches_voluntary":max((x["vol"] for x in samples),default=None),"context_switches_involuntary":max((x["invol"] for x in samples),default=None),"git_commit":git_commit(repo),"log_file":str(logpath.relative_to(APP_DIR)),"command":" ".join(cmd)}
    save(row)
    (LOGS/f"{run_id}.json").write_text(json.dumps({"result":row,"error":error,"samples":samples,"config":cfg,"platform":platform.platform()},indent=2))
    return row,error,logpath

def main():
    st.set_page_config(page_title="DBx1000 Control Center",page_icon="🧪",layout="wide")
    st.title("🧪 DBx1000 Control Center")
    st.caption("DBMS benchmarking + OS process monitoring")
    st.info("This GUI runs the current compiled `rundb` binary and reads `config.h`. It does not silently change C++ settings or rebuild your database.")
    with st.sidebar:
        st.header("Repository")
        repo=Path(st.text_input("DBx1000 path",os.environ.get("DBX1000_REPO",str(Path.home()/"DBx1000")))).expanduser()
        st.caption("Run Streamlit inside Ubuntu/WSL and use a Linux path.")
        st.header("Experiment")
        threads=st.select_slider("Worker threads",[1,2,4,8,16,32],value=2)
        timeout=st.number_input("Timeout (seconds)",min_value=10,max_value=7200,value=900,step=30)
        launch=st.button("▶ Run experiment",type="primary",use_container_width=True)
    exists=repo.is_dir(); cfg=read_config(repo) if exists else {}
    a,b,c,d=st.columns(4)
    a.metric("Repository","Found" if exists else "Not found")
    b.metric("CC algorithm",cfg.get("CC_ALG","—"))
    c.metric("Index",cfg.get("INDEX_STRUCT","—"))
    d.metric("Workload",cfg.get("WORKLOAD","—"))
    if exists: st.caption(f"Git commit: `{git_commit(repo)}` • `{repo}`")
    else: st.warning("Enter the path to your DBx1000 checkout.")
    if psutil is None: st.warning("OS process metrics need psutil. Install dependencies using requirements.txt.")
    if launch:
        if not exists: st.error("Repository path does not exist.")
        else:
            with st.spinner(f"Running DBx1000 with {threads} worker threads…"):
                try:
                    row,error,logpath=run_one(repo,int(threads),int(timeout))
                    if row["status"]=="completed": st.success(f"Run completed: {row['run_id']}")
                    else: st.error(f"Run status: {row['status']}; inspect its log.")
                    if error: st.warning(error)
                    x,y,z,w=st.columns(4)
                    x.metric("Completed txns",f"{int(row['completed_txns']):,}" if pd.notna(row["completed_txns"]) else "Not parsed")
                    y.metric("Aborts",f"{int(row['aborts']):,}" if pd.notna(row["aborts"]) else "Not parsed")
                    z.metric("Throughput",f"{row['throughput_txn_s']:,.1f} txn/s" if pd.notna(row["throughput_txn_s"]) else "Not parsed")
                    w.metric("Mean CPU",f"{row['cpu_percent_mean']}%" if row["cpu_percent_mean"] is not None else "Unavailable")
                    with st.expander("Raw DBx1000 log"): st.code(logpath.read_text(errors="replace")[-20000:])
                except Exception as e: st.error(str(e))
    st.divider(); st.subheader("Run history")
    if RESULTS.exists():
        df=pd.read_csv(RESULTS)
    else: df=pd.DataFrame(columns=COLS)
    if df.empty: st.write("No runs yet. Launch a benchmark to populate this table.")
    else:
        for col in ("threads","completed_txns","aborts","throughput_txn_s","cpu_percent_mean","rss_mb_peak"):
            if col in df: df[col]=pd.to_numeric(df[col],errors="coerce")
        ok=df[df.status=="completed"]
        x,y,z,w=st.columns(4); x.metric("Recorded runs",len(df)); y.metric("Completed",len(ok)); z.metric("Failed / timeout",int(df.status.isin(["failed","timeout"]).sum())); w.metric("Peak throughput",f"{ok.throughput_txn_s.max():,.1f}" if not ok.empty and ok.throughput_txn_s.notna().any() else "—")
        st.dataframe(df.sort_values("timestamp_utc",ascending=False),use_container_width=True,hide_index=True)
        valid=ok.dropna(subset=["throughput_txn_s"])
        if not valid.empty:
            st.subheader("Throughput by thread count")
            st.line_chart(valid.groupby("threads")["throughput_txn_s"].mean())
            res=valid.dropna(subset=["cpu_percent_mean","rss_mb_peak"])
            if not res.empty:
                st.subheader("OS resource measurements")
                st.bar_chart(res.groupby("threads")[["cpu_percent_mean","rss_mb_peak"]].mean())
        st.download_button("⬇ Export CSV",df.to_csv(index=False).encode(),file_name="dbx1000_results.csv",mime="text/csv")
    with st.expander("Project concepts"):
        st.markdown("- **DBMS:** transactions, concurrency control, indexing, aborts and throughput.\n- **OS:** worker-process CPU, resident memory and context-switch counters.\n- **Systems:** subprocess execution, timeouts, logs, metadata and reproducible experiments.\n\nResource sampling is best-effort; very short runs may not produce samples. Failed runs are retained but should not be treated as valid performance measurements.")

         st.divider()
    st.header("SQL Experiment Explorer")

    st.caption(
        "Query the SQLite database containing benchmark results."
    )

    query = st.text_area(
        "SQL query",
        value="""
SELECT
    e.algorithm,
    e.thread_count,
    m.throughput
FROM experiments e
JOIN metrics m ON e.run_id = m.run_id
WHERE e.status = 'completed'
ORDER BY m.throughput DESC
""",
        height=160,
    )

    if st.button("Execute SQL"):
        try:
            results = run_query(query)

            if results:
                st.dataframe(results, use_container_width=True)
            else:
                st.info("The query returned no rows.")

        except Exception as exc:
            st.error(f"Query failed: {exc}")