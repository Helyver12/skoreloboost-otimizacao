@echo off
title Skore Optimizer
cd /d "%~dp0"

REM 1) Se o SkoreOptimizer.exe estiver nesta pasta, abre ele (nao precisa de Python nem de nada instalado).
if exist "%~dp0SkoreOptimizer.exe" (
  start "" "%~dp0SkoreOptimizer.exe" %*
  exit /b 0
)

REM 2) Sem o .exe: tenta rodar pelo codigo-fonte. Procura o Python (comando "python" ou o atalho "py").
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
echo  NAO ENCONTREI O SkoreOptimizer.exe NEM O PYTHON NESTA PASTA/PC.
echo.
echo  Baixe o SkoreOptimizer.exe na aba "Releases" do repositorio no GitHub
echo  e deixe-o na mesma pasta deste arquivo (ele nao precisa de Python).
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