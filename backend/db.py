import os
import mysql.connector
from dotenv import load_dotenv
load_dotenv()
def connect():
    return mysql.connector.connect(host=os.getenv('MYSQL_HOST','127.0.0.1'), port=int(os.getenv('MYSQL_PORT','3306')),
      user=os.getenv('MYSQL_USER','root'), password=os.getenv('MYSQL_PASSWORD',''),
      database=os.getenv('MYSQL_DATABASE','recruitment_intelligence_dev'), autocommit=False)
