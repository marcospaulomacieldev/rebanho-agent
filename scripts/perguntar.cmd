@echo off
rem Abre o assistente do rebanho em modo de teste (Windows).
rem Uso:
rem   scripts\perguntar.cmd                       abre o modo interativo
rem   scripts\perguntar.cmd "sua pergunta"        faz uma pergunta e sai
rem   scripts\perguntar.cmd "pergunta" --mostrar-chamadas
rem Roda a partir da raiz do projeto, com o Python do ambiente virtual (.venv).
pushd "%~dp0.."
".venv\Scripts\python.exe" -m app.ask %*
set CODIGO=%ERRORLEVEL%
popd
exit /b %CODIGO%
