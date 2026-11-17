@echo off
rem Starts Mouser without a console window. Put a shortcut to this file in
rem shell:startup to have it run when you sign in (add --background there).
start "" pythonw -I "%~dp0run.pyw" %*
