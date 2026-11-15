on run
	set dashDir to (POSIX path of (path to home folder)) & "straude-dashboard"
	set statusCode to "000"
	try
		set statusCode to do shell script "curl -s -o /dev/null -m 1 -w '%{http_code}' http://localhost:8934/api/data"
	end try
	if statusCode is "200" then
		do shell script "open http://localhost:8934/"
	else
		-- Solo el python va en segundo plano y con stdin/stdout/stderr desconectados:
		-- si algo queda con el pipe de "do shell script" abierto, la app nunca
		-- termina y bloquea el apagado de la Mac.
		do shell script "cd " & quoted form of dashDir & " || exit 1; DO_NOT_TRACK=1 nohup /usr/bin/python3 server.py > /tmp/straude-dashboard.log 2>&1 < /dev/null &"
	end if
end run
