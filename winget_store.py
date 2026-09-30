"""Skore Optimizer - loja de apps via WinGet (catálogo curado)."""
import shutil

import tweaks as T

# (id do winget, nome, descrição, categoria)
CATALOG = [
    ("Valve.Steam", "Steam", "Loja e launcher de jogos", "Jogos"),
    ("EpicGames.EpicGamesLauncher", "Epic Games Launcher", "Fortnite e jogos grátis da Epic", "Jogos"),
    ("Discord.Discord", "Discord", "Chat de voz e texto para gamers", "Jogos"),
    ("OBSProject.OBSStudio", "OBS Studio", "Gravação e transmissão ao vivo", "Jogos"),
    ("Guru3D.Afterburner", "MSI Afterburner", "Monitor, curva de fan e overclock de GPU", "Hardware"),
    ("REALiX.HWiNFO", "HWiNFO", "Sensores e temperatura de todo o PC", "Hardware"),
    ("CPUID.CPU-Z", "CPU-Z", "Detalhes de CPU, RAM e placa-mãe", "Hardware"),
    ("TechPowerUp.GPU-Z", "GPU-Z", "Detalhes e sensores da placa de vídeo", "Hardware"),
    ("CrystalDewWorld.CrystalDiskInfo", "CrystalDiskInfo", "Saúde de SSD e HD", "Hardware"),
    ("Wagnardsoft.DisplayDriverUninstaller", "DDU", "Remove drivers de vídeo por completo antes de reinstalar", "Hardware"),
    ("Google.Chrome", "Google Chrome", "Navegador", "Navegadores"),
    ("Mozilla.Firefox", "Firefox", "Navegador", "Navegadores"),
    ("Brave.Brave", "Brave", "Navegador com bloqueador de anúncios", "Navegadores"),
    ("7zip.7zip", "7-Zip", "Compactador de arquivos", "Utilitários"),
    ("VideoLAN.VLC", "VLC", "Player de vídeo e áudio", "Utilitários"),
    ("Notepad++.Notepad++", "Notepad++", "Editor de texto", "Utilitários"),
    ("Microsoft.PowerToys", "PowerToys", "Ferramentas extras do Windows", "Utilitários"),
    ("voidtools.Everything", "Everything", "Busca instantânea de arquivos", "Utilitários"),
    ("AntibodySoftware.WizTree", "WizTree", "Mostra o que ocupa espaço no disco", "Utilitários"),
    ("Microsoft.VisualStudioCode", "Visual Studio Code", "Editor de código", "Utilitários"),
]
FLAGS = ["--silent", "--accept-package-agreements", "--accept-source-agreements"]


def available():
    return shutil.which("winget") is not None


def installed_text():
    """Saída de 'winget list' em minúsculas (para conferir ids instalados)."""
    _, out = T.run(["winget", "list", "--accept-source-agreements"])
    return out.lower()


def install(app_id):
    code, out = T.run(["winget", "install", "--id", app_id, "-e"] + FLAGS)
    return code == 0, _last(out)


def uninstall(app_id):
    code, out = T.run(["winget", "uninstall", "--id", app_id, "-e", "--silent", "--accept-source-agreements"])
    return code == 0, _last(out)


def upgrade_all():
    code, out = T.run(["winget", "upgrade", "--all"] + FLAGS)
    return code == 0, _last(out)


def _last(out):
    lines = [l.strip() for l in out.replace("\r", "\n").split("\n") if l.strip() and not set(l.strip()) <= set("-\\|/ ")]
    return lines[-1] if lines else ""


# ---------------------------------------------------------------- ferramentas especiais
# (id winget, nome, descrição, dicas de nome para achar o executável)
TOOLS = [
    ("TechPowerUp.NVCleanstall", "NVCleanstall", "Instala o driver NVIDIA enxuto: escolha o que instalar e remova telemetria.", ["nvcleanstall"]),
    ("Wagnardsoft.DisplayDriverUninstaller", "DDU (Display Driver Uninstaller)",
     "Remove por completo o driver de vídeo. Use no Modo Seguro antes de instalar outro driver.", ["display driver uninstaller"]),
    ("sordum.WindowsUpdateBlocker", "Windows Update Blocker (WUB)", "Liga e desliga o Windows Update com um clique.",
     ["windows update blocker", "wub"]),
    ("Orbmu2k.nvidiaProfileInspector", "NVIDIA Profile Inspector",
     "Opções escondidas do driver NVIDIA (Baixa Latência, energia, filtragem, etc.).", ["nvidiaprofileinspector", "profile inspector"]),
    ("Resplendence.LatencyMon", "LatencyMon", "Mede a latência de drivers e DPC: acha o que causa travadas e áudio picotando.", ["latencymon"]),
    ("CXWorld.CapFrameX", "CapFrameX", "Benchmark de FPS e frametimes com gráficos.", ["capframex"]),
    ("Microsoft.Sysinternals.Autoruns", "Autoruns", "Mostra tudo que inicia com o Windows (mais completo que o Gerenciador de Tarefas).", ["autoruns"]),
    ("Wagnardsoft.ISLC", "ISLC (Intelligent Standby List Cleaner)", "Limpa a memória em espera do Windows e ajuda contra stutter.",
     ["islc", "intelligent standby"]),
    ("BitSum.ProcessLasso", "Process Lasso", "Controla prioridade e afinidade de processos automaticamente.", ["process lasso", "processlasso"]),
    ("Rufus.Rufus", "Rufus", "Cria pendrive de boot do Windows.", ["rufus"]),
    ("Ventoy.Ventoy", "Ventoy", "Pendrive com vários ISOs de boot ao mesmo tempo.", ["ventoy"]),
]


def find_tool(tool):
    """Caminho para abrir a ferramenta instalada (atalho do Menu Iniciar, pacote do WinGet ou Program Files)."""
    import os
    norm = lambda s: s.lower().replace(" ", "").replace("_", "").replace("-", "")
    hints = [norm(h) for h in tool[3]]
    env = os.environ.get
    starts = [os.path.join(env("PROGRAMDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs"),
              os.path.join(env("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs")]
    for base in starts:
        for cur, _, files in os.walk(base):
            for f in files:
                if f.lower().endswith(".lnk") and any(h in norm(f) for h in hints):
                    return os.path.join(cur, f)
    roots = []
    pk = os.path.join(env("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages")
    if os.path.isdir(pk):
        roots += [os.path.join(pk, d) for d in os.listdir(pk) if d.lower().startswith(tool[0].lower())]
    for base in (env("PROGRAMFILES", ""), env("PROGRAMFILES(X86)", ""), os.path.join(env("LOCALAPPDATA", ""), "Programs")):
        if base and os.path.isdir(base):
            roots += [os.path.join(base, d) for d in os.listdir(base) if any(h in norm(d) for h in hints)]
    for root in roots:
        depth0 = root.count(os.sep)
        for cur, dirs, files in os.walk(root):
            if cur.count(os.sep) - depth0 >= 3:
                dirs[:] = []
            for f in files:
                if f.lower().endswith(".exe") and any(h in norm(f) for h in hints) and "unins" not in f.lower():
                    return os.path.join(cur, f)
    return None
