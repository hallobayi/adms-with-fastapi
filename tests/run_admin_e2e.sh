#!/usr/bin/env bash
# Verifikasi dashboard admin terhadap instance MySQL sementara.
#
# Kenapa dibungkus skrip: proses latar belakang (mysqld) dimatikan di antara
# pemanggilan perintah di lingkungan kerja ini, jadi seluruh siklus hidup —
# nyalakan, migrasi, seed, uji, matikan — harus berjalan dalam satu proses.
#
# Instance memakai port terpisah dan `--no-defaults` supaya TIDAK menyentuh
# MySQL milik pengguna (biasanya di 3306). Data di dalamnya sekali pakai.
#
# Pemakaian:
#   bash tests/run_admin_e2e.sh
#
# Kode keluar 0 bila seluruh pemeriksaan lulus.

set -u

MYSQL_BIN="${MYSQL_BIN:-C:/laragon/bin/mysql/mysql-8.0.15-winx64/bin}"
MYSQL_BASE="${MYSQL_BASE:-C:/laragon/bin/mysql/mysql-8.0.15-winx64}"
PORT="${VERIFY_PORT:-3399}"
DB="${VERIFY_DB:-adms}"
DBUSER="${VERIFY_USER:-vuser}"
DBPASS="${VERIFY_PASSWORD:-vsecret}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMPDB="${TMPDIR:-C:/Users/asus/AppData/Local/Temp}/adms_verify_$$"

# `basedir` harus ditulis eksplisit. Menurunkannya dari `$MYSQL_BIN/..` pernah
# salah: PATH berisi 8.0.15, tetapi `..` dari bin-nya menunjuk instalasi lain
# (5.7.24), dan 5.7 menolak `--mysqlx` sehingga server gagal start.
export PATH="$MYSQL_BIN:$PATH"

MY="mysql -h 127.0.0.1 -P $PORT --protocol=TCP"

cleanup() {
  mysqladmin -h 127.0.0.1 -P "$PORT" -u root --protocol=TCP shutdown >/dev/null 2>&1
  sleep 2
  rm -rf "$TMPDB"
}
trap cleanup EXIT

echo "== 1. Menyalakan MySQL sementara di port $PORT =="
mkdir -p "$TMPDB/data"
mysqld --initialize-insecure --datadir="$TMPDB/data" --basedir="$MYSQL_BASE" >/dev/null 2>&1
mysqld --no-defaults --datadir="$TMPDB/data" --basedir="$MYSQL_BASE" \
  --port="$PORT" --bind-address=127.0.0.1 --console \
  >"$TMPDB/server.log" 2>&1 &

for i in $(seq 1 40); do
  $MY -u root -e "SELECT 1" >/dev/null 2>&1 && { echo "   siap setelah ${i}s"; break; }
  sleep 1
done
$MY -u root -e "SELECT 1" >/dev/null 2>&1 || { echo "GAGAL: MySQL tidak siap"; cat "$TMPDB/server.log"; exit 1; }

echo "== 2. Migrasi =="
$MY -u root -e "CREATE DATABASE $DB CHARACTER SET utf8mb4;"
for f in "$ROOT"/migrations/0*.sql; do
  $MY -u root "$DB" < "$f" || { echo "GAGAL migrasi: $f"; exit 1; }
  echo "   ok: $(basename "$f")"
done
TABLES=$($MY -u root "$DB" -N -e \
  "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='$DB';")
echo "   tabel: $TABLES (harapan 15)"
[ "$TABLES" = "15" ] || { echo "GAGAL: jumlah tabel tidak sesuai"; exit 1; }

echo "== 3. Akun & data contoh =="
$MY -u root -e "
CREATE USER IF NOT EXISTS '$DBUSER'@'%' IDENTIFIED BY '$DBPASS';
GRANT ALL PRIVILEGES ON $DB.* TO '$DBUSER'@'%';
FLUSH PRIVILEGES;"
$MY -u root "$DB" < "$ROOT/tests/seed_admin_e2e.sql" || { echo "GAGAL seed"; exit 1; }
echo "   ok"

echo "== 4. Menjalankan harness =="
cd "$ROOT"
PYTHONPATH="$ROOT" \
VERIFY_HOST=127.0.0.1 VERIFY_PORT="$PORT" VERIFY_DB="$DB" \
VERIFY_USER="$DBUSER" VERIFY_PASSWORD="$DBPASS" \
  "${PYTHON:-python}" tests/verify_admin_e2e.py
STATUS=$?

echo "== 5. Membersihkan =="
cleanup
trap - EXIT
echo "   temp dihapus"
exit $STATUS
