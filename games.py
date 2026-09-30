"""Skore Optimizer - ajustes por jogo: detecção do .exe, GPU dedicada, tela cheia e prioridade de CPU."""
import json
import os
import re
import string

import tweaks as T

LAYERS = r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"
IFEO = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options"
FSO_FLAG = "DISABLEDXMAXIMIZEDWINDOWEDMODE"

# no_prio: anti-cheat de kernel (Vanguard) — não oferecemos prioridade via IFEO nesses jogos.
GAMES = [
    dict(id="valorant", name="VALORANT", exes=["VALORANT-Win64-Shipping.exe"], no_prio=True, launch="",
         tips=["Vídeo: Limitar FPS em segundo plano e no menu; Vsync desligado; Material/Textura/Detalhe: Baixo ou Médio.",
               "Multithreaded Rendering: Ligado. Use tela cheia (não janela sem borda) para menor latência.",
               "O Vanguard exige TPM/Secure Boot; evite mexer em serviços do Windows que ele use."]),
    dict(id="lol", name="League of Legends", exes=["League of Legends.exe"], no_prio=True, launch="",
         tips=["Vídeo: tela cheia (Exclusive), Limitar FPS: sem limite ou o refresh do monitor, Sombras: Desligado.",
               "Feche o Client depois de entrar na partida (o LeagueClient consome RAM e CPU)."]),
    dict(id="cs2", name="Counter-Strike 2", exes=["cs2.exe"], no_prio=False, launch="-novid -high",
         tips=["Vídeo: Modo de exibição Tela cheia; Suavização MSAA 4x (ou 2x); Sombras Alto/Médio; Vsync desligado.",
               "Na Steam: Propriedades > Opções de inicialização; cole o texto acima. Use +fps_max 0 se quiser FPS sem limite."]),
    dict(id="fortnite", name="Fortnite", exes=["FortniteClient-Win64-Shipping.exe"], no_prio=False, launch="",
         tips=["Vídeo: Modo de renderização Desempenho (menos gráficos, mais FPS) em PCs fracos; DirectX 11 é o mais estável.",
               "Desligue Nanite, Lumen e Sombras virtuais; Resolução 3D 100%; limite de FPS igual ao do monitor."]),
    dict(id="apex", name="Apex Legends", exes=["r5apex_dx12.exe", "r5apex.exe"], no_prio=False,
         launch="-novid +fps_max unlimited",
         tips=["Vídeo: Modo tela cheia; Vsync desligado; Detalhe de modelo/efeitos Baixo; Sombras Baixo.",
               "No Steam/EA app: Propriedades > Opções de inicialização; cole o texto acima."]),
    dict(id="warzone", name="Call of Duty (Warzone)", exes=["cod.exe"], no_prio=False, launch="",
         tips=["Vídeo: Tela cheia exclusiva; Sincronização vertical Desligada; Reflexos/Sombras no Baixo.",
               "Habilite NVIDIA Reflex (Ligado + Boost) se tiver placa NVIDIA."]),
    dict(id="rust", name="Rust", exes=["RustClient.exe"], no_prio=False, launch="-high -window-mode exclusive",
         tips=["Gráficos: Qualidade de sombras Baixo, Alcance de draw Médio, Oclusão de partículas: Desligado.",
               "Steam > Opções de inicialização: cole o texto acima."]),
    dict(id="tarkov", name="Escape from Tarkov", exes=["EscapeFromTarkov.exe"], no_prio=False, launch="",
         tips=["Tela cheia exclusiva; Sincronização vertical desligada; Qualidade de sombras e Nível de detalhe médios.",
               "Feche o launcher da BSG depois de abrir o jogo para liberar RAM."]),
    dict(id="marvel", name="Marvel Rivals", exes=["Marvel-Win64-Shipping.exe"], no_prio=False, launch="",
         tips=["Vídeo: Modo tela cheia; qualidade Baixa/Média; ative NVIDIA Reflex; desligue Lumen e reflexos."]),
    dict(id="overwatch", name="Overwatch 2", exes=["Overwatch.exe"], no_prio=False, launch="",
         tips=["Vídeo: Tela cheia; Reduzir buffering: Ligado; Qualidade de modelos/sombras Baixo; FPS: sem limite."]),
]
BY_ID = {g["id"]: g for g in GAMES}


