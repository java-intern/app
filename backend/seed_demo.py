import sqlite3
import uuid
import os
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

def hash_pw(pw: str) -> str:
    salt = os.urandom(16)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=600000
    )
    key = kdf.derive(pw.encode('utf-8'))
    return f"{salt.hex()}:{key.hex()}"

db_path = os.path.join(os.path.dirname(__file__), "adaptivetrust.db")
conn = sqlite3.connect(db_path)
c = conn.cursor()

# Ensure default company
c.execute("SELECT id FROM companies WHERE company_code='ACME1234'")
comp = c.fetchone()
if not comp:
    comp_id = str(uuid.uuid4())
    c.execute("INSERT INTO companies (id, name, company_code, is_active, created_at) VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)", (comp_id, 'Acme Corp', 'ACME1234'))
else:
    comp_id = comp[0]

pw_hash = hash_pw('Password123!')

# 1. Admin Account
c.execute("SELECT id FROM users WHERE email='admin@secure.com'")
admin = c.fetchone()
if not admin:
    c.execute("INSERT INTO users (id, company_id, email, hashed_password, role, full_name, is_active, current_score, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 1, 100, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)", (str(uuid.uuid4()), comp_id, 'admin@secure.com', pw_hash, 'ADMIN', 'John Admin'))
else:
    c.execute("UPDATE users SET hashed_password=? WHERE email='admin@secure.com'", (pw_hash,))

# 2. Employee Account
c.execute("SELECT id FROM users WHERE email='alice@company.com'")
emp = c.fetchone()
if not emp:
    emp_id = str(uuid.uuid4())
    c.execute("INSERT INTO users (id, company_id, email, hashed_password, role, full_name, is_active, current_score, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 1, 95, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)", (emp_id, comp_id, 'alice@company.com', pw_hash, 'EMPLOYEE', 'Alice Worker'))
    c.execute("INSERT INTO trust_logs (id, company_id, user_id, score_before, score_after, cause_of_change, created_at) VALUES (?, ?, ?, 100, 95, 'Baseline trust initialization', CURRENT_TIMESTAMP)", (str(uuid.uuid4()), comp_id, emp_id))
else:
    c.execute("UPDATE users SET hashed_password=? WHERE email='alice@company.com'", (pw_hash,))

conn.commit()
conn.close()
print("SUCCESS: Seeded default admin@secure.com and alice@company.com with password Password123!")
