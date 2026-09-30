# Skore Optimizer (protótipo)

Otimizador de Windows focado em gaming. Python + CustomTkinter.

## Instalar em outro PC
```
git clone <URL-do-repositório>
cd <pasta>
pip install -r requirements.txt
python app.py
```
Precisa de Windows 10/11 e Python 3.10+. O app pede administrador ao abrir.

## Rodar
- `dist/SkoreOptimizer.exe` (pede administrador) ou `SkoreOptimizer.bat` (usa Python).
- Dev sem elevação: `python app.py --noadmin`
- Recompilar: `python -m PyInstaller --noconfirm --onefile --noconsole --uac-admin --name SkoreOptimizer --icon assets/icon.ico --add-data "assets;assets" --collect-all customtkinter app.py`

## Estrutura
- `tweaks.py` — motor: `RegTweak`, `PowercfgTweak`, `DnsTweak`, `PowerPlanTweak`, `ActionTweak`, lista `TWEAKS`, `PROFILES`, `BLOAT`, startup, GPU, backup.
- `games.py` — catálogo de jogos (`GAMES`), detecção do .exe e opções por jogo (GPU, FSO, prioridade).
- `winget_store.py` — catálogo de apps (`CATALOG`) e comandos do WinGet.
- `app.py` — interface (uma função `_page_*` por aba).

## Adicionar um ajuste
Em `tweaks.py`, acrescente na lista `TWEAKS`:

    RegTweak("meu_id", "Título", "Descrição", "gaming", risk="safe",
             ops=[("HKLM", r"SOFTWARE\...", "Nome", DWORD, 1)])

Categorias: gaming, geral, gpu, avancado, privacidade, servicos, limpeza. Ele aparece sozinho na aba da categoria, com interruptor e reversão automática.
Para entrar em um perfil, use o id em `PROFILES`.

## Backup
Valores originais ficam em `%APPDATA%/SkoreOptimizer/backup.json`.

## Benchmark
Medições ficam em `%APPDATA%/SkoreOptimizer/benchmarks.json`.
