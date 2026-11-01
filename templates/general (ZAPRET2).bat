@echo off
chcp 65001 > nul
:: 65001 - UTF-8
:: Zapret2 (winws2 / Lua) general strategy

cd /d "%~dp0"
call service.bat load_game_filter
call service.bat load_user_lists
echo:

set "BIN=%~dp0bin\"
set "LISTS=%~dp0lists\"
set "LUA=%~dp0lua\"
set "FAKE=%~dp0files\fake\"
cd /d %BIN%

start "zapret2: %~n0" /min "%BIN%winws2.exe" ^
 --wf-tcp-out=80,443,2053,2083,2087,2096,8443,%GameFilterTCP% ^
 --wf-udp-out=443,19294-19344,50000-50100,%GameFilterUDP% ^
 --lua-init=@"%LUA%zapret-lib.lua" ^
 --lua-init=@"%LUA%zapret-antidpi.lua" ^
 --lua-init="fake_default_tls = tls_mod(fake_default_tls,'rnd,dupsid')" ^
 --blob=quic_google:@"%FAKE%quic_initial_www_google_com.bin" ^
 --blob=tls_google:@"%FAKE%tls_clienthello_www_google_com.bin" ^
 --blob=discord_udp:@"%BIN%ACTIVE_DISCORD_UDP.bin" ^
 --filter-tcp=443,2053,2083,2087,2096,8443 --filter-l7=tls --hostlist="%LISTS%list-general.txt" --hostlist="%LISTS%list-general-user.txt" --hostlist-exclude="%LISTS%list-exclude.txt" --hostlist-exclude="%LISTS%list-exclude-user.txt" ^
   --out-range=-d10 ^
   --payload=tls_client_hello ^
   --lua-desync=fake:blob=fake_default_tls:tcp_md5:repeats=6 ^
   --lua-desync=multidisorder:pos=1,midsld ^
 --new ^
 --filter-tcp=443 --filter-l7=tls --hostlist="%LISTS%list-google.txt" ^
   --out-range=-d10 ^
   --payload=tls_client_hello ^
   --lua-desync=fake:blob=tls_google:tcp_md5:tls_mod=rnd,dupsid,sni=www.google.com:repeats=6 ^
   --lua-desync=multidisorder:pos=1,midsld ^
 --new ^
 --filter-tcp=80 --filter-l7=http --hostlist="%LISTS%list-general.txt" --hostlist="%LISTS%list-general-user.txt" ^
   --out-range=-d10 ^
   --payload=http_req ^
   --lua-desync=fake:blob=fake_default_http:tcp_md5:repeats=4 ^
   --lua-desync=multisplit:pos=method+2,midsld ^
 --new ^
 --filter-udp=443 --filter-l7=quic --hostlist="%LISTS%list-general.txt" --hostlist="%LISTS%list-general-user.txt" ^
   --payload=quic_initial ^
   --lua-desync=fake:blob=quic_google:repeats=6 ^
 --new ^
 --filter-udp=443 --filter-l7=quic ^
   --payload=quic_initial ^
   --lua-desync=fake:blob=fake_default_quic:repeats=6 ^
 --new ^
 --filter-udp=19294-19344,50000-50100 --filter-l7=discord,stun ^
   --payload=discord_ip_discovery,stun ^
   --lua-desync=fake:blob=discord_udp:repeats=2
