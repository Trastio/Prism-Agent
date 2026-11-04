$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut('C:\Users\<you>\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\Prism-Agent-autostart.lnk')
$lnk.TargetPath = 'C:\Users\<you>\Anaconda3\pythonw.exe'
$lnk.Arguments = '"C:\Users\<you>\Desktop\Prism-Agent\prism.py" start'
$lnk.WorkingDirectory = 'C:\Users\<you>\Desktop\Prism-Agent'
$lnk.Description = 'Prism-Agent autostart'
$lnk.Save()
