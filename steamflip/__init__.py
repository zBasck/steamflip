"""steamflip — analisador de oportunidades de revenda no mercado Steam."""

__version__ = "0.1.0"
__all__ = ["__version__"]

# Se ``config_local.py`` existir, sobrescreve as variáveis de ``config.py``
# em runtime. Isso permite o usuário manter suas credenciais reais fora do
# Git (o ``.gitignore`` blinda ``config_local.py``) sem mudar nenhum import.
import importlib
import sys
from pathlib import Path

_pkg_dir = Path(__file__).resolve().parent
_local_cfg = _pkg_dir / "config_local.py"
if _local_cfg.is_file():
    spec = importlib.util.spec_from_file_location(
        "steamflip.config_local", _local_cfg
    )
    if spec and spec.loader:
        _mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_mod)
        # Sobrescreve o módulo já importado (``steamflip.config``).
        import steamflip.config as _cfg_mod

        for _name in dir(_mod):
            if _name.startswith("_"):
                continue
            setattr(_cfg_mod, _name, getattr(_mod, _name))
