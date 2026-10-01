import logging
import uuid
import datetime
from typing import Any, Dict, List, Optional

from core.simulation_accounts import demo_password, hash_password, is_hashed
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None
    RealDictCursor = None

log = logging.getLogger(__name__)

INITIAL_ACCOUNTS = [
    {
        "email": "normal1@novatrust.com",
        "password": demo_password("NOVATRUST_DEMO_PASSWORD_ALICE"),
        "user_id": "alice",
        "display_name": "Alice Johnson",
        "account_masked": "****4521",
        "balance": 12450.00,
    },
    {
        "email": "normal2@novatrust.com",
        "password": demo_password("NOVATRUST_DEMO_PASSWORD_BOB"),
        "user_id": "bob",
        "display_name": "Bob Carter",
        "account_masked": "****8314",
        "balance": 9820.42,
    },
    {
        "email": "admin@novatrust.com",
        "password": demo_password("NOVATRUST_DEMO_PASSWORD_CAROL"),
        "user_id": "carol",
        "display_name": "Carol Admin",
        "account_masked": "****1108",
        "balance": 50124.77,
    },
]

class NovaTrustRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def _connect(self):
        if not self.database_url or psycopg2 is None:
            return None
        conn = psycopg2.connect(
            self.database_url,
            cursor_factory=RealDictCursor,
            connect_timeout=5,
        )
        return conn

    def bootstrap(self) -> None:
        conn = self._connect()
        if not conn:
            return
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS novatrust_accounts (
                        email VARCHAR(255) PRIMARY KEY,
                        password VARCHAR(255) NOT NULL,
                        user_id VARCHAR(255) NOT NULL,
                        display_name VARCHAR(255) NOT NULL,
                        account_masked VARCHAR(255) NOT NULL,
                        balance DECIMAL(15, 2) NOT NULL
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS novatrust_transactions (
                        id VARCHAR(255) PRIMARY KEY,
                        user_id VARCHAR(255) NOT NULL,
                        date TIMESTAMP NOT NULL,
                        description VARCHAR(255) NOT NULL,
                        amount DECIMAL(15, 2) NOT NULL
                    )
                """)
                
                # Upgrade accounts written before passwords were hashed.
                cur.execute("SELECT email, password FROM novatrust_accounts")
                for row in cur.fetchall():
                    if not is_hashed(row["password"]):
                        cur.execute("UPDATE novatrust_accounts SET password = %s WHERE email = %s", (hash_password(row["password"]), row["email"]))

                # Check if empty
                cur.execute("SELECT COUNT(*) as count FROM novatrust_accounts")
                if cur.fetchone()["count"] == 0:
                    for acc in INITIAL_ACCOUNTS:
                        cur.execute("""
                            INSERT INTO novatrust_accounts (email, password, user_id, display_name, account_masked, balance)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """, (acc["email"], hash_password(acc["password"]), acc["user_id"], acc["display_name"], acc["account_masked"], acc["balance"]))
                        
                        # Generate some dummy transactions for this user
                        for i in range(5):
                            amount = -15.00 if i % 2 == 0 else 500.00
                            cur.execute("""
                                INSERT INTO novatrust_transactions (id, user_id, date, description, amount)
                                VALUES (%s, %s, %s, %s, %s)
                            """, (
                                f"tx-{acc['user_id']}-{i}", 
                                acc["user_id"], 
                                datetime.datetime.utcnow() - datetime.timedelta(days=i), 
                                "Grocery Store" if amount < 0 else "Payroll", 
                                amount
                            ))

    def get_account(self, email: str) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        if not conn:
            return None
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM novatrust_accounts WHERE email = %s", (email,))
                row = cur.fetchone()
                if row:
                    row["balance"] = float(row["balance"])
                return row

    def get_account_by_user_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        if not conn:
            return None
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM novatrust_accounts WHERE user_id = %s", (user_id,))
                row = cur.fetchone()
                if row:
                    row["balance"] = float(row["balance"])
                return row

    def get_transactions(self, user_id: str) -> List[Dict[str, Any]]:
        conn = self._connect()
        if not conn:
            return []
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM novatrust_transactions WHERE user_id = %s ORDER BY date DESC", (user_id,))
                rows = cur.fetchall()
                for row in rows:
                    row["amount"] = float(row["amount"])
                    row["date"] = row["date"].strftime("%b %d, %Y")
                    row["type"] = "credit" if row["amount"] > 0 else "debit"
                return rows

    def record_transfer(self, user_id: str, amount: float, destination: str, memo: Optional[str]) -> None:
        conn = self._connect()
        if not conn:
            return
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO novatrust_transactions (id, user_id, date, description, amount)
                    VALUES (%s, %s, %s, %s, %s)
                """, (
                    f"tx-real-{uuid.uuid4().hex[:8]}",
                    user_id,
                    datetime.datetime.utcnow(),
                    f"Transfer to {destination}",
                    -amount
                ))
                cur.execute("""
                    UPDATE novatrust_accounts SET balance = balance - %s WHERE user_id = %s
                """, (amount, user_id))