# ---------------------------------------------------------------- detecção
def _steam_common_dirs():
    steam = T.reg_read("HKCU", r"Software\Valve\Steam", "SteamPath")
    dirs = []
    if steam:
        root = str(steam[0]).replace("/", os.sep)
        dirs.append(os.path.join(root, "steamapps", "common"))
        try:
            with open(os.path.join(root, "steamapps", "libraryfolders.vdf"), encoding="utf-8", errors="ignore") as f:
                for m in re.finditer(r'"path"\s+"([^"]+)"', f.read()):
                    dirs.append(os.path.join(m.group(1).replace("\\\\", "\\"), "steamapps", "common"))
        except OSError:
            pass
    return dirs


def _epic_dirs():
    out, man = [], os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "Epic", "EpicGamesLauncher", "Data", "Manifests")
    try:
        for fn in os.listdir(man):
            if fn.endswith(".item"):
                try:
                    with open(os.path.join(man, fn), encoding="utf-8") as f:
                        loc = json.load(f).get("InstallLocation")
                    if loc:
                        out.append(loc)
                except (OSError, ValueError):
                    pass
    except OSError:
        pass
    return out


def _search_roots():
    roots = _steam_common_dirs() + _epic_dirs()
    for d in (f"{c}:\\" for c in string.ascii_uppercase):
        if os.path.isdir(d):
            for sub in ("Riot Games", "Epic Games", "Games", r"Program Files\Epic Games", r"Program Files (x86)\Steam\steamapps\common",
                        r"Program Files\EA Games", r"Program Files (x86)\Battle.net", r"Program Files\Call of Duty", "Battlestate Games"):
                p = os.path.join(d, sub)
                if os.path.isdir(p):
                    roots.append(p)
    return list(dict.fromkeys(roots))


def find_exe(game, roots=None):
    """Caminho do executável do jogo, ou None. Usa caminho escolhido pelo usuário, preferências de GPU e busca."""
    saved = T.load_state().get("_games", {}).get(game["id"])
    if saved and os.path.exists(saved):
        return saved
    wanted = {e.lower() for e in game["exes"]}
    for path, _ in T.gpu_pref_list():
        if os.path.basename(path).lower() in wanted and os.path.exists(path):
            return path
    for root in roots if roots is not None else _search_roots():
        base_depth = root.rstrip("\\").count("\\")
        for cur, dirs, files in os.walk(root):
            if cur.count("\\") - base_depth >= 7:
                dirs[:] = []
            for f in files:
                if f.lower() in wanted:
                    return os.path.join(cur, f)
    return None


def remember_exe(game_id, path):
    state = T.load_state()
    state.setdefault("_games", {})[game_id] = path
    T.save_state(state)


# ---------------------------------------------------------------- opções por jogo
OPTIONS = ("gpu", "fso", "prio")


def _flags(exe):
    cur = T.reg_read("HKCU", LAYERS, exe)
    return [x for x in str(cur[0]).split() if x != "~"] if cur else []


def _write_flags(exe, flags):
    if flags:
        T.reg_write("HKCU", LAYERS, exe, T.SZ, "~ " + " ".join(flags))
    else:
        T.reg_delete("HKCU", LAYERS, exe)


def _ifeo_path(exe):
    return IFEO + "\\" + os.path.basename(exe) + r"\PerfOptions"


def is_set(exe, opt):
    if opt == "gpu":
        return any(p.lower() == exe.lower() and pref == "2" for p, pref in T.gpu_pref_list())
    if opt == "fso":
        return FSO_FLAG in _flags(exe)
    if opt == "prio":
        cur = T.reg_read("HKLM", _ifeo_path(exe), "CpuPriorityClass")
        return bool(cur) and cur[0] == 3
    return False


def set_option(exe, opt, on):
    if opt == "gpu":
        (T.gpu_pref_set if on else T.gpu_pref_remove)(exe)
    elif opt == "fso":
        flags = [f for f in _flags(exe) if f != FSO_FLAG]
        _write_flags(exe, flags + [FSO_FLAG] if on else flags)
    elif opt == "prio":
        if on:
            T.reg_write("HKLM", _ifeo_path(exe), "CpuPriorityClass", T.DWORD, 3)
        else:
            T.reg_delete("HKLM", _ifeo_path(exe), "CpuPriorityClass")
