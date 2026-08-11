"""Redirige al backend local las URLs de AWS incrustadas en los binarios.

Los servicios de cuentas, patterns, achievements, stats y reports llevan la URL
fija dentro del .exe (a diferencia del de sesiones, que se lee de Engine.ini).
Este script las reescribe in-place.

La cadena nueva es mas corta que la original y se rellena con ceros, de modo
que wcslen() en tiempo de ejecucion lea la nueva y nada se desplace en el
binario: el tamano del fichero no cambia ni un byte.

Uso:
    python redirect_urls.py --url http://127.0.0.1:8080/          # aplicar
    python redirect_urls.py --restore                             # volver al original
"""

import argparse
import os
import re
import shutil
import tempfile
from pathlib import Path

TARGETS = [
    Path(
        r"C:\Program Files (x86)\Steam\steamapps\common\Memories of Mars"
        r"\MarsClient\Game\Binaries\Win64\MemoriesOfMars.exe"
    ),
    Path(
        r"C:\Program Files (x86)\Steam\steamapps\common\Memories of Mars - Dedicated Server"
        r"\Game\Binaries\Win64\MemoriesOfMarsServer.exe"
    ),
]

# https://<id>.execute-api.<region>.amazonaws.com/Prod/
PATTERN = re.compile(
    r"https://[a-z0-9]{8,12}\.execute-api\.[a-z0-9-]+\.amazonaws\.com/Prod/",
    re.IGNORECASE,
)
ASCII_PATTERN = re.compile(
    rb"https://[a-z0-9]{8,12}\.execute-api\.[a-z0-9-]+\.amazonaws\.com/Prod/",
    re.IGNORECASE,
)
UTF16_STRING = re.compile(rb"(?:[\x20-\x7e]\x00){20,}")


class PatchError(RuntimeError):
    """El binario no se puede parchear de forma segura."""


def _write_atomic(path, data):
    """Sustituye un binario sin dejarlo a medias si falla la escritura."""
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _find_urls(data):
    """Devuelve los huecos ASCII/UTF-16 sin asumir alineacion del binario."""
    hits = [
        ("ascii", m.start(), m.end(), m.group().decode("ascii"), "latin1", b"\x00")
        for m in ASCII_PATTERN.finditer(data)
    ]
    for block in UTF16_STRING.finditer(data):
        text = block.group().decode("utf-16le")
        for match in PATTERN.finditer(text):
            hits.append(
                (
                    "utf-16",
                    block.start() + match.start() * 2,
                    block.start() + match.end() * 2,
                    match.group(),
                    "utf-16le",
                    b"\x00\x00",
                )
            )
    return hits


def patch(path, new_url):
    path = Path(path)
    if not path.is_file():
        raise PatchError(f"Executable not found: {path}")
    if not new_url.startswith("http://") or not new_url.endswith("/"):
        raise PatchError("The URL must use http:// and end with /")

    original = path.with_suffix(path.suffix + ".orig")
    current_data = path.read_bytes()
    if _find_urls(current_data):
        # Si Steam revalida o actualiza el juego, el ejecutable oficial nuevo
        # debe reemplazar al .orig viejo. De lo contrario re-aplicar el parche
        # haria un downgrade silencioso.
        had_original = original.exists()
        refresh = not had_original or original.read_bytes() != current_data
        if refresh:
            _write_atomic(original, current_data)
            shutil.copystat(path, original)
            action = "base actualizada" if had_original else "copia de seguridad"
            print(f"  {action} -> {original.name}")

    if not original.exists():
        raise PatchError(
            f"{path.name} ya no contiene las URLs originales y no existe {original.name}. "
            "Verifica los archivos del juego en Steam."
        )

    # Partimos siempre del binario intacto para que el parche sea idempotente.
    data = bytearray(original.read_bytes())

    # Buscar sobre bytes conserva la alineacion real. Decodificar el .exe
    # entero como UTF-16 falla si una cadena empieza en un offset impar.
    hits = _find_urls(data)

    replaced = 0
    grouped = {}
    for label, start, end, url, codec, terminator in hits:
        needle = bytes(data[start:end]) + terminator
        encoded_url = new_url.encode(codec)
        # ljust() NO acorta: la version anterior agrandaba silenciosamente
        # el .exe cuando la URL nueva era demasiado larga y desplazaba todo
        # el binario. Debe quedar ademas al menos un terminador NUL.
        if len(encoded_url) + len(terminator) > len(needle):
            limit = (len(needle) - len(terminator)) // (2 if codec == "utf-16le" else 1)
            raise PatchError(
                f"URL demasiado larga para {path.name}: {len(new_url)} caracteres "
                f"(maximo {limit})"
            )
        blob = (encoded_url + terminator).ljust(len(needle), b"\x00")
        # El regex no incluye el NUL; exigimos que el hueco lo tenga.
        if bytes(data[end : end + len(terminator)]) != terminator:
            continue
        data[start : end + len(terminator)] = blob
        replaced += 1
        grouped[(label, url)] = grouped.get((label, url), 0) + 1

    for (label, url), count in grouped.items():
        print(f"  [{label}] {url}  ({count}x)")

    if not replaced:
        # Si hay backup, puede que el fichero ya estuviera parcheado. Siempre
        # partimos del backup; que este tampoco contenga URLs originales indica
        # un backup invalido y no debemos sobrescribir nada.
        raise PatchError(
            f"No original URLs were found in {original}. "
            "Revalida el juego en Steam y elimina solo el .orig defectuoso."
        )
    if len(data) != original.stat().st_size:
        raise PatchError("The patch would change the executable size; cancelled")
    _write_atomic(path, bytes(data))
    print(f"  => {replaced} URL(s) redirigidas a {new_url}\n")
    return replaced


def restore(path):
    path = Path(path)
    original = path.with_suffix(path.suffix + ".orig")
    if original.exists():
        _write_atomic(path, original.read_bytes())
        print(f"  restaurado desde {original.name}")
        return True
    else:
        print("  !! no hay copia .orig")
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--url",
        default="http://127.0.0.1:8080/",
        help="URL base del backend local (debe acabar en /)",
    )
    ap.add_argument("--restore", action="store_true")
    opts = ap.parse_args()

    if not opts.url.endswith("/"):
        opts.url += "/"

    for path in TARGETS:
        print(path.name)
        if not path.exists():
            print("  !! no encontrado\n")
            continue
        if opts.restore:
            restore(path)
        else:
            patch(path, opts.url)


if __name__ == "__main__":
    main()
