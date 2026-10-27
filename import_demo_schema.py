
import getpass
from pathlib import Path
import mysql.connector

HOST = "mysql-1348b406-priyankacm26-182f.b.aivencloud.com"
PORT = 14906
DATABASE = "recruitment_demo"
USERNAME = "recruitment_demo_user"
CA_FILE = r"C:\Users\priya\Downloads\ca.pem"

schema_file = Path("sql/schema_demo.sql")

if not schema_file.is_file():
    raise SystemExit(f"Schema file not found: {schema_file}")

password = getpass.getpass("Aiven demo database password (hidden): ")

connection = None
cursor = None

try:
    connection = mysql.connector.connect(
        host=HOST,
        port=PORT,
        user=USERNAME,
        password=password,
        database=DATABASE,
        ssl_ca=CA_FILE,
        ssl_verify_cert=True,
        ssl_verify_identity=True,
        connection_timeout=15,
    )

    cursor = connection.cursor()

    sql_text = schema_file.read_text(encoding="utf-8")
    statements = [
        statement.strip()
        for statement in sql_text.split(";")
        if statement.strip()
    ]

    for statement in statements:
        cursor.execute(statement)

    connection.commit()

    cursor.execute("SHOW TABLES")
    tables = [row[0] for row in cursor.fetchall()]

    expected = {
        "candidates",
        "jobs",
        "candidate_jobs",
        "email_ingestion_logs",
        "chat_messages",
    }

    print("\nTables currently in recruitment_demo:")
    for table in tables:
        print(" -", table)

    missing = expected - set(tables)

    if missing:
        print("\nSome expected tables are missing:", sorted(missing))
    else:
        print("\nSUCCESS: All five demo tables are present.")

except Exception as exc:
    if connection is not None:
        connection.rollback()
    print("\nImport failed:", type(exc).__name__)
    print("Details:", str(exc))
    print("Check the schema file, database permissions, and CA certificate.")

finally:
    if cursor is not None:
        cursor.close()
    if connection is not None and connection.is_connected():
        connection.close()
