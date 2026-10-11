# Skore Optimizer (protótipo)

Otimizador de Windows focado em gaming. Python + CustomTkinter.

## Baixar e instalar em outro PC (Windows 10/11, sem instalar nada)
O programa é um único arquivo, `SkoreOptimizer.exe`, que **já leva dentro dele tudo o que precisa** (Python, interface, bibliotecas).
O outro PC **não precisa ter Python** nem instalar nada.

1. Nesta página do repositório, clique em **Code → Download ZIP** (logado na sua conta do GitHub).
2. **Extraia o ZIP** (botão direito → Extrair tudo). Não rode de dentro do ZIP.
3. Dê dois cliques em **`SkoreOptimizer.exe`** e aceite o pedido de administrador.
   Se aparecer "O Windows protegeu o seu PC": **Mais informações → Executar assim mesmo** (o programa ainda não tem assinatura digital paga).

Também dá para baixar só o `.exe` pela aba **Releases**.

**Se o app não abrir:** o Windows mostra uma janela com o motivo, e os detalhes ficam em `%APPDATA%\SkoreOptimizer\erro.log`.
Outras causas possíveis: o antivírus bloqueou o arquivo, ou o Windows é anterior ao 10.

> `SkoreOptimizer.bat` é só um atalho: se o `.exe` estiver na mesma pasta, ele o abre; senão, tenta rodar pelo código-fonte (precisa de Python 3.10+).

## Rodar
- `dist/SkoreOptimizer.exe` (pede administrador) ou `SkoreOptimizer.bat` (usa Python).
- Dev sem elevação: `python app.py --noadmin`
- Recompilar (depois, copie `dist/SkoreOptimizer.exe` para a raiz do repositório, que é o `.exe` que vai no "Baixar ZIP"): `python -m PyInstaller --noconfirm --onefile --noconsole --uac-admin --name SkoreOptimizer --icon assets/icon.ico --add-data "assets;assets" --collect-all customtkinter app.py`

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
