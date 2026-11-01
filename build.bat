@echo off
chcp 65001 >nul
rem Сборка fuzzer.exe и установщика. Для exe без Inno: build.bat --skip-inno
python scripts\build_installer.py %*
