"""Skore Optimizer - otimizador de Windows focado em gaming."""
import ctypes
import json
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
from tkinter import messagebox

from PIL import Image

import customtkinter as ctk
import psutil

import bench as BM
import games as G
import tweaks as T
import winget_store as W

APP_NAME = "Skore Optimizer"
ACCENT, ACCENT_H = "#FFB100", "#C98600"   # dourado SkoreloBoost
BTN_TXT = "#07070A"
DANGER, OK, MUTE = "#F4485F", "#78DC8C", "#9B9BA3"
BG, CARD, CARD2 = "#07070A", "#131316", "#1d1d22"
RISK = {"safe": ("Seguro", "#2f9e63"), "medium": ("Moderado", "#d9922b")}

ctk.set_appearance_mode("dark")


def asset(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", name)


def load_img(name, width):
    im = Image.open(asset(name))
    return ctk.CTkImage(light_image=im, dark_image=im, size=(width, round(width * im.height / im.width)))


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def elevate():
    """Reabre o programa com privilégios de administrador."""
    params = " ".join(f'"{a}"' for a in sys.argv)
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, " ".join(f'"{a}"' for a in sys.argv[1:])
    else:
        exe = sys.executable
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    if rc <= 32:   # o Windows recusou ou a pessoa cancelou o pedido de administrador
        ctypes.windll.user32.MessageBoxW(
            0, "O Skore Optimizer precisa de permissão de administrador para aplicar os ajustes.\n\n"
               "Abra de novo e clique em \"Sim\" no aviso do Windows.", APP_NAME, 0x30)


def log_erro(texto):
    """Grava o erro em %APPDATA%/SkoreOptimizer/erro.log e devolve o caminho (ou None)."""
    try:
        pasta = os.path.join(os.environ.get("APPDATA", "."), "SkoreOptimizer")
        os.makedirs(pasta, exist_ok=True)
        caminho = os.path.join(pasta, "erro.log")
        with open(caminho, "a", encoding="utf-8") as f:
            f.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} | Python {sys.version.split()[0]} | "
                    f"{'exe' if getattr(sys, 'frozen', False) else 'codigo-fonte'} =====\n{texto}\n")
        return caminho
    except OSError:
        return None


def mostrar_erro_fatal(texto):
    """O app é 'sem console': sem isto, um erro na abertura faria o programa sumir sem aviso."""
    caminho = log_erro(texto)
    ultima = (texto.strip().splitlines() or ["erro desconhecido"])[-1]
    msg = (f"O Skore Optimizer não conseguiu abrir.\n\n{ultima}\n\n"
           + (f"Os detalhes foram salvos em:\n{caminho}\n\nMande esse arquivo para o suporte." if caminho else ""))
    ctypes.windll.user32.MessageBoxW(0, msg, APP_NAME + " - erro", 0x10)


