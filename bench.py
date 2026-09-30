"""Skore Optimizer - benchmark de antes e depois: mede o PC, guarda o histórico e compara medições."""
import ctypes
import html
import json
import os
import socket
import statistics
import tempfile
import time
import uuid

import psutil

import tweaks as T

FILE = os.path.join(T.STATE_DIR, "benchmarks.json")

# chave, nome, unidade, menor_é_melhor, casas decimais, ruído (%): variações menores que isso não contam como melhora/piora
METRICS = [
    ("sleep_avg", "Latência do timer (média)", "ms", True, 2, 15),
    ("sleep_p99", "Latência do timer (pior 1%)", "ms", True, 2, 20),
    ("cpu_score", "CPU (1 núcleo)", "Mit/s", False, 2, 12),
    ("cpu_idle", "CPU em repouso", "%", True, 1, 40),
    ("ram_used", "RAM em uso", "%", True, 1, 5),
    ("ram_free", "RAM livre", "GB", False, 2, 8),
    ("procs", "Processos em execução", "", True, 0, 3),
    ("services", "Serviços em execução", "", True, 0, 3),
    ("disk_write", "Disco (escrita sequencial)", "MB/s", False, 0, 30),
    ("ping", "Ping (Cloudflare)", "ms", True, 1, 30),
    ("jitter", "Jitter de rede", "ms", True, 2, 100),
    ("dns", "Resolução de DNS", "ms", True, 1, 40),
    ("boot", "Tempo do último boot", "s", True, 1, 15),
]
NOISE = 5.0   # (referência; cada métrica tem seu próprio limite acima)


# ---------------------------------------------------------------- medições
def sleep_latency(n=500):
    """Quanto tempo o Windows leva para acordar de um Sleep(1): reflete a resolução do timer."""
    sleep, pc, d = ctypes.WinDLL("kernel32").Sleep, time.perf_counter, []
    for _ in range(n):
        t = pc()
        sleep(1)
        d.append((pc() - t) * 1000)
    d.sort()
    return {"sleep_avg": statistics.fmean(d), "sleep_p99": d[int(0.99 * (n - 1))]}


def cpu_score(runs=3, iters=2_000_000):
    """Milhões de iterações por segundo de um laço fixo (melhor de 3): sensível a energia e throttling."""
    best = None
    for _ in range(runs):
        t = time.perf_counter()
        x = 0
        for i in range(iters):
            x = (x * 31 + i) & 0xFFFFFFFF
        dt = time.perf_counter() - t
        best = dt if best is None else min(best, dt)
    return {"cpu_score": iters / best / 1e6}


def system_load():
    cpu = psutil.cpu_percent(interval=3)
    vm = psutil.virtual_memory()
    try:
        services = sum(1 for s in psutil.win_service_iter() if s.status() == "running")
    except Exception:
        services = None
    return {"cpu_idle": cpu, "ram_used": vm.percent, "ram_free": vm.available / 1024 ** 3,
            "procs": len(psutil.pids()), "services": services}


