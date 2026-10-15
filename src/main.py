"""Script de entrada usado pelo CapturePro.exe."""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _fatal(msg: str) -> None:
    """Mostra o erro mesmo que a interface (Qt) não consiga carregar."""
    try:
        base = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "CapturePro")
        os.makedirs(base, exist_ok=True)
        with open(os.path.join(base, "erro-inicializacao.log"), "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except OSError:
        pass
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None, "O Capture Pro não conseguiu iniciar.\n\n" + msg[-1500:] +
                "\n\nSe o problema continuar, reinstale o programa.", "Capture Pro", 0x10)
            return
        except Exception:
            pass
    sys.stderr and sys.stderr.write(msg)


if __name__ == "__main__":
    try:
        from capturepro.app import main
        code = main()
    except SystemExit:
        raise
    except BaseException:
        _fatal(traceback.format_exc())
        code = 1
    sys.exit(code)