class App(ctk.CTk):
    def __init__(self):
        super().__init__(fg_color=BG)
        self.title(f"{APP_NAME} — by SkoreloBoost")
        self.geometry("1140x800")
        self.minsize(960, 640)
        self.q = queue.Queue()
        self.switches = {}   # id -> (switch, badge)
        self.busy = False

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()

        self.main = ctk.CTkFrame(self, fg_color="transparent")
        self.main.grid(row=0, column=1, sticky="nsew", padx=(0, 16), pady=16)
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_rowconfigure(0, weight=1)

        self.pages = {
            "Painel": self._page_dashboard(),
            "Benchmark": self._page_bench(),
            "Gaming": self._page_tweaks("gaming", "Otimizações para Jogos",
                                        "Menos latência, mais FPS estável e input preciso."),
            "Geral": self._page_tweaks("geral", "Otimizações Gerais",
                                       "Sistema mais leve, rápido e privado no dia a dia."),
            "Jogos": self._page_games(),
            "GPU": self._page_gpu(),
            "Avançado": self._page_advanced(),
            "Privacidade": self._page_tweaks("privacidade", "Privacidade e IA",
                                             "Desliga Copilot, Recall, histórico de atividades e coleta de dados."),
            "Serviços": self._page_tweaks("servicos", "Serviços do Windows",
                                          "Desativa serviços que quase ninguém usa. Reversível: o app guarda o estado original."),
            "Limpeza": self._page_tweaks("limpeza", "Limpeza", "Ações pontuais para liberar espaço e corrigir DNS."),
            "Debloat": self._page_debloat(),
            "Inicialização": self._page_startup(),
            "Apps": self._page_apps(),
            "Ferramentas": self._page_tools(),
            "Perfis": self._page_profiles(),
        }
        self.log = ctk.CTkTextbox(self, height=110, fg_color=CARD, font=("Consolas", 12), corner_radius=10)
        self.log.grid(row=1, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 16))
        self.log.configure(state="disabled")

        self.after(250, self._set_icon)
        self._gpu_poll()
        self.show("Painel")
        self.say(f"{APP_NAME} iniciado." + ("" if is_admin() else
                 " ATENÇÃO: sem privilégios de administrador — ajustes do sistema (HKLM) vão falhar."))
        self.refresh_status()
        self._scan_startup()
        threading.Thread(target=self._load_hw, daemon=True).start()
        self.after(100, self._pump)
        self.after(1000, self._tick)

    def _set_icon(self):
        try:
            self.iconbitmap(asset("icon.ico"))
        except Exception:
            pass

    # ------------------------------------------------------------ infra
    def _pump(self):
        try:
            while True:
                self.q.get_nowait()()
        except queue.Empty:
            pass
        self.after(100, self._pump)

    def report_callback_exception(self, exc, val, tb):
        log_erro("".join(traceback.format_exception(exc, val, tb)))
        try:
            self.say("✖ Erro inesperado (detalhes em %APPDATA%\\SkoreOptimizer\\erro.log).")
        except Exception:
            pass

    def say(self, msg):
        def w():
            self.log.configure(state="normal")
            self.log.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        self.q.put(w)

    def show(self, name):
        for n, p in self.pages.items():
            p.grid_forget()
            self.nav[n].configure(fg_color="transparent")
        self.pages[name].grid(row=0, column=0, sticky="nsew")
        self.nav[name].configure(fg_color=CARD2)

    def refresh_status(self):
        """Lê o estado real de cada ajuste em segundo plano (alguns usam PowerShell) e atualiza os interruptores."""
        if getattr(self, "_refreshing", False):
            self._again = True
            return
        self._refreshing = True

        def job():
            res = {}
            for tid in list(self.switches):
                try:
                    res[tid] = T.BY_ID[tid].is_applied()
                except Exception:
                    res[tid] = False

            def ui():
                for tid, on in res.items():
                    sw, badge = self.switches[tid]
                    (sw.select if on else sw.deselect)()
                    badge.configure(text="ATIVO" if on else "inativo", text_color=OK if on else MUTE)
                self._refreshing = False
                if getattr(self, "_again", False):
                    self._again = False
                    self.refresh_status()
            self.q.put(ui)
        threading.Thread(target=job, daemon=True).start()

    # ------------------------------------------------------------ UI
    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=210, fg_color=CARD, corner_radius=0)
        sb.grid(row=0, column=0, sticky="nsw")
        sb.grid_propagate(False)
        ctk.CTkLabel(sb, text="", image=load_img("logo.png", 96)).pack(pady=(18, 4))
        ctk.CTkLabel(sb, text="OPTIMIZER", font=("Segoe UI", 15, "bold"), text_color=ACCENT).pack()
        ctk.CTkLabel(sb, text="by SkoreloBoost", font=("Segoe UI", 11), text_color=MUTE).pack(pady=(0, 10))
        ctk.CTkLabel(sb, text="Admin: " + ("sim ✔" if is_admin() else "não ✖"), font=("Segoe UI", 11),
                     text_color=OK if is_admin() else DANGER).pack(side="bottom", pady=10)
        nav = ctk.CTkScrollableFrame(sb, fg_color="transparent", width=170)
        nav.pack(fill="both", expand=True, padx=2)
        self.nav = {}
        items = [("Painel", "🖥"), ("Benchmark", "📊"), ("Gaming", "🎮"), ("Jogos", "🕹"), ("GPU", "🟩"), ("Avançado", "⚡"), ("Geral", "⚙"),
                 ("Privacidade", "🔒"), ("Serviços", "🛠"), ("Limpeza", "🧹"), ("Debloat", "🗑"),
                 ("Inicialização", "🚀"), ("Apps", "📦"), ("Ferramentas", "🧰"), ("Perfis", "🛡")]
        for name, icon in items:
            b = ctk.CTkButton(nav, text=f"  {icon}   {name}", anchor="w", height=36, corner_radius=8,
                              fg_color="transparent", hover_color=CARD2, font=("Segoe UI", 14),
                              command=lambda n=name: self.show(n))
            b.pack(fill="x", padx=6, pady=1)
            self.nav[name] = b

    def _title(self, parent, title, sub):
        ctk.CTkLabel(parent, text=title, font=("Segoe UI", 26, "bold"), anchor="w").pack(fill="x", pady=(10, 0), padx=6)
        ctk.CTkLabel(parent, text=sub, font=("Segoe UI", 13), text_color=MUTE, anchor="w").pack(fill="x", padx=6, pady=(0, 10))

    def _page_dashboard(self):
        p = ctk.CTkFrame(self.main, fg_color="transparent")
        self._title(p, "Painel", "Visão geral do seu PC em tempo real.")
        top = ctk.CTkFrame(p, fg_color=CARD, corner_radius=12)
        top.pack(fill="x", pady=6)
        ctk.CTkLabel(top, text="", image=load_img("hero-team.png", 260)).pack(side="right", padx=14, pady=8)
        self.hw_label = ctk.CTkLabel(top, text="Detectando hardware...", justify="left", anchor="w",
                                     font=("Segoe UI", 14), padx=18, pady=16)
        self.hw_label.pack(side="left", fill="x", expand=True)
        grid = ctk.CTkFrame(p, fg_color="transparent")
        grid.pack(fill="x", pady=6)
        self.meters = {}
        for i, key in enumerate(["CPU", "RAM", "Disco C:"]):
            grid.grid_columnconfigure(i, weight=1, uniform="m")
            card = ctk.CTkFrame(grid, fg_color=CARD, corner_radius=12)
            card.grid(row=0, column=i, padx=6, sticky="ew")
            ctk.CTkLabel(card, text=key, text_color=MUTE).pack(pady=(14, 0))
            val = ctk.CTkLabel(card, text="--%", font=("Segoe UI", 30, "bold"))
            val.pack()
            bar = ctk.CTkProgressBar(card, progress_color=ACCENT, height=8)
            bar.set(0)
            bar.pack(fill="x", padx=18, pady=(4, 16))
            self.meters[key] = (val, bar)
        ctk.CTkLabel(p, text="Dica: use a aba Perfis para aplicar o pacote Gaming com um clique. "
                             "Tudo pode ser revertido.", text_color=MUTE, anchor="w").pack(fill="x", pady=14, padx=6)
        return p

    def _page_tweaks(self, category, title, sub):
        p = ctk.CTkFrame(self.main, fg_color="transparent")
        self._title(p, title, sub)
        sc = ctk.CTkScrollableFrame(p, fg_color="transparent")
        sc.pack(fill="both", expand=True)
        self._tweak_rows(sc, category)
        return p

    def _tweak_rows(self, sc, category):
        for tw in [t for t in T.TWEAKS if t.category == category and t.available()]:
            row = ctk.CTkFrame(sc, fg_color=CARD, corner_radius=12)
            row.pack(fill="x", pady=5, padx=2)
            row.grid_columnconfigure(0, weight=1)
            head = ctk.CTkFrame(row, fg_color="transparent")
            head.grid(row=0, column=0, sticky="w", padx=16, pady=(12, 0))
            ctk.CTkLabel(head, text=tw.title, font=("Segoe UI", 14, "bold")).pack(side="left")
            rtxt, rcol = RISK[tw.risk]
            ctk.CTkLabel(head, text=f" {rtxt} ", fg_color=rcol, corner_radius=6, font=("Segoe UI", 10, "bold"),
                         text_color="white").pack(side="left", padx=8)
            if tw.reboot:
                ctk.CTkLabel(head, text=" reiniciar ", fg_color=CARD2, corner_radius=6, font=("Segoe UI", 10),
                             text_color="#b0b7c3").pack(side="left")
            ctk.CTkLabel(row, text=tw.desc, wraplength=640, justify="left", anchor="w", text_color="#9aa3b2",
                         font=("Segoe UI", 12)).grid(row=1, column=0, sticky="w", padx=16, pady=(2, 12))
            if tw.reversible:
                right = ctk.CTkFrame(row, fg_color="transparent")
                right.grid(row=0, column=1, rowspan=2, padx=16)
                badge = ctk.CTkLabel(right, text="...", font=("Segoe UI", 11, "bold"), width=60)
                badge.pack(side="left", padx=8)
                sw = ctk.CTkSwitch(right, text="", progress_color=ACCENT, width=46,
                                   command=lambda t=tw: self._toggle(t))
                sw.pack(side="left")
                self.switches[tw.id] = (sw, badge)
            else:
                ctk.CTkButton(row, text="Executar", width=100, fg_color=ACCENT, hover_color=ACCENT_H, text_color=BTN_TXT,
                              command=lambda t=tw: self._run_action(t)).grid(row=0, column=1, rowspan=2, padx=16)

    def _page_gpu(self):
        p = ctk.CTkFrame(self.main, fg_color="transparent")
        self._title(p, "GPU — NVIDIA / AMD", "Monitor da placa, ajustes de driver e jogos forçados na GPU dedicada.")
        sc = ctk.CTkScrollableFrame(p, fg_color="transparent")
        sc.pack(fill="both", expand=True)

        # --- monitor ao vivo
        card = ctk.CTkFrame(sc, fg_color=CARD, corner_radius=12)
        card.pack(fill="x", pady=5, padx=2)
        self.gpu_name = ctk.CTkLabel(card, text="Procurando placa de vídeo...", font=("Segoe UI", 15, "bold"), anchor="w")
        self.gpu_name.pack(fill="x", padx=16, pady=(14, 0))
        self.gpu_sub = ctk.CTkLabel(card, text="", text_color=MUTE, anchor="w")
        self.gpu_sub.pack(fill="x", padx=16)
        grid = ctk.CTkFrame(card, fg_color="transparent")
        grid.pack(fill="x", padx=10, pady=(8, 14))
        self.gpu_meters = {}
        for i, key in enumerate(["Uso", "VRAM", "Temp", "Consumo"]):
            grid.grid_columnconfigure(i, weight=1, uniform="g")
            box = ctk.CTkFrame(grid, fg_color=CARD2, corner_radius=10)
            box.grid(row=0, column=i, padx=5, sticky="ew")
            ctk.CTkLabel(box, text=key, text_color=MUTE, font=("Segoe UI", 11)).pack(pady=(8, 0))
            val = ctk.CTkLabel(box, text="--", font=("Segoe UI", 20, "bold"))
            val.pack()
            bar = ctk.CTkProgressBar(box, progress_color=ACCENT, height=6)
            bar.set(0)
            bar.pack(fill="x", padx=14, pady=(2, 10))
            self.gpu_meters[key] = (val, bar)

        # --- ajustes
        self._tweak_rows(sc, "gpu")

        # --- jogos na GPU dedicada
        ctk.CTkLabel(sc, text="Jogos na GPU dedicada", font=("Segoe UI", 18, "bold"), anchor="w").pack(
            fill="x", padx=6, pady=(16, 0))
        ctk.CTkLabel(sc, text="Em notebooks com placa dupla (Intel + NVIDIA/AMD), força o jogo a usar a placa dedicada "
                              "(igual a Configurações > Sistema > Vídeo > Gráficos).",
                     text_color=MUTE, anchor="w", wraplength=700, justify="left").pack(fill="x", padx=6)
        ctk.CTkButton(sc, text="➕ Adicionar jogo (.exe)", fg_color=ACCENT, hover_color=ACCENT_H, text_color=BTN_TXT,
                      width=180, command=self._add_game).pack(anchor="w", padx=6, pady=8)
        self.game_list = ctk.CTkFrame(sc, fg_color="transparent")
        self.game_list.pack(fill="x")
        self._refresh_games()

        # --- guias por fabricante (só do que o PC tem; se nada for detectado, mostra os dois)
        vend = T.gpu_vendors()
        if "NVIDIA" in vend or not (vend & {"NVIDIA", "AMD"}):
            self._guide(sc, "Configurações recomendadas no Painel NVIDIA", [
                "Gerenciar configurações 3D > Modo de gerenciamento de energia: Preferir desempenho máximo",
                "Baixa Latência: Ativado (ou Ultra em jogos competitivos sem limite de FPS)",
                "Otimização de threads: Ativado  •  Qualidade de filtragem de textura: Alto desempenho",
                "Tamanho do cache de shader: Ilimitado (ou 10 GB)  •  Sincronização vertical: Desativada",
                "Ajustar tamanho e posição da área de trabalho > Escala feita por: GPU (opcional)"],
                "Abrir Painel de Controle NVIDIA", self._open_nv_panel)
        if "AMD" in vend or not (vend & {"NVIDIA", "AMD"}):
            self._guide(sc, "Configurações recomendadas no AMD Software (Radeon)", [
                "Jogos > Gráficos: Radeon Anti-Lag Ativado (o Anti-Lag+ antigo foi retirado pela AMD após causar bans no CS2)",
                "Radeon Chill: Desativado  •  Radeon Boost: Desativado (reduz a qualidade ao mexer a câmera)",
                "Aguardar atualização vertical: Desativado (use Enhanced Sync só se houver tearing)",
                "Modo de tesselação: Otimizado pela AMD  •  Qualidade de filtragem de textura: Desempenho",
                "Otimização do formato de superfície: Ativado  •  Cache de shader: Otimizado pela AMD",
                "FreeSync: Ativado no AMD Software e no menu do monitor  •  Evite OC/undervolt se houver instabilidade"],
                "Abrir AMD Software", self._open_radeon)
        return p

    def _guide(self, sc, title, tips, btn_text, btn_cmd):
        ctk.CTkLabel(sc, text=title, font=("Segoe UI", 18, "bold"), anchor="w").pack(fill="x", padx=6, pady=(18, 0))
        guide = ctk.CTkFrame(sc, fg_color=CARD, corner_radius=12)
        guide.pack(fill="x", pady=6, padx=2)
        for t in tips:
            ctk.CTkLabel(guide, text="•  " + t, anchor="w", justify="left", wraplength=700,
                         text_color="#c9c9d1").pack(fill="x", padx=16, pady=3)
        ctk.CTkButton(guide, text=btn_text, fg_color=CARD2, hover_color="#2b2b32",
                      command=btn_cmd).pack(anchor="w", padx=16, pady=(6, 14))

    def _open_radeon(self):
        if not T.open_radeon_software():
            self.say("✖ Não encontrei o AMD Software (Adrenalin). Instale o driver da AMD.")

    def _open_nv_panel(self):
        if not T.open_nvidia_panel():
            self.say("✖ Não consegui abrir o Painel NVIDIA (instale-o pela Microsoft Store).")

    def _refresh_games(self):
        for w in self.game_list.winfo_children():
            w.destroy()
        games = T.gpu_pref_list()
        if not games:
            ctk.CTkLabel(self.game_list, text="Nenhum jogo configurado ainda.", text_color=MUTE).pack(anchor="w", padx=6)
        for exe, pref in games:
            row = ctk.CTkFrame(self.game_list, fg_color=CARD, corner_radius=10)
            row.pack(fill="x", pady=3, padx=2)
            box = ctk.CTkFrame(row, fg_color="transparent")
            box.pack(side="left", padx=16, pady=8)
            ctk.CTkLabel(box, text=os.path.basename(exe), font=("Segoe UI", 13, "bold"), anchor="w").pack(anchor="w")
            ctk.CTkLabel(box, text=f"{T.GPU_LABEL.get(pref, pref)}  •  {exe[:80]}", text_color=MUTE,
                         font=("Segoe UI", 11), anchor="w").pack(anchor="w")
            ctk.CTkButton(row, text="Remover", width=80, fg_color=CARD2, hover_color="#2b2b32",
                          command=lambda e=exe: self._del_game(e)).pack(side="right", padx=8)
            if pref != "2":
                ctk.CTkButton(row, text="Usar GPU dedicada", width=140, fg_color=ACCENT, hover_color=ACCENT_H,
                              text_color=BTN_TXT, command=lambda e=exe: self._set_game(e)).pack(side="right")

    def _add_game(self):
        from tkinter import filedialog
        f = filedialog.askopenfilename(title="Escolha o .exe do jogo", filetypes=[("Executável", "*.exe")])
        if f:
            self._set_game(os.path.normpath(f))

    def _set_game(self, exe):
        try:
            T.gpu_pref_set(exe)
            self.say(f"✔ {os.path.basename(exe)} agora usa a GPU dedicada (reinicie o jogo).")
        except Exception as e:
            self.say(f"✖ {exe}: {e}")
        self._refresh_games()

    def _del_game(self, exe):
        T.gpu_pref_remove(exe)
        self.say(f"↩ {os.path.basename(exe)} voltou para o padrão do Windows.")
        self._refresh_games()

    def _gpu_poll(self):
        if not getattr(self, "_gpu_busy", False):
            self._gpu_busy = True

            def job():
                st = T.gpu_stats()
                if st is None and "AMD" in T.gpu_vendors():
                    st = T.gpu_stats_generic()
                self.q.put(lambda: self._gpu_update(st))
            self._bg(job)
        self.after(2000, self._gpu_poll)

    def _gpu_update(self, st):
        self._gpu_busy = False
        if not st:
            self.gpu_name.configure(text="GPU dedicada não detectada")
            self.gpu_sub.configure(text="Instale o driver da NVIDIA ou da AMD para ver o monitor e usar os ajustes desta aba.")
            return
        num = lambda v, fmt: fmt.format(v) if v is not None else "--"
        self.gpu_name.configure(text=f"🟩 {st['name']}")
        extra = "" if st["clock"] is None else f"  •  Clock {st['clock']:.0f} MHz  •  Estado {st['pstate']}"
        self.gpu_sub.configure(text=f"Driver {st['driver']}{extra}" +
                               ("  •  Monitor via contadores do Windows (sem temperatura/consumo)" if st.get("generic") else ""))
        pct_mem = (st["mem_used"] / st["mem_total"] * 100) if st["mem_total"] else 0
        power = st["power"]
        vals = {"Uso": (num(st["util"], "{:.0f}%"), st["util"] or 0),
                "VRAM": (num(st["mem_used"], "{:.0f} MB"), pct_mem),
                "Temp": (num(st["temp"], "{:.0f}°C"), min(st["temp"] or 0, 100)),
                "Consumo": (num(power, "{:.0f} W"), min((power or 0) / 1.2, 100))}
        for k, (txt, pct) in vals.items():
            lbl, bar = self.gpu_meters[k]
            lbl.configure(text=txt)
            bar.set(max(0, min(pct, 100)) / 100)

    def _page_debloat(self):
        p = ctk.CTkFrame(self.main, fg_color="transparent")
        self._title(p, "Debloat de Apps da Microsoft",
                    "Remove apps pré-instalados e promovidos (só para o seu usuário). Reinstale pela Microsoft Store.")
        bar = ctk.CTkFrame(p, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 6))
        ctk.CTkButton(bar, text="🔍 Analisar apps", width=140, fg_color=CARD2, hover_color="#2b303b",
                      command=self._scan_bloat).pack(side="left", padx=(0, 8))
        ctk.CTkButton(bar, text="Marcar todos", width=110, fg_color=CARD2, hover_color="#2b303b",
                      command=lambda: self._mark_bloat(True)).pack(side="left", padx=(0, 8))
        ctk.CTkButton(bar, text="Desmarcar", width=100, fg_color=CARD2, hover_color="#2b303b",
                      command=lambda: self._mark_bloat(False)).pack(side="left")
        ctk.CTkButton(bar, text="🗑 Remover selecionados", fg_color=ACCENT, hover_color=ACCENT_H, text_color=BTN_TXT,
                      command=self._remove_bloat).pack(side="right")
        self.bloat_list = ctk.CTkScrollableFrame(p, fg_color="transparent")
        self.bloat_list.pack(fill="both", expand=True)
        self.bloat_checks = []   # (checkbox, full_name, friendly)
        ctk.CTkLabel(self.bloat_list, text="Clique em 'Analisar apps' para listar o que pode ser removido.",
                     text_color=MUTE).pack(pady=30)
        ctk.CTkLabel(p, text="Protegidos (nunca listados): Microsoft Store, Calculadora, Fotos, Terminal, "
                             "Xbox e Game Bar.", text_color=MUTE, anchor="w").pack(fill="x", padx=6, pady=(6, 0))
        return p

    def _scan_bloat(self):
        self.say("Analisando apps instalados...")

        def job():
            apps = T.list_bloat()

            def ui():
                for w in self.bloat_list.winfo_children():
                    w.destroy()
                self.bloat_checks.clear()
                if not apps:
                    ctk.CTkLabel(self.bloat_list, text="Nenhum app removível encontrado. 🎉",
                                 text_color=MUTE).pack(pady=30)
                for friendly, desc, full in apps:
                    row = ctk.CTkFrame(self.bloat_list, fg_color=CARD, corner_radius=10)
                    row.pack(fill="x", pady=4, padx=2)
                    cb = ctk.CTkCheckBox(row, text=f"{friendly}", font=("Segoe UI", 14, "bold"),
                                         fg_color=ACCENT, hover_color=ACCENT_H, checkmark_color=BTN_TXT)
                    cb.pack(side="left", padx=16, pady=12)
                    ctk.CTkLabel(row, text=desc, text_color="#9aa3b2").pack(side="left", padx=6)
                    self.bloat_checks.append((cb, full, friendly))
                self.say(f"{len(apps)} app(s) removível(is) encontrado(s).")
            self.q.put(ui)
        self._bg(job)

    def _mark_bloat(self, on):
        for cb, _, _ in self.bloat_checks:
            (cb.select if on else cb.deselect)()

    def _remove_bloat(self):
        sel = [(f, n) for cb, f, n in self.bloat_checks if cb.get()]
        if not sel:
            self.say("Nenhum app selecionado.")
            return
        nl = chr(10)
        names = nl.join(n for _, n in sel)
        msg = f"Remover {len(sel)} app(s) selecionado(s)?{nl}{nl}{names}{nl}{nl}Para reinstalar, use a Microsoft Store."
        if not messagebox.askyesno("Remover apps", msg):
            return

        def job():
            for full, name in sel:
                try:
                    T.remove_app(full)
                    self.say(f"  ✔ Removido: {name}")
                except Exception as e:
                    self.say(f"  ✖ {name}: {e}")
            self.say("Debloat concluído.")
            self.q.put(self._scan_bloat)
        self._bg(job)

    def _page_startup(self):
        p = ctk.CTkFrame(self.main, fg_color="transparent")
        self._title(p, "Programas de Inicialização",
                    "Menos programas ao ligar = boot mais rápido e mais RAM livre. Ligado = abre com o Windows.")
        ctk.CTkButton(p, text="🔄 Atualizar lista", width=140, fg_color=CARD2, hover_color="#2b303b",
                      command=self._scan_startup).pack(anchor="w", pady=(0, 6))
        self.startup_list = ctk.CTkScrollableFrame(p, fg_color="transparent")
        self.startup_list.pack(fill="both", expand=True)
        return p

    def _scan_startup(self):
        def job():
            items = T.list_startup()

            def ui():
                for w in self.startup_list.winfo_children():
                    w.destroy()
                for it in items:
                    row = ctk.CTkFrame(self.startup_list, fg_color=CARD, corner_radius=10)
                    row.pack(fill="x", pady=4, padx=2)
                    box = ctk.CTkFrame(row, fg_color="transparent")
                    box.pack(side="left", padx=16, pady=10)
                    ctk.CTkLabel(box, text=it["name"], font=("Segoe UI", 14, "bold"), anchor="w").pack(anchor="w")
                    ctk.CTkLabel(box, text=it["command"][:90], text_color=MUTE, font=("Segoe UI", 11),
                                 anchor="w").pack(anchor="w")
                    sw = ctk.CTkSwitch(row, text="", progress_color=ACCENT, width=46)
                    sw.pack(side="right", padx=16)
                    if it["enabled"]:
                        sw.select()
                    sw.configure(command=lambda i=it, s=sw: self._toggle_startup(i, s))
            self.q.put(ui)
        self._bg(job)

    def _toggle_startup(self, it, sw):
        on = bool(sw.get())

        def job():
            try:
                T.set_startup(it, on)
                self.say(("✔ Ativado na inicialização: " if on else "↩ Removido da inicialização: ") + it["name"])
            except Exception as e:
                self.say(f"✖ {it['name']}: {e}")
        self._bg(job)

    # ------------------------------------------------------------ Jogos (ajustes por jogo)
    def _page_games(self):
        p = ctk.CTkFrame(self.main, fg_color="transparent")
        self._title(p, "Ajustes por Jogo", "Aplica GPU dedicada, tela cheia exclusiva e prioridade de CPU só no executável de cada jogo.")
        ctk.CTkButton(p, text="🔍 Detectar jogos", width=150, fg_color=CARD2, hover_color="#2b2b32",
                      command=self._scan_games).pack(anchor="w", pady=(0, 6))
        sc = ctk.CTkScrollableFrame(p, fg_color="transparent")
        sc.pack(fill="both", expand=True)
        self.game_cards = {}
        for g in G.GAMES:
            card = ctk.CTkFrame(sc, fg_color=CARD, corner_radius=12)
            card.pack(fill="x", pady=5, padx=2)
            head = ctk.CTkFrame(card, fg_color="transparent")
            head.pack(fill="x", padx=16, pady=(12, 0))
            ctk.CTkLabel(head, text=g["name"], font=("Segoe UI", 16, "bold")).pack(side="left")
            status = ctk.CTkLabel(head, text="procurando...", text_color=MUTE, font=("Segoe UI", 11))
            status.pack(side="left", padx=10)
            ctk.CTkButton(head, text="Localizar .exe", width=110, height=26, fg_color=CARD2, hover_color="#2b2b32",
                          command=lambda gid=g["id"]: self._game_locate(gid)).pack(side="right")
            path = ctk.CTkLabel(card, text="", text_color=MUTE, font=("Segoe UI", 11), anchor="w")
            path.pack(fill="x", padx=16)
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=6)
            sws = {}
            for opt, label in (("gpu", "GPU dedicada"), ("fso", "Tela cheia exclusiva (sem FSO)"), ("prio", "Prioridade alta de CPU")):
                if opt == "prio" and g["no_prio"]:
                    ctk.CTkLabel(row, text="Prioridade de CPU: indisponível (anti-cheat)", text_color=MUTE,
                                 font=("Segoe UI", 11)).pack(side="left", padx=8)
                    continue
                sw = ctk.CTkSwitch(row, text=label, progress_color=ACCENT, state="disabled",
                                   command=lambda gid=g["id"], o=opt: self._game_toggle(gid, o))
                sw.pack(side="left", padx=8)
                sws[opt] = sw
            for tip in g["tips"]:
                ctk.CTkLabel(card, text="•  " + tip, anchor="w", justify="left", wraplength=720, text_color="#c9c9d1",
                             font=("Segoe UI", 12)).pack(fill="x", padx=16, pady=1)
            if g["launch"]:
                lrow = ctk.CTkFrame(card, fg_color="transparent")
                lrow.pack(fill="x", padx=16, pady=(6, 0))
                ctk.CTkLabel(lrow, text="Opções de inicialização:", text_color=MUTE, font=("Segoe UI", 11)).pack(side="left")
                ent = ctk.CTkEntry(lrow, width=260, fg_color=CARD2, border_width=0)
                ent.insert(0, g["launch"])
                ent.configure(state="readonly")
                ent.pack(side="left", padx=8)
                ctk.CTkButton(lrow, text="Copiar", width=70, height=26, fg_color=CARD2, hover_color="#2b2b32",
                              command=lambda txt=g["launch"]: self._copy(txt)).pack(side="left")
            ctk.CTkFrame(card, height=8, fg_color="transparent").pack()
            self.game_cards[g["id"]] = {"status": status, "path": path, "sws": sws, "exe": None}
        self._scan_games()
        return p

    def _copy(self, txt):
        self.clipboard_clear()
        self.clipboard_append(txt)
        self.say(f"Copiado: {txt}")

    def _scan_games(self):
        def job():
            roots = G._search_roots()
            for g in G.GAMES:
                self._probe_game(g, G.find_exe(g, roots))
        self._bg(job)

    def _probe_game(self, g, exe):
        states = {o: G.is_set(exe, o) for o in G.OPTIONS} if exe else {}
        self.q.put(lambda: self._game_update(g["id"], exe, states))

    def _game_update(self, gid, exe, states):
        c = self.game_cards[gid]
        c["exe"] = exe
        c["status"].configure(text="✔ encontrado" if exe else "não encontrado", text_color=OK if exe else MUTE)
        c["path"].configure(text=exe or "Clique em 'Localizar .exe' e escolha o executável do jogo.")
        for opt, sw in c["sws"].items():
            sw.configure(state="normal" if exe else "disabled")
            (sw.select if states.get(opt) else sw.deselect)()

    def _game_locate(self, gid):
        from tkinter import filedialog
        f = filedialog.askopenfilename(title="Escolha o executável do jogo", filetypes=[("Executável", "*.exe")])
        if f:
            f = os.path.normpath(f)
            G.remember_exe(gid, f)
            g = G.BY_ID[gid]
            self._bg(lambda: self._probe_game(g, f))

    def _game_toggle(self, gid, opt):
        c = self.game_cards[gid]
        exe, on = c["exe"], bool(c["sws"][opt].get())
        g = G.BY_ID[gid]

        def job():
            try:
                G.set_option(exe, opt, on)
                self.say(("✔ " if on else "↩ ") + f"{g['name']}: {opt} {'ativado' if on else 'desativado'}")
            except PermissionError:
                self.say(f"✖ {g['name']}: permissão negada — execute como administrador.")
            except Exception as e:
                self.say(f"✖ {g['name']}: {e}")
            self._probe_game(g, exe)
        self._bg(job)

    # ------------------------------------------------------------ Avançado
    def _page_advanced(self):
        p = ctk.CTkFrame(self.main, fg_color="transparent")
        self._title(p, "Avançado", "Latência, energia, interrupções e DNS. Ajustes para quem quer o máximo do PC.")
        sc = ctk.CTkScrollableFrame(p, fg_color="transparent")
        sc.pack(fill="both", expand=True)
        card = ctk.CTkFrame(sc, fg_color=CARD, corner_radius=12)
        card.pack(fill="x", pady=5, padx=2)
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text="Timer Resolution 0,5 ms (enquanto o app estiver aberto)", font=("Segoe UI", 14, "bold"),
                     anchor="w").grid(row=0, column=0, sticky="w", padx=16, pady=(12, 0))
        self.timer_label = ctk.CTkLabel(card, text="", text_color="#9aa3b2", anchor="w", justify="left", wraplength=640,
                                        font=("Segoe UI", 12))
        self.timer_label.grid(row=1, column=0, sticky="w", padx=16, pady=(2, 12))
        self.timer_sw = ctk.CTkSwitch(card, text="", progress_color=ACCENT, width=46, command=self._toggle_timer)
        self.timer_sw.grid(row=0, column=1, rowspan=2, padx=16)
        self._timer_refresh()
        self._tweak_rows(sc, "avancado")
        return p

    def _timer_refresh(self):
        lo, hi, cur = T.TIMER.query()
        self.timer_label.configure(text=f"Resolução atual do sistema: {cur:.3f} ms (mínima possível: {hi:.3f} ms). "
                                        "Menor = menos latência de input e frametimes mais estáveis. Para valer no "
                                        "sistema todo no Windows 11, ative também 'Timer Resolution global' abaixo. "
                                        "Volta ao normal ao fechar o app; aumenta um pouco o consumo de energia.")

    def _toggle_timer(self):
        on = bool(self.timer_sw.get())
        try:
            cur = T.TIMER.set(on)
            self.say(f"{'✔ Timer em' if on else '↩ Timer liberado, agora'} {cur:.3f} ms")
        except Exception as e:
            self.say(f"✖ Timer: {e}")
        self._timer_refresh()

    # ------------------------------------------------------------ Apps (WinGet)
    def _page_apps(self):
        p = ctk.CTkFrame(self.main, fg_color="transparent")
        self._title(p, "Loja de Apps", "Instale e atualize programas úteis com um clique (usa o WinGet do Windows).")
        self.app_state, self.app_rows = {}, {}
        self._winget_lock = threading.Lock()
        if not W.available():
            ctk.CTkLabel(p, text="WinGet não encontrado. Instale o 'App Installer' pela Microsoft Store.",
                         text_color=DANGER).pack(pady=30)
            return p
        bar = ctk.CTkFrame(p, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 6))
        ctk.CTkButton(bar, text="🔄 Verificar instalados", width=170, fg_color=CARD2, hover_color="#2b2b32",
                      command=self._scan_apps).pack(side="left", padx=(0, 8))
        ctk.CTkButton(bar, text="⬆ Atualizar todos", width=150, fg_color=ACCENT, hover_color=ACCENT_H, text_color=BTN_TXT,
                      command=self._upgrade_apps).pack(side="left")
        sc = ctk.CTkScrollableFrame(p, fg_color="transparent")
        sc.pack(fill="both", expand=True)
        cat = None
        for app_id, name, desc, c in W.CATALOG:
            if c != cat:
                cat = c
                ctk.CTkLabel(sc, text=c, font=("Segoe UI", 16, "bold"), text_color=ACCENT, anchor="w").pack(
                    fill="x", padx=6, pady=(12, 2))
            row = ctk.CTkFrame(sc, fg_color=CARD, corner_radius=10)
            row.pack(fill="x", pady=3, padx=2)
            box = ctk.CTkFrame(row, fg_color="transparent")
            box.pack(side="left", padx=16, pady=8)
            ctk.CTkLabel(box, text=name, font=("Segoe UI", 13, "bold"), anchor="w").pack(anchor="w")
            ctk.CTkLabel(box, text=desc, text_color=MUTE, font=("Segoe UI", 11), anchor="w").pack(anchor="w")
            btn = ctk.CTkButton(row, text="Instalar", width=100, fg_color=ACCENT, hover_color=ACCENT_H, text_color=BTN_TXT,
                                command=lambda i=app_id, n=name: self._app_action(i, n))
            btn.pack(side="right", padx=12)
            st = ctk.CTkLabel(row, text="", width=80, font=("Segoe UI", 11, "bold"))
            st.pack(side="right")
            self.app_rows[app_id] = (st, btn)
        self._scan_apps()
        return p

    def _scan_apps(self):
        def job():
            with self._winget_lock:
                self.say("Verificando apps instalados (winget)...")
                txt = W.installed_text()
            states = {i: i.lower() in txt for i, *_ in W.CATALOG}

            def ui():
                self.app_state.update(states)
                for i, on in states.items():
                    st, btn = self.app_rows[i]
                    st.configure(text="instalado" if on else "", text_color=OK)
                    btn.configure(text="Desinstalar" if on else "Instalar", fg_color=CARD2 if on else ACCENT,
                                  hover_color="#2b2b32" if on else ACCENT_H, text_color="#ffffff" if on else BTN_TXT)
            self.q.put(ui)
        self._bg(job)

    def _app_action(self, app_id, name):
        installed = self.app_state.get(app_id, False)
        if installed and not messagebox.askyesno("Desinstalar", f"Desinstalar {name}?"):
            return

        def job():
            with self._winget_lock:
                self.say(f"{'Desinstalando' if installed else 'Instalando'} {name}... (pode levar alguns minutos)")
                ok, msg = (W.uninstall if installed else W.install)(app_id)
            self.say(("✔ " if ok else "✖ ") + f"{name}: {msg}")
            self._scan_apps()
        self._bg(job)

    def _upgrade_apps(self):
        def job():
            with self._winget_lock:
                self.say("Atualizando todos os apps (winget)... pode levar vários minutos.")
                ok, msg = W.upgrade_all()
            self.say(("✔ " if ok else "⚠ ") + f"Atualização: {msg}")
        self._bg(job)

    # ------------------------------------------------------------ exportar / importar perfil
    def _export_profile(self):
        from tkinter import filedialog
        f = filedialog.asksaveasfilename(defaultextension=".skprofile", initialfile="meu-perfil.skprofile",
                                         filetypes=[("Perfil Skore", "*.skprofile")])
        if not f:
            return

        def job():
            ids = [t.id for t in T.TWEAKS if t.reversible and t.available() and t.is_applied()]
            disabled = [i["name"] for i in T.list_startup() if not i["enabled"]]
            with open(f, "w", encoding="utf-8") as fh:
                json.dump({"format": "skore-profile", "version": 1, "tweaks": ids, "startup_disabled": disabled}, fh, indent=1)
            self.say(f"✔ Perfil exportado: {len(ids)} ajustes e {len(disabled)} itens de inicialização desativados → {f}")
        self._bg(job)

    def _import_profile(self):
        from tkinter import filedialog
        f = filedialog.askopenfilename(filetypes=[("Perfil Skore", "*.skprofile")])
        if not f:
            return
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
            if data.get("format") != "skore-profile":
                raise ValueError("arquivo não é um perfil do Skore Optimizer")
        except (OSError, ValueError) as e:
            self.say(f"✖ Perfil inválido: {e}")
            return
        ids = [i for i in data.get("tweaks", []) if i in T.BY_ID and T.BY_ID[i].reversible and T.BY_ID[i].available()]
        names = [str(n) for n in data.get("startup_disabled", [])]
        msg = (f"Aplicar {len(ids)} ajuste(s) e desativar {len(names)} programa(s) de inicialização?"
               " Só ajustes conhecidos do app são aplicados; o resto do arquivo é ignorado.")
        if not messagebox.askyesno("Importar perfil", msg):
            return

        def job():
            self.say(f"▶ Importando perfil ({os.path.basename(f)})...")
            self._restore_point_sync()
            for tid in ids:
                tw = T.BY_ID[tid]
                try:
                    if not tw.is_applied():
                        T.apply_tweak(tw)
                        self.say(f"  ✔ {tw.title}")
                except Exception as e:
                    self.say(f"  ✖ {tw.title}: {e}")
            for it in T.list_startup():
                if it["name"] in names and it["enabled"]:
                    try:
                        T.set_startup(it, False)
                        self.say(f"  ✔ Inicialização desativada: {it['name']}")
                    except Exception as e:
                        self.say(f"  ✖ {it['name']}: {e}")
            self.say("Perfil importado. Reinicie o PC para concluir.")
            self.q.put(self.refresh_status)
            self.q.put(self._scan_startup)
        self._bg(job)

    # ------------------------------------------------------------ Ferramentas especiais
    def _section(self, sc, text):
        ctk.CTkLabel(sc, text=text, font=("Segoe UI", 18, "bold"), text_color=ACCENT, anchor="w").pack(
            fill="x", padx=6, pady=(16, 2))

    def _tool_card(self, sc, title, desc, buttons):
        """buttons: [(texto, comando, destaque)] — cartão com título, descrição e botões."""
        card = ctk.CTkFrame(sc, fg_color=CARD, corner_radius=12)
        card.pack(fill="x", pady=5, padx=2)
        ctk.CTkLabel(card, text=title, font=("Segoe UI", 14, "bold"), anchor="w").pack(fill="x", padx=16, pady=(12, 0))
        ctk.CTkLabel(card, text=desc, wraplength=720, justify="left", anchor="w", text_color="#9aa3b2",
                     font=("Segoe UI", 12)).pack(fill="x", padx=16, pady=(2, 8))
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(0, 12))
        for text, cmd, hi in buttons:
            ctk.CTkButton(row, text=text, command=cmd, width=170,
                          fg_color=ACCENT if hi else CARD2, hover_color=ACCENT_H if hi else "#2b2b32",
                          text_color=BTN_TXT if hi else "#ffffff").pack(side="left", padx=4)

    def _page_tools(self):
        p = ctk.CTkFrame(self.main, fg_color="transparent")
        self._title(p, "Ferramentas Especiais", "BIOS, Modo Seguro, reparo do Windows e utilitários dos técnicos de otimização.")
        sc = ctk.CTkScrollableFrame(p, fg_color="transparent")
        sc.pack(fill="both", expand=True)
        self._maint_busy = False

        self._section(sc, "Reinício especial")
        self._tool_card(sc, "Entrar na BIOS / UEFI",
                        "Reinicia o PC direto na tela da BIOS em 10 segundos (salve seus trabalhos antes). Ideal para "
                        "configurar XMP, Resizable BAR e energia em call com o cliente. Em PCs sem UEFI, use a tecla "
                        "da placa ao ligar (Del, F2 ou F10).",
                        [("🔧 Reiniciar na BIOS", self._reboot_bios, True), ("✖ Cancelar reinício", self._cancel_reboot, False)])
        self._tool_card(sc, "Modo Seguro / Opções avançadas de inicialização",
                        "Reinicia no menu azul do Windows. Para o Modo Seguro: Solucionar problemas > Opções avançadas > "
                        "Configurações de inicialização > Reiniciar > tecla 4 (ou F4). Necessário para usar o DDU.",
                        [("🛡 Abrir menu avançado", self._reboot_advanced, True), ("✖ Cancelar reinício", self._cancel_reboot, False)])

        self._section(sc, "Atalhos do sistema")
        card = ctk.CTkFrame(sc, fg_color=CARD, corner_radius=12)
        card.pack(fill="x", pady=5, padx=2)
        shortcuts = [("Gerenciador de Dispositivos", "devmgmt.msc"), ("Opções de Energia", "powercfg.cpl"),
                     ("Serviços", "services.msc"), ("Configuração do Sistema", "msconfig"),
                     ("Gerenciador de Tarefas", "taskmgr"), ("Informações do Sistema", "msinfo32"),
                     ("Gerenciamento de Disco", "diskmgmt.msc"), ("Visualizador de Eventos", "eventvwr.msc"),
                     ("Configurações de Vídeo", "ms-settings:display")]
        for i, (txt, target) in enumerate(shortcuts):
            card.grid_columnconfigure(i % 3, weight=1, uniform="s")
            ctk.CTkButton(card, text=txt, fg_color=CARD2, hover_color="#2b2b32",
                          command=lambda t=target: self._open_target(t)).grid(row=i // 3, column=i % 3, padx=8, pady=8, sticky="ew")

        self._section(sc, "Manutenção do Windows")
        self._tool_card(sc, "Reparar o Windows",
                        "Roda SFC (arquivos do sistema), DISM (imagem do Windows) e limpa o cache do Windows Update. "
                        "Pode levar de 10 a 30 minutos; não desligue o PC. Exige administrador.",
                        [("🩹 Reparar agora", self._repair_windows, True)])
        self._tool_card(sc, "Refazer cache de ícones e miniaturas",
                        "Corrige ícones em branco ou errados. A tela pisca por alguns segundos (o Explorer reinicia).",
                        [("🖼 Refazer cache", self._rebuild_icons, False)])

        self._section(sc, "Ferramentas de terceiros (instaladas pelo WinGet)")
        bar = ctk.CTkFrame(sc, fg_color="transparent")
        bar.pack(fill="x")
        ctk.CTkButton(bar, text="🔄 Verificar instalados", width=170, fg_color=CARD2, hover_color="#2b2b32",
                      command=self._scan_tools).pack(side="left", padx=4, pady=4)
        self.tool_state, self.tool_rows = {}, {}
        if not W.available():
            ctk.CTkLabel(sc, text="WinGet não encontrado. Instale o 'App Installer' pela Microsoft Store.",
                         text_color=DANGER).pack(pady=10)
            return p
        for tool in W.TOOLS:
            tid, name, desc, _ = tool
            row = ctk.CTkFrame(sc, fg_color=CARD, corner_radius=10)
            row.pack(fill="x", pady=3, padx=2)
            box = ctk.CTkFrame(row, fg_color="transparent")
            box.pack(side="left", padx=16, pady=8)
            ctk.CTkLabel(box, text=name, font=("Segoe UI", 13, "bold"), anchor="w").pack(anchor="w")
            ctk.CTkLabel(box, text=desc, text_color=MUTE, font=("Segoe UI", 11), anchor="w", wraplength=520,
                         justify="left").pack(anchor="w")
            main = ctk.CTkButton(row, text="Instalar", width=100, fg_color=ACCENT, hover_color=ACCENT_H, text_color=BTN_TXT,
                                 command=lambda t=tool: self._tool_main(t))
            main.pack(side="right", padx=12)
            rem = ctk.CTkButton(row, text="Remover", width=80, fg_color=CARD2, hover_color="#2b2b32",
                                command=lambda t=tool: self._tool_remove(t))
            self.tool_rows[tid] = (main, rem)
        ctk.CTkLabel(sc, text="Dica DDU: instale, reinicie no Modo Seguro (cartão acima), abra o DDU e escolha "
                              "'Limpar e reiniciar'. Depois instale o driver novo (NVCleanstall).",
                     text_color=MUTE, anchor="w", wraplength=720, justify="left").pack(fill="x", padx=6, pady=10)
        self._scan_tools()
        return p

    def _open_target(self, target):
        try:
            os.startfile(target)
        except OSError as e:
            self.say(f"✖ Não consegui abrir {target}: {e}")

    def _reboot(self, args, what):
        if not messagebox.askyesno("Reiniciar o PC", f"O PC vai reiniciar em 10 segundos para {what}.{chr(10)}{chr(10)}"
                                   "Salve seus trabalhos. Continuar?"):
            return

        def job():
            code, out = T.run(["shutdown", "/r"] + args + ["/t", "10", "/c", f"Skore Optimizer: reiniciando para {what}"])
            if code == 0:
                self.say(f"↻ Reiniciando em 10 s para {what}. Use 'Cancelar reinício' para abortar.")
            else:
                self.say(f"✖ Não foi possível reiniciar para {what}: {out.strip()[:120]}")
        self._bg(job)

    def _reboot_bios(self):
        self._reboot(["/fw"], "entrar na BIOS/UEFI")

    def _reboot_advanced(self):
        self._reboot(["/o"], "abrir as opções avançadas de inicialização")

    def _cancel_reboot(self):
        def job():
            code, out = T.run(["shutdown", "/a"])
            self.say("✔ Reinício cancelado." if code == 0 else "Nenhum reinício agendado.")
        self._bg(job)

    def _repair_windows(self):
        if not is_admin():
            self.say("✖ O reparo precisa de administrador. Feche e abra o app como administrador.")
            return
        if self._maint_busy or not messagebox.askyesno(
                "Reparar o Windows", "Rodar SFC, DISM e limpar o cache do Windows Update?" + chr(10) +
                "Leva de 10 a 30 minutos. Não desligue o PC."):
            return
        self._maint_busy = True

        def job():
            try:
                for label, cmd in (("SFC (arquivos do sistema)", ["sfc", "/scannow"]),
                                   ("DISM (imagem do Windows)", ["DISM", "/Online", "/Cleanup-Image", "/RestoreHealth"])):
                    self.say(f"▶ {label}... aguarde.")
                    code, _ = T.run(cmd)
                    self.say(("✔ " if code == 0 else "⚠ ") + f"{label} terminou (código {code}).")
                self.say("▶ Limpando cache do Windows Update...")
                for svc in ("wuauserv", "bits"):
                    T.run(["net", "stop", svc])
                sd = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "SoftwareDistribution")
                if os.path.isdir(sd):
                    try:
                        os.rename(sd, f"{sd}.old-{time.strftime('%Y%m%d%H%M%S')}")
                        self.say("✔ Cache do Windows Update renomeado (o Windows recria sozinho).")
                    except OSError as e:
                        self.say(f"⚠ Não consegui renomear SoftwareDistribution: {e}")
                for svc in ("bits", "wuauserv"):
                    T.run(["net", "start", svc])
                self.say("Reparo concluído. Reinicie o PC.")
            finally:
                self._maint_busy = False
        self._bg(job)

    def _rebuild_icons(self):
        if not messagebox.askyesno("Refazer cache", "O Explorer vai fechar e reabrir (a tela pisca). Continuar?"):
            return

        def job():
            T.run(["taskkill", "/f", "/im", "explorer.exe"])
            local = os.environ.get("LOCALAPPDATA", "")
            explorer = os.path.join(local, "Microsoft", "Windows", "Explorer")
            targets = [os.path.join(local, "IconCache.db")]
            if os.path.isdir(explorer):
                targets += [os.path.join(explorer, f) for f in os.listdir(explorer)
                            if f.lower().startswith(("iconcache", "thumbcache"))]
            n = 0
            for f in targets:
                try:
                    os.remove(f)
                    n += 1
                except OSError:
                    pass
            subprocess.Popen(["explorer.exe"])
            self.say(f"✔ Cache de ícones/miniaturas refeito ({n} arquivo(s) removido(s)).")
        self._bg(job)

    def _scan_tools(self):
        if not self.tool_rows:
            return

        def job():
            with self._winget_lock:
                txt = W.installed_text()
            states = {t[0]: t[0].lower() in txt for t in W.TOOLS}

            def ui():
                self.tool_state.update(states)
                for tid, on in states.items():
                    main, rem = self.tool_rows[tid]
                    main.configure(text="Abrir" if on else "Instalar")
                    rem.pack_forget()
                    if on:
                        rem.pack(side="right", padx=(0, 4))
            self.q.put(ui)
        self._bg(job)

    def _tool_main(self, tool):
        tid, name = tool[0], tool[1]
        if self.tool_state.get(tid):
            path = W.find_tool(tool)
            if path:
                self._open_target(path)
                self.say(f"▶ Abrindo {name}")
            else:
                self.say(f"⚠ Não achei o executável de {name}; abra pelo Menu Iniciar.")
            return

        def job():
            with self._winget_lock:
                self.say(f"Instalando {name}... (pode levar alguns minutos)")
                ok, msg = W.install(tid)
            self.say(("✔ " if ok else "✖ ") + f"{name}: {msg}")
            self._scan_tools()
        self._bg(job)

    def _tool_remove(self, tool):
        tid, name = tool[0], tool[1]
        if not messagebox.askyesno("Remover", f"Desinstalar {name}?"):
            return

        def job():
            with self._winget_lock:
                ok, msg = W.uninstall(tid)
            self.say(("✔ " if ok else "✖ ") + f"{name}: {msg}")
            self._scan_tools()
        self._bg(job)

    # ------------------------------------------------------------ Benchmark
    def _page_bench(self):
        p = ctk.CTkFrame(self.main, fg_color="transparent")
        self._title(p, "Benchmark", "Meça o PC antes e depois das otimizações e veja a diferença em números.")
        self._bench_busy = False
        top = ctk.CTkFrame(p, fg_color=CARD, corner_radius=12)
        top.pack(fill="x", pady=6)
        row = ctk.CTkFrame(top, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(14, 6))
        ctk.CTkLabel(row, text="Nome da medição:", text_color=MUTE).pack(side="left")
        self.bench_label = ctk.CTkEntry(row, width=200, fg_color=CARD2, border_width=0)
        self.bench_label.insert(0, "Antes")
        self.bench_label.pack(side="left", padx=8)
        self.bench_btn = ctk.CTkButton(row, text="▶ Rodar benchmark (~20 s)", fg_color=ACCENT, hover_color=ACCENT_H,
                                       text_color=BTN_TXT, command=self._bench_run)
        self.bench_btn.pack(side="left", padx=8)
        self.bench_bar = ctk.CTkProgressBar(top, progress_color=ACCENT, height=8)
        self.bench_bar.set(0)
        self.bench_bar.pack(fill="x", padx=16)
        self.bench_status = ctk.CTkLabel(top, text="Feche jogos e navegadores antes e meça sempre com o PC parado, nas mesmas "
                                                   "condições. Rode uma vez como 'Antes', aplique os ajustes, reinicie e rode como 'Depois'.",
                                         text_color=MUTE, wraplength=760, justify="left", anchor="w", font=("Segoe UI", 12))
        self.bench_status.pack(fill="x", padx=16, pady=(6, 14))

        cmp_row = ctk.CTkFrame(p, fg_color="transparent")
        cmp_row.pack(fill="x", pady=4)
        self.bench_a, self.bench_b = ctk.StringVar(), ctk.StringVar()
        self.bench_menu_a = ctk.CTkOptionMenu(cmp_row, variable=self.bench_a, values=["(sem medições)"], width=230,
                                              fg_color=CARD2, button_color=CARD2, command=lambda _=None: self._bench_compare())
        self.bench_menu_b = ctk.CTkOptionMenu(cmp_row, variable=self.bench_b, values=["(sem medições)"], width=230,
                                              fg_color=CARD2, button_color=CARD2, command=lambda _=None: self._bench_compare())
        self.bench_menu_a.pack(side="left")
        ctk.CTkLabel(cmp_row, text="  →  ", text_color=ACCENT, font=("Segoe UI", 16, "bold")).pack(side="left")
        self.bench_menu_b.pack(side="left")
        ctk.CTkButton(cmp_row, text="📄 Exportar relatório", width=150, fg_color=CARD2, hover_color="#2b2b32",
                      command=self._bench_export).pack(side="right")
        ctk.CTkButton(cmp_row, text="🗑 Apagar histórico", width=140, fg_color=CARD2, hover_color="#2b2b32",
                      command=self._bench_clear).pack(side="right", padx=8)
        self.bench_summary = ctk.CTkLabel(p, text="", anchor="w", font=("Segoe UI", 14, "bold"))
        self.bench_summary.pack(fill="x", padx=6, pady=(6, 0))
        self.bench_table = ctk.CTkScrollableFrame(p, fg_color="transparent")
        self.bench_table.pack(fill="both", expand=True)
        self._bench_refresh()
        return p

    def _bench_names(self, runs):
        return [f"{i + 1}. {r['label']} — {r['ts']}" for i, r in enumerate(runs)]

    def _bench_refresh(self, select_last=False):
        runs = BM.load()
        names = self._bench_names(runs) or ["(sem medições)"]
        self.bench_menu_a.configure(values=names)
        self.bench_menu_b.configure(values=names)
        if select_last or self.bench_a.get() not in names:
            self.bench_a.set(names[-2] if len(names) > 1 else names[-1])
            self.bench_b.set(names[-1])
        self._bench_compare()

    def _bench_pick(self, runs, var):
        names = self._bench_names(runs)
        v = var.get()
        return runs[names.index(v)] if v in names else None

    def _bench_compare(self):
        for w in self.bench_table.winfo_children():
            w.destroy()
        runs = BM.load()
        a, b = self._bench_pick(runs, self.bench_a), self._bench_pick(runs, self.bench_b)
        if not a or not b:
            self.bench_summary.configure(text="Nenhuma medição ainda. Clique em 'Rodar benchmark'.", text_color=MUTE)
            return
        rows = BM.compare(a, b)
        better = sum(1 for r in rows if r[4] == "melhor")
        worse = sum(1 for r in rows if r[4] == "pior")
        self.bench_summary.configure(
            text=f"{better} métrica(s) melhor(es) • {worse} pior(es) • resto estável ou dentro da variação normal",
            text_color=OK if better > worse else (DANGER if worse > better else MUTE))
        t = self.bench_table
        t.grid_columnconfigure(0, weight=1)
        for c, head in enumerate(("Métrica", "Antes", "Depois", "Variação")):
            ctk.CTkLabel(t, text=head, text_color=ACCENT, font=("Segoe UI", 12, "bold"), anchor="w").grid(
                row=0, column=c, sticky="w", padx=10, pady=4)
        color = {"melhor": OK, "pior": DANGER, "igual": MUTE}
        for i, (name, va, vb, pct, verdict, unit, dec) in enumerate(rows, start=1):
            bg = CARD if i % 2 else BG
            cells = (name, BM.fmt(va, dec, unit), BM.fmt(vb, dec, unit), "--" if pct is None else f"{pct:+.1f}%")
            for c, txt in enumerate(cells):
                ctk.CTkLabel(t, text=txt, anchor="w", fg_color=bg, corner_radius=0, height=30,
                             text_color=color[verdict] if c == 3 else "#ffffff",
                             font=("Segoe UI", 13, "bold" if c == 3 else "normal")).grid(
                    row=i, column=c, sticky="ew", ipadx=8)
        t.grid_columnconfigure((1, 2, 3), minsize=140)

    def _bench_run(self):
        if self._bench_busy:
            return
        self._bench_busy = True
        label = self.bench_label.get().strip() or "Medição"
        self.bench_btn.configure(state="disabled", text="Medindo...")

        def progress(pct, msg):
            self.q.put(lambda: (self.bench_bar.set(pct), self.bench_status.configure(text=msg)))

        def job():
            try:
                rec = BM.run_all(label, progress)
                self.say(f"✔ Benchmark '{label}' concluído ({len(rec['active'])} ajustes ativos no momento).")
            except Exception as e:
                self.say(f"✖ Benchmark falhou: {e}")

            def done():
                self._bench_busy = False
                self.bench_btn.configure(state="normal", text="▶ Rodar benchmark (~20 s)")
                if label.lower() == "antes":
                    self.bench_label.delete(0, "end")
                    self.bench_label.insert(0, "Depois")
                self._bench_refresh(select_last=True)
            self.q.put(done)
        self._bg(job)

    def _bench_export(self):
        from tkinter import filedialog
        runs = BM.load()
        a, b = self._bench_pick(runs, self.bench_a), self._bench_pick(runs, self.bench_b)
        if not a or not b:
            self.say("Faça pelo menos uma medição para exportar.")
            return
        f = filedialog.asksaveasfilename(defaultextension=".html", initialfile="relatorio-skore.html",
                                         filetypes=[("Relatório HTML", "*.html")])
        if f:
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(BM.report_html(a, b))
            self.say(f"✔ Relatório salvo: {f}")
            self._open_target(f)

    def _bench_clear(self):
        if messagebox.askyesno("Apagar histórico", "Apagar todas as medições salvas?"):
            BM.save([])
            self._bench_refresh(select_last=True)

    def _page_profiles(self):
        p = ctk.CTkFrame(self.main, fg_color="transparent")
        self._title(p, "Perfis e Segurança", "Aplique pacotes prontos e proteja o sistema com backups.")
        desc = {"Gaming": "Ajustes seguros para jogos + sistema enxuto. Recomendado.",
                "Geral": "Otimizações gerais e de privacidade (só as seguras): PC leve para o dia a dia.",
                "Gaming Extremo": "Tudo de Gaming, Geral, GPU, Avançado e Privacidade, inclusive ajustes moderados."}
        for name, ids in T.PROFILES.items():
            card = ctk.CTkFrame(p, fg_color=CARD, corner_radius=12)
            card.pack(fill="x", pady=6)
            box = ctk.CTkFrame(card, fg_color="transparent")
            box.pack(side="left", padx=18, pady=14)
            ctk.CTkLabel(box, text=f"{name}  ({len(ids)} ajustes)", font=("Segoe UI", 16, "bold"), anchor="w").pack(anchor="w")
            ctk.CTkLabel(box, text=desc[name], text_color="#9aa3b2", anchor="w").pack(anchor="w")
            ctk.CTkButton(card, text="Aplicar perfil", fg_color=ACCENT, hover_color=ACCENT_H, text_color=BTN_TXT, width=130,
                          command=lambda n=name: self._apply_profile(n)).pack(side="right", padx=18)
        bar = ctk.CTkFrame(p, fg_color="transparent")
        bar.pack(fill="x", pady=14)
        ctk.CTkButton(bar, text="🛟 Criar ponto de restauração", fg_color=CARD2, hover_color="#2b303b",
                      command=self._restore_point).pack(side="left", padx=(0, 10))
        ctk.CTkButton(bar, text="↩ Reverter TUDO", fg_color=CARD2, hover_color="#2b303b",
                      command=self._revert_all).pack(side="left")
        ctk.CTkButton(bar, text="📤 Exportar perfil", fg_color=CARD2, hover_color="#2b303b",
                      command=self._export_profile).pack(side="left", padx=(10, 0))
        ctk.CTkButton(bar, text="📥 Importar perfil", fg_color=CARD2, hover_color="#2b303b",
                      command=self._import_profile).pack(side="left", padx=(10, 0))
        return p

    # ------------------------------------------------------------ hardware / tick
    def _load_hw(self):
        hw = T.hardware_info()
        if hw:
            txt = (f"💻  {hw.get('model', '?')}\n🧠  {hw.get('cpu', '?')}  ({hw.get('cores')}N/{hw.get('threads')}T)\n"
                   f"🎮  {hw.get('gpu', '?')}\n📦  {hw.get('ram', '?')} GB RAM")
        else:
            txt = "Não foi possível detectar o hardware."
        self.q.put(lambda: self.hw_label.configure(text=txt))

    def _tick(self):
        try:
            vals = {"CPU": psutil.cpu_percent(), "RAM": psutil.virtual_memory().percent,
                    "Disco C:": psutil.disk_usage("C:\\").percent}
            for k, v in vals.items():
                lbl, bar = self.meters[k]
                lbl.configure(text=f"{v:.0f}%")
                bar.set(v / 100)
        except Exception:
            pass
        self.after(1000, self._tick)

    # ------------------------------------------------------------ ações
    def _bg(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    def _toggle(self, tw):
        sw, _ = self.switches[tw.id]
        want = bool(sw.get())

        def job():
            try:
                if want:
                    T.apply_tweak(tw)
                    self.say(f"✔ Aplicado: {tw.title}" + ("  (reinicie o PC)" if tw.reboot else ""))
                else:
                    T.revert_tweak(tw)
                    self.say(f"↩ Revertido: {tw.title}")
            except PermissionError:
                self.say(f"✖ {tw.title}: permissão negada — execute como administrador.")
            except Exception as e:
                self.say(f"✖ {tw.title}: {e}")
            self.q.put(self.refresh_status)
        self._bg(job)

    def _run_action(self, tw):
        def job():
            try:
                self.say(f"✔ {tw.title}: {T.apply_tweak(tw)}")
            except Exception as e:
                self.say(f"✖ {tw.title}: {e}")
        self._bg(job)

    def _apply_profile(self, name):
        def job():
            self.say(f"▶ Aplicando perfil {name}...")
            ok, ok_rp = 0, self._restore_point_sync()
            for tid in T.PROFILES[name]:
                tw = T.BY_ID[tid]
                if not tw.available():
                    continue
                try:
                    if not tw.is_applied():
                        T.apply_tweak(tw)
                        self.say(f"  ✔ {tw.title}")
                    ok += 1
                except Exception as e:
                    self.say(f"  ✖ {tw.title}: {e}")
            self.say(f"Perfil {name}: {ok}/{len(T.PROFILES[name])} ajustes ativos. Reinicie o PC para concluir.")
            self.q.put(self.refresh_status)
        self._bg(job)

    def _revert_all(self):
        def job():
            state = T.load_state()
            for tid in list(state):
                tw = T.BY_ID.get(tid)
                if not tw:
                    continue
                try:
                    T.revert_tweak(tw)
                    self.say(f"↩ {tw.title}")
                except Exception as e:
                    self.say(f"✖ {tw.title}: {e}")
            self.say("Tudo revertido ao estado original.")
            self.q.put(self.refresh_status)
        self._bg(job)

    def _restore_point_sync(self):
        self.say("Criando ponto de restauração...")
        ok, out = T.create_restore_point()
        self.say("✔ Ponto de restauração criado." if ok else
                 "⚠ Não foi possível criar o ponto (o Windows limita a 1 a cada 24h, ou a proteção do sistema está desligada).")
        return ok

    def _restore_point(self):
        self._bg(self._restore_point_sync)


if __name__ == "__main__":
    try:
        if "--noadmin" not in sys.argv and not is_admin():
            elevate()
            sys.exit(0)
        App().mainloop()
    except SystemExit:
        raise
    except Exception:
        mostrar_erro_fatal(traceback.format_exc())
        sys.exit(1)
