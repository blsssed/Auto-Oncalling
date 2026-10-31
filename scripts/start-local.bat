@echo off
setlocal EnableExtensions

set "ROOT_DIR=%~dp0.."
cd /d "%ROOT_DIR%"

where docker >nul 2>nul || (echo 缺少必需命令：docker & exit /b 1)
where npm >nul 2>nul || (echo 缺少必需命令：npm & exit /b 1)
where uv >nul 2>nul || (echo 缺少必需命令：uv & exit /b 1)
where cls-mcp-server >nul 2>nul || (echo 缺少必需命令：cls-mcp-server & exit /b 1)

if not exist "config\project.json" (
  echo 缺少配置文件：config\project.json
  echo 请先执行：copy config\project.template.json config\project.json
  exit /b 1
)

for /f "usebackq delims=" %%A in (`powershell -NoProfile -Command "function Merge-Config($base,$override){ foreach($p in $override.PSObject.Properties){ if($null -ne $base.($p.Name) -and $base.($p.Name) -is [pscustomobject] -and $p.Value -is [pscustomobject]){ Merge-Config $base.($p.Name) $p.Value } else { $base ^| Add-Member -NotePropertyName $p.Name -NotePropertyValue $p.Value -Force } }; $base }; $config = Get-Content -Raw -Encoding UTF8 'config/project.json' ^| ConvertFrom-Json; if(Test-Path 'config/user.project.json'){ $user = Get-Content -Raw -Encoding UTF8 'config/user.project.json' ^| ConvertFrom-Json; $config = Merge-Config $config $user }; Write-Output ('TRANSPORT=' + $config.clsMcpServer.transport); Write-Output ('PORT=' + $config.clsMcpServer.port); Write-Output ('BACKEND_PORT=' + $(if ($config.backend -and $config.backend.port) { $config.backend.port } else { 8000 })); Write-Output ('TENCENTCLOUD_SECRET_ID=' + $config.clsMcpServer.secretId); Write-Output ('TENCENTCLOUD_SECRET_KEY=' + $config.clsMcpServer.secretKey); Write-Output ('TZ=' + $config.clsMcpServer.timezone)"`) do set "%%A"

if not defined PORT (
  echo 未能从 config\project.json 读取 clsMcpServer.port，请检查配置文件是否有效
  exit /b 1
)
if not defined BACKEND_PORT set "BACKEND_PORT=8000"

docker compose -f infra/compose.yaml up -d etcd minio milvus attu alertmanager prometheus
if errorlevel 1 (
  echo docker compose 启动失败，请确认 Docker Desktop 已启动
  exit /b 1
)

pushd apps\backend
if not exist var mkdir var
uv sync
if errorlevel 1 exit /b 1
uv run alembic upgrade head
if errorlevel 1 exit /b 1
netstat -ano | findstr /c:":%PORT% " >nul 2>nul
if errorlevel 1 (
  start "Agent Py CLS MCP" /D "%CD%" cmd /c "cls-mcp-server > var\cls-mcp-server-local.log 2>&1"
) else (
  echo 端口 %PORT% 已被占用，跳过 CLS MCP 启动
)

netstat -ano | findstr /c:":%BACKEND_PORT% " >nul 2>nul
if errorlevel 1 (
  start "Agent Py Backend" /D "%CD%" cmd /c "uv run uvicorn super_ai.api.app:create_app --factory --host 127.0.0.1 --port %BACKEND_PORT% > var\backend-local.log 2>&1"
) else (
  echo 端口 %BACKEND_PORT% 已被占用，跳过后端启动
)
popd

pushd apps\frontend
if not exist node_modules npm install
if errorlevel 1 exit /b 1
netstat -ano | findstr /c:":5173 " >nul 2>nul
if errorlevel 1 (
  start "Agent Py Frontend" /D "%CD%" cmd /c "npm run dev -- --host 127.0.0.1 > ..\backend\var\frontend-local.log 2>&1"
) else (
  echo 端口 5173 已被占用，跳过前端启动
)
popd

echo 前端：     http://127.0.0.1:5173
echo 后端：     http://127.0.0.1:%BACKEND_PORT%
echo MCP SSE：  http://127.0.0.1:%PORT%/sse
echo 本地日志： apps\backend\var
