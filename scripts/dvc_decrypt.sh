#!/usr/bin/env bash
#
# dvc_decrypt_all.sh
#
# Descifra todos los archivos .age encontrados dentro de data/,
# usando la llave privada del equipo después de `dvc pull`.
#
# Uso:
#   ./scripts/dvc_decrypt_all.sh
#
# Requiere que la variable de entorno AGE_KEY_FILE apunte a la llave
# privada del equipo, o que exista en .age/key.txt (NUNCA se sube a Git).
#
set -e

KEY_FILE="${AGE_KEY_FILE:-.age/key.txt}"

if [ ! -f "$KEY_FILE" ]; then
  echo "ERROR: No se encontró la llave privada en '$KEY_FILE'."
  echo "Pide la llave del equipo por un canal seguro y colócala en .age/."
  exit 1
fi

if ! command -v age &> /dev/null; then
  echo "ERROR: 'age' no está instalado."
  exit 1
fi

COUNT=0

## Busca todos los .age dentro de data/ (raw y processed)
while IFS= read -r -d '' ENCRYPTED_FILE; do
  DECRYPTED_FILE="${ENCRYPTED_FILE%.age}"
  echo "Descifrando '$ENCRYPTED_FILE' -> '$DECRYPTED_FILE'..."
  age -d -i "$KEY_FILE" -o "$DECRYPTED_FILE" "$ENCRYPTED_FILE"
  COUNT=$((COUNT + 1))
done < <(find data -type f -name "*.age" -print0)

if [ "$COUNT" -eq 0 ]; then
  echo "No se encontraron archivos .age en data/."
else
  echo ""
  echo "$COUNT archivo(s) descifrado(s) correctamente."
fi
