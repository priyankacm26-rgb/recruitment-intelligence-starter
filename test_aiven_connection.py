
import getpass
import os
import mysql.connector

host = input("Aiven MySQL hostname: ").strip()
port = int(input("Aiven MySQL port [14906]: ").strip() or "14906")
user = input("Aiven MySQL username [recruitment_demo_user]: ").strip()
user = user or "recruitment_demo_user"
password = getpass.getpass("Aiven MySQL password (hidden): ")
ca_path = input(
    "CA certificate path [C:\\Users\\priya\\Downloads\\ca.pem]: "
).strip().strip('"')
ca_path = ca_path or r"C:\Users\priya\Downloads\ca.pem"

try:
    connection = mysql.connector.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database="recruitment_demo",
        ssl_ca=ca_path,
        ssl_verify_cert=True,
        ssl_verify_identity=True,
        connection_timeout=15,
    )

    cursor = connection.cursor()
    cursor.execute("SELECT DATABASE(), VERSION()")
    database, version = cursor.fetchone()

    print("\nConnection successful!")
    print("Connected database:", database)
    print("MySQL version:", version)

    cursor.close()
    connection.close()

except Exception as exc:
    print("\nConnection failed:", type(exc).__name__)
    print("Details:", str(exc))
    print("Check the hostname, port, username, password, CA path,")
    print("and the user's permission to access recruitment_demo.")
