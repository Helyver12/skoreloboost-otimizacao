@echo off
title Skore Optimizer
cd /d "%~dp0"

REM Procura o Python (comando "python" ou o atalho "py"). O falso "python" da Microsoft Store nao conta.
set "PY="
python -c "import sys" >nul 2>&1 && set "PY=python"
if not defined PY py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY goto SEM_PYTHON

REM Na primeira vez, instala as bibliotecas que o app usa.
%PY% -c "import customtkinter, psutil, PIL" >nul 2>&1
if errorlevel 1 (
  echo Instalando as bibliotecas do app ^(so na primeira vez, pode levar 1 minuto^)...
  %PY% -m pip install -r requirements.txt
  if errorlevel 1 goto ERRO
)

%PY% app.py %*
if errorlevel 1 goto ERRO
exit /b 0

:SEM_PYTHON
echo.
echo  NAO ENCONTREI O PYTHON NESTE PC.
echo.
echo  Duas opcoes:
echo   1^) A mais facil: baixe o SkoreOptimizer.exe na aba "Releases" do
echo      repositorio no GitHub. Esse arquivo nao precisa de Python.
echo   2^) Instale o Python 3.10 ou mais novo em https://www.python.org/downloads/
echo      marcando a caixa "Add python.exe to PATH". Depois abra este arquivo de novo.
echo.
pause
exit /b 1

:ERRO
echo.
echo  O programa nao conseguiu abrir. Tire um print desta janela e mande para o suporte.
echo  Se existir, o arquivo %%APPDATA%%\SkoreOptimizer\erro.log tem os detalhes.
echo.
pause
exit /b 1