def disk_write(mb=128):
    chunk, path = os.urandom(4 * 1024 * 1024), os.path.join(tempfile.gettempdir(), f"skore_bench_{uuid.uuid4().hex}.tmp")
    try:
        t = time.perf_counter()
        with open(path, "wb") as f:
            for _ in range(mb // 4):
                f.write(chunk)
            f.flush()
            os.fsync(f.fileno())
        return {"disk_write": mb / (time.perf_counter() - t)}
    except OSError:
        return {"disk_write": None}
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def network(host="1.1.1.1", port=443, n=10):
    times = []
    for _ in range(n):
        t = time.perf_counter()
        try:
            with socket.create_connection((host, port), timeout=2):
                times.append((time.perf_counter() - t) * 1000)
        except OSError:
            pass
        time.sleep(0.1)
    out = {"ping": statistics.fmean(times) if times else None,
           "jitter": statistics.pstdev(times) if len(times) > 1 else None}
    dns = []
    for _ in range(5):   # domínio inexistente e único: mede a resolução real, sem cache
        t = time.perf_counter()
        try:
            socket.getaddrinfo(f"sk{uuid.uuid4().hex[:12]}.com", 80)
        except OSError:
            pass
        dns.append((time.perf_counter() - t) * 1000)
    out["dns"] = statistics.fmean(dns) if len(dns) == 5 and max(dns) < 2000 else None
    return out


def boot_time():
    ps = ("$e=Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-Diagnostics-Performance/Operational';Id=100}"
          " -MaxEvents 1 -ErrorAction SilentlyContinue; if($e){([xml]$e.ToXml()).Event.EventData.Data |"
          " ?{$_.Name -eq 'BootTime'} | %{$_.'#text'}}")
    code, out = T.run(["powershell", "-NoProfile", "-Command", ps])
    try:
        return {"boot": int(out.strip().splitlines()[-1]) / 1000}
    except (ValueError, IndexError):
        return {"boot": None}


def run_all(label, progress=lambda pct, msg: None):
    """Executa todas as medições (~30 s) e grava no histórico. Retorna o registro."""
    steps = [("Latência do timer", sleep_latency), ("Desempenho da CPU", cpu_score), ("Carga do sistema (3 s)", system_load),
             ("Velocidade do disco", disk_write), ("Rede e DNS", network), ("Tempo de boot", boot_time)]
    metrics = {}
    for i, (name, fn) in enumerate(steps):
        progress(i / (len(steps) + 1), f"Medindo: {name}...")
        try:
            metrics.update(fn())
        except Exception:
            pass
    progress(len(steps) / (len(steps) + 1), "Lendo ajustes ativos...")
    active = []
    for t in T.TWEAKS:
        try:
            if t.reversible and t.available() and t.is_applied():
                active.append(t.id)
        except Exception:
            pass
    rec = {"label": label, "ts": time.strftime("%Y-%m-%d %H:%M"), "metrics": metrics, "active": active,
           "timer_ms": T.TIMER.query()[2]}
    runs = load()
    runs.append(rec)
    save(runs)
    progress(1.0, "Concluído.")
    return rec


# ---------------------------------------------------------------- histórico
def load():
    try:
        with open(FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def save(runs):
    os.makedirs(T.STATE_DIR, exist_ok=True)
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(runs, f, indent=1, ensure_ascii=False)


def compare(a, b):
    """Linhas [(nome, valor_a, valor_b, %, veredito, unidade)] — veredito: 'melhor', 'pior' ou 'igual'."""
    rows = []
    for key, name, unit, lower, dec, noise in METRICS:
        va, vb = a["metrics"].get(key), b["metrics"].get(key)
        if va is None or vb is None:
            rows.append((name, va, vb, None, "igual", unit, dec))
            continue
        pct = (vb - va) / va * 100 if va else 0.0
        if abs(pct) < noise:
            verdict = "igual"
        else:
            verdict = "melhor" if (pct < 0) == lower else "pior"
        rows.append((name, va, vb, pct, verdict, unit, dec))
    return rows


def fmt(v, dec, unit):
    return "--" if v is None else f"{v:.{dec}f}{(' ' + unit) if unit else ''}"


def report_html(a, b):
    """Relatório standalone (HTML) com a identidade SkoreloBoost, para entregar ao cliente."""
    rows = compare(a, b)
    better = sum(1 for r in rows if r[4] == "melhor")
    worse = sum(1 for r in rows if r[4] == "pior")
    added = [T.BY_ID[i].title for i in b.get("active", []) if i in T.BY_ID and i not in a.get("active", [])]
    color = {"melhor": "#78DC8C", "pior": "#F4485F", "igual": "#9B9BA3"}
    body = "".join(
        f"<tr><td>{html.escape(n)}</td><td>{fmt(va, d, u)}</td><td>{fmt(vb, d, u)}</td>"
        f"<td style='color:{color[v]};font-weight:700'>{'--' if p is None else f'{p:+.1f}%'}</td></tr>"
        for n, va, vb, p, v, u, d in rows)
    tweaks = "".join(f"<li>{html.escape(t)}</li>" for t in added) or "<li>Nenhum ajuste novo entre as medições.</li>"
    return f"""<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Relatório Skore Optimizer</title>
<style>body{{background:#07070A;color:#F5F5F7;font-family:Segoe UI,Arial,sans-serif;max-width:820px;margin:32px auto;padding:0 16px}}
h1{{color:#FFB100}}table{{width:100%;border-collapse:collapse}}td,th{{padding:10px;border-bottom:1px solid #222;text-align:left}}
th{{color:#FFB100}}.card{{background:#131316;border-radius:12px;padding:16px;margin:16px 0}}small{{color:#9B9BA3}}</style>
<h1>Relatório de otimização — SkoreloBoost</h1>
<small>Antes: {html.escape(a['label'])} ({a['ts']}) &nbsp;•&nbsp; Depois: {html.escape(b['label'])} ({b['ts']})</small>
<div class="card"><b>{better}</b> métrica(s) melhoraram, <b>{worse}</b> pioraram, o resto ficou estável ou dentro da variação normal entre medições.</div>
<table><tr><th>Métrica</th><th>Antes</th><th>Depois</th><th>Variação</th></tr>{body}</table>
<div class="card"><b>Ajustes aplicados entre as medições</b><ul>{tweaks}</ul></div>
<small>Medições feitas com o Skore Optimizer. Pequenas variações são normais; compare sempre com o PC nas mesmas condições.</small>
</html>"""
