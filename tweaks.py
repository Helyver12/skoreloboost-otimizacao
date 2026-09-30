"""Skore Optimizer - motor de tweaks: cada ajuste sabe verificar, aplicar e reverter."""
import json
import os
import re
import shutil
import subprocess
import winreg

HIVES = {"HKLM": winreg.HKEY_LOCAL_MACHINE, "HKCU": winreg.HKEY_CURRENT_USER}
DWORD, SZ = winreg.REG_DWORD, winreg.REG_SZ
NO_WINDOW = 0x08000000

STATE_DIR = os.path.join(os.environ.get("APPDATA", "."), "SkoreOptimizer")
STATE_FILE = os.path.join(STATE_DIR, "backup.json")


# ---------------------------------------------------------------- registro
def reg_read(hive, path, name):
    """Retorna (valor, tipo) ou None se não existir."""
    try:
        with winreg.OpenKey(HIVES[hive], path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            return winreg.QueryValueEx(k, name)
    except OSError:
        return None


def reg_key_exists(hive, path):
    try:
        with winreg.OpenKey(HIVES[hive], path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY):
            return True
    except OSError:
        return False


def reg_write(hive, path, name, rtype, value):
    with winreg.CreateKeyEx(HIVES[hive], path, 0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
        winreg.SetValueEx(k, name, 0, rtype, value)


def reg_delete(hive, path, name):
    try:
        with winreg.OpenKey(HIVES[hive], path, 0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
            winreg.DeleteValue(k, name)
    except OSError:
        pass


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=NO_WINDOW,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


# ---------------------------------------------------------------- tweaks
class Tweak:
    reversible = True

    def __init__(self, id, title, desc, category, risk="safe", reboot=False):
        self.id, self.title, self.desc = id, title, desc
        self.category, self.risk, self.reboot = category, risk, reboot

    def available(self):
        """False se o ajuste não se aplica a este PC (ex.: driver NVIDIA ausente)."""
        return True

    def is_applied(self):
        return False

    def apply(self):
        """Aplica e devolve os dados necessários para reverter."""
        raise NotImplementedError

    def revert(self, backup):
        raise NotImplementedError


class RegTweak(Tweak):
    """ops: lista de (hive, path, nome, tipo, valor) ou função que retorna essa lista."""

    def __init__(self, *a, ops, needs=None, **kw):
        super().__init__(*a, **kw)
        self._ops = ops
        self.needs = needs   # (hive, chave) que precisa existir para o ajuste valer

    def available(self):
        n = self.needs
        if n is None:
            return True
        return n() if callable(n) else reg_key_exists(*n)

    def ops(self):
        return self._ops() if callable(self._ops) else self._ops

    def is_applied(self):
        ops = self.ops()
        if not ops:
            return False
        for hive, path, name, rtype, value in ops:
            cur = reg_read(hive, path, name)
            if cur is None or str(cur[0]) != str(value):
                return False
        return True

    def apply(self):
        backup = []
        for hive, path, name, rtype, value in self.ops():
            cur = reg_read(hive, path, name)
            backup.append({"hive": hive, "path": path, "name": name,
                           "existed": cur is not None,
                           "type": cur[1] if cur else rtype,
                           "value": cur[0] if cur else None})
            reg_write(hive, path, name, rtype, value)
        return backup

    def revert(self, backup):
        for b in backup:
            if b["existed"]:
                reg_write(b["hive"], b["path"], b["name"], b["type"], b["value"])
            else:
                reg_delete(b["hive"], b["path"], b["name"])


class PowerPlanTweak(Tweak):
    ULT = "e9a42b02-d5df-448d-aa00-03f14749eb61"
    GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")

    def _active(self):
        _, out = run(["powercfg", "/getactivescheme"])
        m = self.GUID.search(out)
        return (m.group(0).lower() if m else None), out

    def is_applied(self):
        _, out = self._active()
        return "ultimate" in out.lower() or "desempenho máximo" in out.lower() \
            or "desempenho maximo" in out.lower()

    def apply(self):
        previous, _ = self._active()
        code, out = run(["powercfg", "-duplicatescheme", self.ULT])
        m = self.GUID.search(out)
        if code != 0 or not m:
            raise RuntimeError("Este Windows não permite criar o plano Desempenho Máximo.")
        new = m.group(0)
        run(["powercfg", "/setactive", new])
        return {"previous": previous, "new": new}

    def revert(self, backup):
        if backup.get("previous"):
            run(["powercfg", "/setactive", backup["previous"]])
        if backup.get("new"):
            run(["powercfg", "/delete", backup["new"]])


class ActionTweak(Tweak):
    """Ação pontual (limpeza etc.): não tem estado nem reversão."""
    reversible = False

    def __init__(self, *a, func, **kw):
        super().__init__(*a, **kw)
        self.func = func

    def apply(self):
        return self.func()


class PowercfgTweak(Tweak):
    """Valores de energia (na tomada) do plano ativo. settings: [(subgrupo_guid, config_guid, valor)]."""
    PS = r"SYSTEM\CurrentControlSet\Control\Power\User\PowerSchemes"
    GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")

    def __init__(self, *a, settings, **kw):
        super().__init__(*a, **kw)
        self.settings = settings

    def _active(self):
        _, out = run(["powercfg", "/getactivescheme"])
        m = self.GUID.search(out)
        return m.group(0).lower() if m else None

    def _path(self, guid, sub, st):
        return f"{self.PS}\\{guid}\\{sub}\\{st}"

    def is_applied(self):
        guid = self._active()
        if not guid:
            return False
        for sub, st, value in self.settings:
            cur = reg_read("HKLM", self._path(guid, sub, st), "ACSettingIndex")
            if cur is None or int(cur[0]) != value:
                return False
        return True

    def apply(self):
        guid = self._active()
        if not guid:
            raise RuntimeError("Não foi possível ler o plano de energia ativo.")
        items = []
        for sub, st, value in self.settings:
            cur = reg_read("HKLM", self._path(guid, sub, st), "ACSettingIndex")
            items.append({"sub": sub, "st": st, "existed": cur is not None, "value": cur[0] if cur else None})
            run(["powercfg", "/setacvalueindex", guid, sub, st, str(value)])
        run(["powercfg", "/setactive", guid])
        return {"guid": guid, "items": items}

    def revert(self, backup):
        guid = backup["guid"]
        for it in backup["items"]:
            if it["existed"]:
                run(["powercfg", "/setacvalueindex", guid, it["sub"], it["st"], str(it["value"])])
            else:
                reg_delete("HKLM", self._path(guid, it["sub"], it["st"]), "ACSettingIndex")
        run(["powercfg", "/setactive", guid])


def ps_json(cmd):
    code, out = run(["powershell", "-NoProfile", "-Command", cmd])
    try:
        return json.loads(out)
    except ValueError:
        return None


class DnsTweak(Tweak):
    """DNS Cloudflare + DNS sobre HTTPS nas placas de rede ativas (reversível)."""
    SERVERS = ["1.1.1.1", "1.0.0.1"]

    def _current(self):
        idx = ps_json("ConvertTo-Json -Compress -InputObject @(Get-NetAdapter | ? {$_.Status -eq 'Up' -and -not $_.Virtual}"
                      " | select -ExpandProperty InterfaceIndex)")
        if not idx:
            return {}
        cur = {}
        for i in idx:
            d = ps_json(f"ConvertTo-Json -Compress -InputObject @((Get-DnsClientServerAddress -InterfaceIndex {int(i)}"
                        " -AddressFamily IPv4).ServerAddresses)")
            cur[str(i)] = d or []
        return cur

    def is_applied(self):
        cur = self._current()
        return bool(cur) and all(v[:1] == self.SERVERS[:1] for v in cur.values())

    def apply(self):
        backup = self._current()
        if not backup:
            raise RuntimeError("Nenhuma placa de rede ativa encontrada.")
        for i in backup:
            run(["powershell", "-NoProfile", "-Command",
                 f"Set-DnsClientServerAddress -InterfaceIndex {int(i)} -ServerAddresses {','.join(self.SERVERS)}"])
        for s in self.SERVERS:   # DoH (Windows 11); ignora erro em versões sem o comando
            run(["powershell", "-NoProfile", "-Command",
                 f"Add-DnsClientDohServerAddress -ServerAddress {s} -DohTemplate https://cloudflare-dns.com/dns-query"
                 " -AllowFallbackToUdp $true -AutoUpgrade $true -ErrorAction SilentlyContinue"])
        run(["ipconfig", "/flushdns"])
        return backup

    def revert(self, backup):
        for i, servers in backup.items():
            if servers:
                cmd = f"Set-DnsClientServerAddress -InterfaceIndex {int(i)} -ServerAddresses {','.join(servers)}"
            else:
                cmd = f"Set-DnsClientServerAddress -InterfaceIndex {int(i)} -ResetServerAddresses"
            run(["powershell", "-NoProfile", "-Command", cmd])
        run(["ipconfig", "/flushdns"])


class TimerResolution:
    """Resolução do timer do Windows (0,5 ms) enquanto o app estiver aberto."""

    def __init__(self):
        import ctypes
        self.ct = ctypes
        self.nt = ctypes.WinDLL("ntdll")
        self.active = False

    def query(self):
        """(mais_lento, mais_rápido, atual) em ms."""
        c = self.ct
        lo, hi, cur = c.c_ulong(), c.c_ulong(), c.c_ulong()
        self.nt.NtQueryTimerResolution(c.byref(lo), c.byref(hi), c.byref(cur))
        return lo.value / 10000, hi.value / 10000, cur.value / 10000

    def set(self, on):
        c = self.ct
        lo, hi, cur = c.c_ulong(), c.c_ulong(), c.c_ulong()
        self.nt.NtQueryTimerResolution(c.byref(lo), c.byref(hi), c.byref(cur))
        self.nt.NtSetTimerResolution(hi.value, bool(on), c.byref(cur))
        self.active = bool(on)
        return cur.value / 10000


TIMER = TimerResolution()


# ---------------------------------------------------------------- ações
def clean_temp():
    return clean_dirs([os.environ.get("TEMP"), os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Temp")])


def shader_cache_dirs():
    local, common = os.environ.get("LOCALAPPDATA", ""), os.environ.get("PROGRAMDATA", "")
    return [os.path.join(local, "D3DSCache"), os.path.join(local, "NVIDIA", "DXCache"),
            os.path.join(local, "NVIDIA", "GLCache"), os.path.join(common, "NVIDIA Corporation", "NV_Cache"),
            os.path.join(local, "AMD", "DxCache"), os.path.join(local, "AMD", "DxcCache"),
            os.path.join(local, "AMD", "GLCache"), os.path.join(local, "AMD", "VkCache")]


def clean_dirs(dirs):
    """Apaga o conteúdo das pastas (ignora arquivos em uso) e informa o espaço liberado."""
    freed = 0
    for d in filter(None, dirs):
        if not os.path.isdir(d):
            continue
        for entry in os.scandir(d):
            try:
                if entry.is_dir(follow_symlinks=False):
                    size = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(entry.path) for f in fs
                               if os.path.exists(os.path.join(r, f)))
                    shutil.rmtree(entry.path, ignore_errors=True)
                    if not os.path.exists(entry.path):
                        freed += size
                else:
                    size = entry.stat().st_size
                    os.remove(entry.path)
                    freed += size
            except OSError:
                pass  # arquivo em uso: ignora
    return f"{freed / 1024 / 1024:.1f} MB liberados"


def flush_dns():
    run(["ipconfig", "/flushdns"])
    return "Cache DNS limpo"


def _nagle_ops():
    """TCPNoDelay/TcpAckFrequency em todas as interfaces de rede com IP."""
    base = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"
    ops = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            i = 0
            while True:
                try:
                    guid = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                p = base + "\\" + guid
                if reg_read("HKLM", p, "DhcpIPAddress") or reg_read("HKLM", p, "IPAddress"):
                    ops += [("HKLM", p, "TcpAckFrequency", DWORD, 1), ("HKLM", p, "TCPNoDelay", DWORD, 1)]
    except OSError:
        pass
    return ops


def _nv_telemetry_ops():
    ops = [("HKLM", r"SOFTWARE\NVIDIA Corporation\NvControlPanel2\Client", "OptInOrOutPreference", DWORD, 0)]
    svc = r"SYSTEM\CurrentControlSet\Services\NvTelemetryContainer"
    if reg_key_exists("HKLM", svc):   # só mexe no serviço se ele existir (drivers novos não têm)
        ops.append(("HKLM", svc, "Start", DWORD, 4))
    return ops


# valores "chave=valor;" usados pelo Windows em Configurações > Gráficos
GPU_PREFS = r"Software\Microsoft\DirectX\UserGpuPreferences"


def kv_parse(s):
    return dict(p.split("=", 1) for p in (s or "").split(";") if "=" in p)


def kv_build(d):
    return "".join(f"{k}={v};" for k, v in d.items())


def _windowed_opt_ops():
    cur = reg_read("HKCU", GPU_PREFS, "DirectXUserGlobalSettings")
    d = kv_parse(cur[0] if cur else "")
    d.update({"SwapEffectUpgradeEnable": "1", "VRROptimizeEnable": "1"})
    return [("HKCU", GPU_PREFS, "DirectXUserGlobalSettings", SZ, kv_build(d))]


CLASS_DISPLAY = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
_VENDORS = None


def display_adapters():
    """[(subchave, descrição)] das placas de vídeo instaladas (lido do registro, rápido)."""
    out = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, CLASS_DISPLAY, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                cur = reg_read("HKLM", CLASS_DISPLAY + "\\" + sub, "DriverDesc")
                if cur:
                    out.append((sub, str(cur[0])))
    except OSError:
        pass
    return out


def gpu_vendors():
    """Conjunto com 'NVIDIA', 'AMD' e/ou 'INTEL' conforme as placas de vídeo do PC."""
    global _VENDORS
    if _VENDORS is None:
        _VENDORS = set()
        for _, desc in display_adapters():
            d = desc.lower()
            if "nvidia" in d:
                _VENDORS.add("NVIDIA")
            elif "amd" in d or "radeon" in d or "advanced micro" in d:
                _VENDORS.add("AMD")
            elif "intel" in d:
                _VENDORS.add("INTEL")
    return _VENDORS


def _has_dedicated_gpu():
    return bool(gpu_vendors() & {"NVIDIA", "AMD"})


def _amd_ulps_ops():
    """EnableUlps=0 só nas placas AMD que já possuem esse valor."""
    ops = []
    for sub, desc in display_adapters():
        d = desc.lower()
        path = CLASS_DISPLAY + "\\" + sub
        if ("amd" in d or "radeon" in d) and reg_read("HKLM", path, "EnableUlps") is not None:
            ops.append(("HKLM", path, "EnableUlps", DWORD, 0))
    return ops


def _msi_gpu_ops():
    """MSISupported=1 em cada GPU PCI (lido de Enum\\PCI)."""
    base = r"SYSTEM\CurrentControlSet\Enum\PCI"
    display_guid = "{4d36e968-e325-11ce-bfc1-08002be10318}"
    ops = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            i = 0
            while True:
                try:
                    dev = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                with winreg.OpenKey(k, dev) as kd:
                    j = 0
                    while True:
                        try:
                            inst = winreg.EnumKey(kd, j)
                        except OSError:
                            break
                        j += 1
                        p = f"{base}\\{dev}\\{inst}"
                        cg = reg_read("HKLM", p, "ClassGUID")
                        if cg and str(cg[0]).lower() == display_guid:
                            ops.append(("HKLM", p + r"\Device Parameters\Interrupt Management\MessageSignaledInterruptProperties",
                                        "MSISupported", DWORD, 1))
    except OSError:
        pass
    return ops


SYSPROF = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile"
CDM = r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager"

G, X = "gaming", "geral"
TWEAKS = [
    # ------------------------------------------------------------ GAMING
    PowerPlanTweak("power_ultimate", "Plano de energia Desempenho Máximo",
                   "Impede a CPU de reduzir o clock em jogos. Aumenta consumo e calor (evite na bateria).",
                   G),
    RegTweak("game_mode", "Modo de Jogo do Windows",
             "Prioriza o jogo em primeiro plano e evita que o Windows Update atrapalhe.", G,
             ops=[("HKCU", r"Software\Microsoft\GameBar", "AutoGameModeEnabled", DWORD, 1),
                  ("HKCU", r"Software\Microsoft\GameBar", "AllowAutoGameMode", DWORD, 1)]),
    RegTweak("gamedvr_off", "Desativar Game DVR / gravação em segundo plano",
             "Remove a captura automática da Xbox Game Bar, que consome CPU/GPU e causa quedas de FPS.", G,
             ops=[("HKCU", r"System\GameConfigStore", "GameDVR_Enabled", DWORD, 0),
                  ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\GameDVR", "AppCaptureEnabled", DWORD, 0),
                  ("HKLM", r"SOFTWARE\Policies\Microsoft\Windows\GameDVR", "AllowGameDVR", DWORD, 0)]),
    RegTweak("hags", "Agendamento de GPU acelerado por hardware (HAGS)",
             "Reduz latência de CPU->GPU em placas NVIDIA GTX 1000+/AMD recentes. Requer driver atualizado.", G,
             reboot=True, ops=[("HKLM", r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode", DWORD, 2)]),
    RegTweak("net_throttle", "Remover limitação de rede multimídia",
             "Desativa o NetworkThrottlingIndex e dá mais resposta ao sistema para jogos/streaming.", G,
             ops=[("HKLM", SYSPROF, "NetworkThrottlingIndex", DWORD, 0xFFFFFFFF),
                  ("HKLM", SYSPROF, "SystemResponsiveness", DWORD, 10)]),
    RegTweak("games_priority", "Prioridade alta para tarefas de jogo",
             "Ajusta GPU Priority, Priority e Scheduling Category da tarefa 'Games' do agendador multimídia.", G,
             ops=[("HKLM", SYSPROF + r"\Tasks\Games", "GPU Priority", DWORD, 8),
                  ("HKLM", SYSPROF + r"\Tasks\Games", "Priority", DWORD, 6),
                  ("HKLM", SYSPROF + r"\Tasks\Games", "Scheduling Category", SZ, "High"),
                  ("HKLM", SYSPROF + r"\Tasks\Games", "SFIO Priority", SZ, "High")]),
    RegTweak("prio_sep", "Priorizar programa em primeiro plano",
             "Win32PrioritySeparation = 0x26: mais fatias de CPU para o app/jogo que você está usando.", G,
             risk="medium",
             ops=[("HKLM", r"SYSTEM\CurrentControlSet\Control\PriorityControl", "Win32PrioritySeparation", DWORD, 0x26)]),
    RegTweak("mouse_accel", "Desativar aceleração do mouse",
             "Precisão 1:1 do mouse (essencial em FPS). Vale ao reiniciar a sessão do Windows.", G,
             ops=[("HKCU", r"Control Panel\Mouse", "MouseSpeed", SZ, "0"),
                  ("HKCU", r"Control Panel\Mouse", "MouseThreshold1", SZ, "0"),
                  ("HKCU", r"Control Panel\Mouse", "MouseThreshold2", SZ, "0")]),
    RegTweak("nagle_off", "Desativar algoritmo de Nagle (menor ping)",
             "TCPNoDelay + TcpAckFrequency=1: envia pacotes na hora. Reduz latência em alguns jogos online.", G,
             risk="medium", reboot=True, ops=_nagle_ops),
    RegTweak("fso_off", "Desativar otimizações de tela cheia globais",
             "Faz jogos em tela cheia usar modo exclusivo real. Pode ajudar ou ser neutro dependendo do jogo.", G,
             risk="medium",
             ops=[("HKCU", r"System\GameConfigStore", "GameDVR_FSEBehaviorMode", DWORD, 2),
                  ("HKCU", r"System\GameConfigStore", "GameDVR_HonorUserFSEBehaviorMode", DWORD, 1),
                  ("HKCU", r"System\GameConfigStore", "GameDVR_DXGIHonorFSEWindowsCompatible", DWORD, 1)]),
    # ------------------------------------------------------------ GERAL
    RegTweak("telemetry_off", "Reduzir telemetria do Windows",
             "Define coleta de diagnóstico ao mínimo e desativa o serviço DiagTrack.", X,
             ops=[("HKLM", r"SOFTWARE\Policies\Microsoft\Windows\DataCollection", "AllowTelemetry", DWORD, 0),
                  ("HKLM", r"SYSTEM\CurrentControlSet\Services\DiagTrack", "Start", DWORD, 4)]),
    RegTweak("bg_apps_off", "Impedir apps em segundo plano",
             "Apps da Microsoft Store deixam de rodar escondidos, poupando RAM, CPU e bateria.", X,
             ops=[("HKCU", r"Software\Microsoft\Windows\CurrentVersion\BackgroundAccessApplications",
                   "GlobalUserDisabled", DWORD, 1)]),
    RegTweak("ads_off", "Remover anúncios e sugestões do Windows",
             "Desativa ID de publicidade, sugestões no Iniciar e apps promovidos.", X,
             ops=[("HKCU", r"Software\Microsoft\Windows\CurrentVersion\AdvertisingInfo", "Enabled", DWORD, 0),
                  ("HKCU", CDM, "SystemPaneSuggestionsEnabled", DWORD, 0),
                  ("HKCU", CDM, "SilentInstalledAppsEnabled", DWORD, 0),
                  ("HKCU", CDM, "SubscribedContent-338388Enabled", DWORD, 0),
                  ("HKCU", CDM, "SubscribedContent-338389Enabled", DWORD, 0)]),
    RegTweak("web_search_off", "Pesquisa do Iniciar só local",
             "Tira resultados da web (Bing) da busca do Windows: mais rápida e privada.", X,
             ops=[("HKCU", r"Software\Policies\Microsoft\Windows\Explorer", "DisableSearchBoxSuggestions", DWORD, 1)]),
    RegTweak("fast_startup_off", "Desativar Inicialização Rápida",
             "Evita problemas de drivers/atualizações e garante um boot limpo a cada desligamento.", X,
             reboot=True,
             ops=[("HKLM", r"SYSTEM\CurrentControlSet\Control\Session Manager\Power", "HiberbootEnabled", DWORD, 0)]),
    RegTweak("startup_delay_off", "Sem atraso na inicialização de apps",
             "Remove o atraso artificial que o Windows aplica aos programas de inicialização.", X,
             ops=[("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Serialize", "StartupDelayInMSec", DWORD, 0)]),
    RegTweak("menu_fast", "Menus e janelas mais rápidos",
             "Zera o atraso de menus e a animação de minimizar/maximizar (sensação de PC mais ágil).", X,
             ops=[("HKCU", r"Control Panel\Desktop", "MenuShowDelay", SZ, "0"),
                  ("HKCU", r"Control Panel\Desktop\WindowMetrics", "MinAnimate", SZ, "0")]),
    RegTweak("transparency_off", "Desativar efeitos de transparência",
             "Alivia a GPU integrada e deixa a interface mais leve.", X,
             ops=[("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", "EnableTransparency", DWORD, 0)]),
    # ------------------------------------------------------------ LIMPEZA
    ActionTweak("clean_temp", "Limpar arquivos temporários",
                "Apaga %TEMP% e Windows\\Temp (arquivos em uso são ignorados).", "limpeza", func=clean_temp),
    ActionTweak("flush_dns", "Limpar cache DNS",
                "Resolve lentidão/erros de conexão causados por DNS antigo.", "limpeza", func=flush_dns),
    ActionTweak("clean_shader", "Limpar cache de shaders (NVIDIA/AMD/DirectX)",
                "Apaga o cache de shaders do DirectX, NVIDIA e AMD. Útil após atualizar o driver ou se um jogo travar; "
                "os jogos recompilam os shaders na próxima abertura (pode ter micro-travadas uma vez).",
                "gpu", func=lambda: clean_dirs(shader_cache_dirs())),
    # ------------------------------------------------------------ NVIDIA / GPU
    RegTweak("nv_telemetry", "NVIDIA: desativar telemetria",
             "NVIDIA: desliga o serviço NvTelemetryContainer e a coleta de dados do driver. Não afeta FPS nem o driver.",
             "gpu", needs=("HKLM", r"SOFTWARE\NVIDIA Corporation"), ops=_nv_telemetry_ops),
    RegTweak("win_windowed_opt", "Otimizações para jogos em janela",
             "Liga SwapEffectUpgrade e VRR do Windows 11 (Configurações > Gráficos): menos latência em jogos "
             "em janela sem borda / DX10-11.", "gpu", ops=_windowed_opt_ops),
    RegTweak("nv_mpo_off", "NVIDIA/AMD: desativar Multiplane Overlay (MPO)",
             "Corrige travadas, flicker e tela preta em alguns drivers NVIDIA e AMD. Pode aumentar levemente o consumo.",
             "gpu", risk="medium", reboot=True,
             needs=_has_dedicated_gpu,
             ops=[("HKLM", r"SOFTWARE\Microsoft\Windows\Dwm", "OverlayTestMode", DWORD, 5)]),
    RegTweak("amd_ulps_off", "AMD: desativar ULPS (Ultra Low Power State)",
             "Impede a placa Radeon de entrar em estado de energia ultra baixo. Ajuda contra tela preta, "
             "travadas e clock instável; aumenta um pouco o consumo em idle.", "gpu", risk="medium", reboot=True,
             needs=lambda: bool(_amd_ulps_ops()), ops=_amd_ulps_ops),
    # ------------------------------------------------------------ AVANÇADO
    RegTweak("timer_global", "Timer Resolution global (Windows 11)",
             "Restaura o comportamento antigo do timer: a resolução de 0,5 ms pedida por um programa (veja o "
             "controle abaixo) vale para o sistema todo. Menos latência de input e frametimes mais estáveis.",
             "avancado", reboot=True,
             ops=[("HKLM", r"SYSTEM\CurrentControlSet\Control\Session Manager\kernel", "GlobalTimerResolutionRequests", DWORD, 1)]),
    RegTweak("msi_gpu", "Modo MSI na placa de vídeo",
             "Usa interrupções sinalizadas por mensagem (MSI) na GPU: menos latência de DPC. Reversível; "
             "se o driver da placa der problema, desligue e reinicie.",
             "avancado", risk="medium", reboot=True, needs=lambda: bool(_msi_gpu_ops()), ops=_msi_gpu_ops),
    PowercfgTweak("cpu_power_max", "CPU sem economia de energia (na tomada)",
                  "Desativa o core parking, fixa o estado mínimo da CPU em 100% e ativa o boost agressivo. "
                  "Só na tomada; em notebook aumenta calor e ruído das ventoinhas.",
                  "avancado", risk="medium",
                  settings=[("54533251-82be-4824-96c1-47b60b740d00", "0cc5b647-c1df-4637-891a-dec35c318583", 100),
                            ("54533251-82be-4824-96c1-47b60b740d00", "893dee8e-2bef-41e0-89c6-b55d0929964c", 100),
                            ("54533251-82be-4824-96c1-47b60b740d00", "be337238-0d82-4146-a960-4f3749d470c7", 2)]),
    PowercfgTweak("pcie_aspm_off", "PCIe sem economia de energia (ASPM off)",
                  "Desliga o gerenciamento de energia do link PCIe (na tomada): menos latência na GPU e no SSD NVMe.",
                  "avancado", risk="medium",
                  settings=[("501a4d13-42af-4429-9fd1-a8218c268e20", "ee12f906-d277-404b-b6da-e5fa1a576df5", 0)]),
    DnsTweak("dns_cloudflare", "DNS Cloudflare (1.1.1.1) + DNS sobre HTTPS",
             "Troca o DNS das placas de rede ativas pelo da Cloudflare e liga o DoH (Windows 11): resolução de "
             "nomes mais rápida e privada. Volta ao DNS anterior ao desligar.", "avancado", risk="medium"),
    # ------------------------------------------------------------ PRIVACIDADE
    RegTweak("ai_copilot_off", "Desativar o Copilot",
             "Remove o Copilot do Windows por política (usuário e máquina).", "privacidade",
             ops=[("HKCU", r"Software\Policies\Microsoft\Windows\WindowsCopilot", "TurnOffWindowsCopilot", DWORD, 1),
                  ("HKLM", r"SOFTWARE\Policies\Microsoft\Windows\WindowsCopilot", "TurnOffWindowsCopilot", DWORD, 1)]),
    RegTweak("ai_recall_off", "Desativar o Recall (capturas de tela por IA)",
             "Impede o Windows de salvar snapshots da sua atividade para análise por IA.", "privacidade",
             ops=[("HKLM", r"SOFTWARE\Policies\Microsoft\Windows\WindowsAI", "DisableAIDataAnalysis", DWORD, 1),
                  ("HKCU", r"Software\Policies\Microsoft\Windows\WindowsAI", "DisableAIDataAnalysis", DWORD, 1)]),
    RegTweak("ai_clicktodo_off", "Desativar o Click to Do",
             "Desliga as ações de IA sobre o conteúdo da tela (Click to Do).", "privacidade",
             ops=[("HKLM", r"SOFTWARE\Policies\Microsoft\Windows\WindowsAI", "DisableClickToDo", DWORD, 1),
                  ("HKCU", r"Software\Policies\Microsoft\Windows\WindowsAI", "DisableClickToDo", DWORD, 1)]),
    RegTweak("activity_off", "Desativar histórico de atividades",
             "O Windows deixa de registrar e enviar à Microsoft o que você abre e faz.", "privacidade",
             ops=[("HKLM", r"SOFTWARE\Policies\Microsoft\Windows\System", "EnableActivityFeed", DWORD, 0),
                  ("HKLM", r"SOFTWARE\Policies\Microsoft\Windows\System", "PublishUserActivities", DWORD, 0),
                  ("HKLM", r"SOFTWARE\Policies\Microsoft\Windows\System", "UploadUserActivities", DWORD, 0)]),
    RegTweak("widgets_off", "Desativar Widgets e Notícias",
             "Remove o painel de widgets/notícias (economiza RAM e processos em segundo plano).", "privacidade",
             ops=[("HKLM", r"SOFTWARE\Policies\Microsoft\Dsh", "AllowNewsAndInterests", DWORD, 0)]),
    RegTweak("feedback_off", "Sem pedidos de feedback do Windows",
             "Para de exibir pop-ups pedindo sua opinião sobre o Windows.", "privacidade",
             ops=[("HKCU", r"Software\Microsoft\Siuf\Rules", "NumberOfSIUFInPeriod", DWORD, 0)]),
    RegTweak("search_highlights_off", "Desativar destaques de pesquisa",
             "Remove as ilustrações e sugestões dinâmicas da caixa de pesquisa.", "privacidade",
             ops=[("HKCU", r"Software\Microsoft\Windows\CurrentVersion\SearchSettings", "IsDynamicSearchBoxEnabled", DWORD, 0)]),
    RegTweak("wer_off", "Desativar relatório de erros do Windows",
             "Não envia mais relatórios de travamento para a Microsoft.", "privacidade",
             ops=[("HKLM", r"SOFTWARE\Microsoft\Windows\Windows Error Reporting", "Disabled", DWORD, 1)]),
    # ------------------------------------------------------------ SERVIÇOS
    RegTweak("svc_dmwappushservice", 'Push de mensagens WAP', 'Serviço de telemetria/WAP sem uso em PCs desktop e notebooks.',
             "servicos", risk='safe', reboot=True,
             needs=("HKLM", r"SYSTEM\CurrentControlSet\Services\dmwappushservice"),
             ops=[("HKLM", r"SYSTEM\CurrentControlSet\Services\dmwappushservice", "Start", DWORD, 4)]),
    RegTweak("svc_mapsbroker", 'Gerenciador de mapas baixados', 'Só serve para mapas offline do app Mapas.',
             "servicos", risk='safe', reboot=True,
             needs=("HKLM", r"SYSTEM\CurrentControlSet\Services\MapsBroker"),
             ops=[("HKLM", r"SYSTEM\CurrentControlSet\Services\MapsBroker", "Start", DWORD, 4)]),
    RegTweak("svc_retaildemo", 'Modo demonstração de loja', 'Serviço usado só em PCs de vitrine.',
             "servicos", risk='safe', reboot=True,
             needs=("HKLM", r"SYSTEM\CurrentControlSet\Services\RetailDemo"),
             ops=[("HKLM", r"SYSTEM\CurrentControlSet\Services\RetailDemo", "Start", DWORD, 4)]),
    RegTweak("svc_wersvc", 'Relatório de erros do Windows', 'Envia dumps de erro para a Microsoft.',
             "servicos", risk='safe', reboot=True,
             needs=("HKLM", r"SYSTEM\CurrentControlSet\Services\WerSvc"),
             ops=[("HKLM", r"SYSTEM\CurrentControlSet\Services\WerSvc", "Start", DWORD, 4)]),
    RegTweak("svc_fax", 'Fax', 'Serviço de fax, sem uso na maioria dos PCs.',
             "servicos", risk='safe', reboot=True,
             needs=("HKLM", r"SYSTEM\CurrentControlSet\Services\Fax"),
             ops=[("HKLM", r"SYSTEM\CurrentControlSet\Services\Fax", "Start", DWORD, 4)]),
    RegTweak("svc_remoteregistry", 'Registro remoto', 'Permite editar o registro pela rede: melhor deixar desligado por segurança.',
             "servicos", risk='safe', reboot=True,
             needs=("HKLM", r"SYSTEM\CurrentControlSet\Services\RemoteRegistry"),
             ops=[("HKLM", r"SYSTEM\CurrentControlSet\Services\RemoteRegistry", "Start", DWORD, 4)]),
    RegTweak("svc_lfsvc", 'Serviço de geolocalização', 'Localização para apps. Desative se não usa Mapas/Clima por GPS.',
             "servicos", risk='safe', reboot=True,
             needs=("HKLM", r"SYSTEM\CurrentControlSet\Services\lfsvc"),
             ops=[("HKLM", r"SYSTEM\CurrentControlSet\Services\lfsvc", "Start", DWORD, 4)]),
    RegTweak("svc_wpcmonsvc", 'Controle dos pais', 'Só necessário com contas infantis da Microsoft.',
             "servicos", risk='safe', reboot=True,
             needs=("HKLM", r"SYSTEM\CurrentControlSet\Services\WpcMonSvc"),
             ops=[("HKLM", r"SYSTEM\CurrentControlSet\Services\WpcMonSvc", "Start", DWORD, 4)]),
    RegTweak("svc_scardsvr", 'Cartão inteligente', 'Só para leitores de smart card.',
             "servicos", risk='safe', reboot=True,
             needs=("HKLM", r"SYSTEM\CurrentControlSet\Services\SCardSvr"),
             ops=[("HKLM", r"SYSTEM\CurrentControlSet\Services\SCardSvr", "Start", DWORD, 4)]),
    RegTweak("svc_trkwks", 'Rastreamento de links distribuídos', 'Serviço de rede corporativa sem uso em casa.',
             "servicos", risk='safe', reboot=True,
             needs=("HKLM", r"SYSTEM\CurrentControlSet\Services\TrkWks"),
             ops=[("HKLM", r"SYSTEM\CurrentControlSet\Services\TrkWks", "Start", DWORD, 4)]),
    RegTweak("svc_wisvc", 'Windows Insider', 'Necessário só para o programa Insider.',
             "servicos", risk='safe', reboot=True,
             needs=("HKLM", r"SYSTEM\CurrentControlSet\Services\wisvc"),
             ops=[("HKLM", r"SYSTEM\CurrentControlSet\Services\wisvc", "Start", DWORD, 4)]),
    RegTweak("svc_phonesvc", 'Serviço de telefone', 'Gerencia estado de chamadas em dispositivos com modem.',
             "servicos", risk='safe', reboot=True,
             needs=("HKLM", r"SYSTEM\CurrentControlSet\Services\PhoneSvc"),
             ops=[("HKLM", r"SYSTEM\CurrentControlSet\Services\PhoneSvc", "Start", DWORD, 4)]),
    RegTweak("svc_sysmain", 'SysMain (Superfetch)', 'Pré-carrega apps na RAM. Ajuda em HDD, quase inútil em SSD e usa disco/RAM à toa.',
             "servicos", risk='medium', reboot=True,
             needs=("HKLM", r"SYSTEM\CurrentControlSet\Services\SysMain"),
             ops=[("HKLM", r"SYSTEM\CurrentControlSet\Services\SysMain", "Start", DWORD, 4)]),
    RegTweak("svc_wsearch", 'Windows Search (indexação)', 'Reduz uso de disco/CPU, mas a busca de arquivos do Windows fica mais lenta.',
             "servicos", risk='medium', reboot=True,
             needs=("HKLM", r"SYSTEM\CurrentControlSet\Services\WSearch"),
             ops=[("HKLM", r"SYSTEM\CurrentControlSet\Services\WSearch", "Start", DWORD, 4)]),
    RegTweak("svc_spooler", 'Spooler de impressão', 'Só desative se você não usa impressora (nem PDF virtual).',
             "servicos", risk='medium', reboot=True,
             needs=("HKLM", r"SYSTEM\CurrentControlSet\Services\Spooler"),
             ops=[("HKLM", r"SYSTEM\CurrentControlSet\Services\Spooler", "Start", DWORD, 4)]),
]
BY_ID = {t.id: t for t in TWEAKS}

PROFILES = {
    "Gaming": [t.id for t in TWEAKS if t.category == G and t.risk == "safe"] +
              ["bg_apps_off", "ads_off", "fast_startup_off", "transparency_off", "startup_delay_off",
               "nv_telemetry", "win_windowed_opt", "timer_global"],
    "Geral": [t.id for t in TWEAKS if t.category in (X, "privacidade") and t.risk == "safe"],
    "Gaming Extremo": [t.id for t in TWEAKS if t.category in (G, X, "gpu", "avancado", "privacidade") and t.reversible],
}


# ---------------------------------------------------------------- estado / backup
def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)


def apply_tweak(tw):
    """Aplica um tweak guardando o estado original (sem sobrescrever backup antigo)."""
    result = tw.apply()
    if tw.reversible:
        state = load_state()
        state.setdefault(tw.id, result)
        save_state(state)
    return result


def revert_tweak(tw):
    state = load_state()
    if tw.id not in state:
        raise RuntimeError("Sem backup deste ajuste (ele não foi aplicado pelo Skore Optimizer).")
    tw.revert(state.pop(tw.id))
    save_state(state)


def create_restore_point():
    code, out = run(["powershell", "-NoProfile", "-Command",
                     "Checkpoint-Computer -Description 'Skore Optimizer' -RestorePointType MODIFY_SETTINGS -ErrorAction Stop"])
    return code == 0, out.strip()


def hardware_info():
    ps = ("$c=Get-CimInstance Win32_Processor|select -First 1;"
          "$g=(Get-CimInstance Win32_VideoController|%{$_.Name}) -join ' | ';"
          "$m=Get-CimInstance Win32_ComputerSystem;"
          "[pscustomobject]@{cpu=$c.Name.Trim();cores=$c.NumberOfCores;threads=$c.NumberOfLogicalProcessors;"
          "gpu=$g;ram=[math]::Round($m.TotalPhysicalMemory/1GB);model=($m.Manufacturer+' '+$m.Model)}|ConvertTo-Json")
    code, out = run(["powershell", "-NoProfile", "-Command", ps])
    try:
        return json.loads(out)
    except ValueError:
        return {}


# ---------------------------------------------------------------- debloat de apps da Microsoft
# (padrão do nome do pacote, nome amigável, descrição). Nada essencial (Store, Calculadora,
# Fotos, Terminal, Xbox/Game Bar etc.) está na lista.
BLOAT = [
    ("Microsoft.BingNews", "Notícias", "Feed de notícias da Microsoft"),
    ("Microsoft.BingWeather", "Clima", "App de previsão do tempo"),
    ("Microsoft.BingSearch", "Bing Search", "Componente de busca web"),
    ("Microsoft.BingFinance", "Finanças", "App de finanças do Bing"),
    ("Microsoft.BingSports", "Esportes", "App de esportes do Bing"),
    ("Microsoft.GetHelp", "Obter Ajuda", "Suporte da Microsoft"),
    ("Microsoft.Getstarted", "Dicas", "Dicas e primeiros passos"),
    ("Microsoft.MicrosoftOfficeHub", "Microsoft 365 (Office)", "Atalho de anúncio do Office"),
    ("Microsoft.MicrosoftSolitaireCollection", "Solitaire Collection", "Jogos de cartas com anúncios"),
    ("Microsoft.People", "Pessoas", "Contatos"),
    ("Microsoft.PowerAutomateDesktop", "Power Automate", "Automação de tarefas"),
    ("Microsoft.Todos", "Microsoft To Do", "Lista de tarefas"),
    ("Microsoft.WindowsFeedbackHub", "Hub de Comentários", "Envio de feedback à Microsoft"),
    ("Microsoft.WindowsMaps", "Mapas", "Mapas offline/online"),
    ("Microsoft.ZuneVideo", "Filmes e TV", "Player de vídeo da loja"),
    ("Microsoft.YourPhone", "Vincular ao Celular", "Phone Link"),
    ("Microsoft.549981C3F5F10", "Cortana", "Assistente descontinuado"),
    ("Microsoft.SkypeApp", "Skype", "Mensageiro"),
    ("Microsoft.WindowsCommunicationsApps", "Email e Calendário", "Apps antigos de e-mail"),
    ("Microsoft.OutlookForWindows", "Novo Outlook", "Substituto do app de e-mail"),
    ("Microsoft.MixedReality.Portal", "Realidade Mista", "Portal de VR"),
    ("Microsoft.Microsoft3DViewer", "Visualizador 3D", "Modelos 3D"),
    ("Microsoft.Print3D", "Print 3D", "Impressão 3D"),
    ("Microsoft.OneConnect", "Planos móveis", "App de planos de celular"),
    ("Microsoft.Wallet", "Carteira", "Pagamentos da Microsoft"),
    ("Microsoft.Copilot", "Copilot", "Assistente de IA"),
    ("Microsoft.Windows.DevHome", "Dev Home", "Painel para desenvolvedores"),
    ("MicrosoftTeams", "Teams (pessoal)", "Chat pessoal"),
    ("MSTeams", "Teams", "Chat pessoal (novo)"),
    ("Clipchamp.Clipchamp", "Clipchamp", "Editor de vídeo"),
    ("*CandyCrush*", "Candy Crush", "Jogo promovido"),
    ("*Disney*", "Disney+", "App promovido"),
    ("*Spotify*", "Spotify", "App promovido (pode reinstalar pela Store)"),
    ("*TikTok*", "TikTok", "App promovido"),
    ("*Facebook*", "Facebook", "App promovido"),
    ("*Instagram*", "Instagram", "App promovido"),
    ("*Netflix*", "Netflix", "App promovido"),
    ("*AmazonPrimeVideo*", "Prime Video", "App promovido"),
    ("*LinkedIn*", "LinkedIn", "App promovido"),
]


def list_bloat():
    """Retorna [(nome_amigável, descrição, PackageFullName)] dos apps instalados no usuário atual."""
    import fnmatch
    code, out = run(["powershell", "-NoProfile", "-Command",
                     "Get-AppxPackage | Select-Object Name,PackageFullName | ConvertTo-Json -Compress"])
    try:
        pk = json.loads(out)
    except ValueError:
        return []
    if isinstance(pk, dict):
        pk = [pk]
    found, seen = [], set()
    for pattern, friendly, desc in BLOAT:
        for p in pk:
            if p["PackageFullName"] not in seen and fnmatch.fnmatch(p["Name"].lower(), pattern.lower()):
                seen.add(p["PackageFullName"])
                found.append((friendly, desc, p["PackageFullName"]))
    return found


def remove_app(full_name):
    """Remove o app só para o usuário atual. Reinstalação: Microsoft Store."""
    code, out = run(["powershell", "-NoProfile", "-Command",
                     f"Remove-AppxPackage -Package '{full_name}' -ErrorAction Stop"])
    if code != 0:
        raise RuntimeError(out.strip().splitlines()[0] if out.strip() else "falha ao remover")


# ---------------------------------------------------------------- programas de inicialização
RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN32 = r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"
APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"


def _approved_path(run_path):
    return APPROVED + (r"\Run32" if "WOW6432Node" in run_path else r"\Run")


def list_startup():
    """[{name, command, hive, run_path, enabled}] das chaves Run (HKCU/HKLM)."""
    items = []
    for hive, path in [("HKCU", RUN), ("HKLM", RUN), ("HKLM", RUN32)]:
        try:
            with winreg.OpenKey(HIVES[hive], path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
                i = 0
                while True:
                    try:
                        name, cmd, _ = winreg.EnumValue(k, i)
                    except OSError:
                        break
                    i += 1
                    flag = reg_read(hive, _approved_path(path), name)
                    enabled = not (flag and isinstance(flag[0], bytes) and flag[0][:1] in (b"\x03", b"\x07"))
                    items.append({"name": name, "command": str(cmd), "hive": hive, "run_path": path, "enabled": enabled})
        except OSError:
            pass
    return items


def set_startup(item, enabled):
    """Habilita/desabilita como o Gerenciador de Tarefas faz (reversível, não apaga a entrada)."""
    data = bytes([2 if enabled else 3]) + b"\x00" * 11
    reg_write(item["hive"], _approved_path(item["run_path"]), item["name"], winreg.REG_BINARY, data)


# ---------------------------------------------------------------- NVIDIA / GPU
def gpu_stats():
    """Lê a GPU NVIDIA via nvidia-smi. Retorna dict ou None se não houver GPU/driver NVIDIA."""
    q = "name,driver_version,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw,clocks.gr,pstate"
    try:
        code, out = run(["nvidia-smi", f"--query-gpu={q}", "--format=csv,noheader,nounits"])
    except OSError:
        return None
    if code != 0 or not out.strip():
        return None
    f = [x.strip() for x in out.strip().splitlines()[0].split(",")]
    if len(f) < 9:
        return None

    def num(v):
        try:
            return float(v)
        except ValueError:
            return None
    return {"name": f[0], "driver": f[1], "temp": num(f[2]), "util": num(f[3]), "mem_used": num(f[4]),
            "mem_total": num(f[5]), "power": num(f[6]), "clock": num(f[7]), "pstate": f[8]}


GPU_LABEL = {"1": "Economia (Intel)", "2": "Alto desempenho (NVIDIA)", "0": "Padrão do Windows"}


def gpu_pref_list():
    """[(caminho_exe, preferência)] dos apps com GpuPreference definido no Windows."""
    items = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, GPU_PREFS, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            i = 0
            while True:
                try:
                    name, val, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                i += 1
                kv = kv_parse(str(val))
                if name != "DirectXUserGlobalSettings" and "GpuPreference" in kv:
                    items.append((name, kv["GpuPreference"]))
    except OSError:
        pass
    return items


def gpu_pref_set(exe, pref="2"):
    """Força o app a usar a GPU dedicada (2) preservando outras opções do valor."""
    cur = reg_read("HKCU", GPU_PREFS, exe)
    d = kv_parse(cur[0] if cur else "")
    d["GpuPreference"] = pref
    reg_write("HKCU", GPU_PREFS, exe, SZ, kv_build(d))


def gpu_pref_remove(exe):
    cur = reg_read("HKCU", GPU_PREFS, exe)
    d = kv_parse(cur[0] if cur else "")
    d.pop("GpuPreference", None)
    if d:
        reg_write("HKCU", GPU_PREFS, exe, SZ, kv_build(d))
    else:
        reg_delete("HKCU", GPU_PREFS, exe)


def open_nvidia_panel():
    """Abre o Painel de Controle NVIDIA (app da Store ou versão clássica)."""
    for cmd in (["explorer.exe", r"shell:appsFolder\NVIDIACorp.NVIDIAControlPanel_56jybvy8sckqj!NVIDIACorp.NVIDIAControlPanel"],
                [r"C:\Program Files\NVIDIA Corporation\Control Panel Client\nvcplui.exe"]):
        try:
            subprocess.Popen(cmd, creationflags=NO_WINDOW)
            return True
        except OSError:
            continue
    return False


def gpu_stats_generic():
    """Monitor por contadores do Windows (funciona com AMD/Intel): nome, driver, uso 3D e VRAM usada."""
    ps = ("$e=Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine -ErrorAction SilentlyContinue;"
          "$u=($e|?{$_.Name -like '*engtype_3D*'}|measure UtilizationPercentage -Sum).Sum;"
          "$m=Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUAdapterMemory -ErrorAction SilentlyContinue;"
          "$v=($m|measure DedicatedUsage -Sum).Sum/1MB;"
          "[pscustomobject]@{util=$u;vram=$v}|ConvertTo-Json -Compress")
    code, out = run(["powershell", "-NoProfile", "-Command", ps])
    try:
        d = json.loads(out)
    except ValueError:
        return None
    amd = [desc for _, desc in display_adapters() if any(x in desc.lower() for x in ("amd", "radeon"))]
    drv = reg_read("HKLM", CLASS_DISPLAY + "\\" + next((s for s, dsc in display_adapters() if dsc in amd), "0000"),
                   "DriverVersion")
    return {"name": " + ".join(amd) or "GPU", "driver": str(drv[0]) if drv else "?",
            "temp": None, "util": min(float(d.get("util") or 0), 100.0), "mem_used": float(d.get("vram") or 0),
            "mem_total": None, "power": None, "clock": None, "pstate": None, "generic": True}


def open_radeon_software():
    """Abre o AMD Software: Adrenalin Edition."""
    for exe in (r"C:\Program Files\AMD\CNext\CNext\RadeonSoftware.exe",
                r"C:\Program Files\AMD\CNext\CNext\cncmd.exe"):
        if os.path.exists(exe):
            subprocess.Popen([exe], creationflags=NO_WINDOW)
            return True
    return False
