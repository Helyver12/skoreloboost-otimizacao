# Skore Optimizer (protótipo)

Otimizador de Windows focado em gaming. Python + CustomTkinter.

## Baixar e instalar em outro PC (Windows 10/11)
**Jeito mais fácil (não precisa de Python):**
1. Abra a aba **Releases** deste repositório (à direita, na página principal) e entre no GitHub com a sua conta.
2. Baixe o `SkoreOptimizer.exe` da versão mais recente.
3. Dê dois cliques e aceite o pedido de administrador.
   Se aparecer "O Windows protegeu o seu PC": **Mais informações → Executar assim mesmo** (o programa ainda não tem assinatura digital paga).

> O repositório em si **não contém o `.exe`**: ele fica só nas Releases. Se você clonar ou baixar o ZIP do repositório,
> o que vem é o código-fonte e o `SkoreOptimizer.bat`, que precisa do Python (veja abaixo).

**Pelo código-fonte (precisa de Python 3.10+ com "Add python.exe to PATH"):**
dê dois cliques em `SkoreOptimizer.bat`. Na primeira vez ele instala as bibliotecas sozinho. Se faltar o Python, ele avisa o que fazer.

**Se o app não abrir:** o Windows mostra uma janela com o motivo, e os detalhes ficam em `%APPDATA%\SkoreOptimizer\erro.log`.

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
