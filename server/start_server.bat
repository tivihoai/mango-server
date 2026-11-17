@echo off
cd /d C:\MangoMCPServer\server
C:\MangoMCP\python\python.exe run_server.py start --data-dir C:\MangoMCPServer\data --host 127.0.0.1 --port 8443 >> C:\MangoMCPServer\server.log 2>&1
