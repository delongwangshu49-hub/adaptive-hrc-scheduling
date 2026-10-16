if ($PSVersionTable.PSVersion.Major -ne 7) { throw 'PowerShell 7 required' }
& 'D:/Dev/tools/isaac-sim-6.1/python.bat' @args
exit $LASTEXITCODE
