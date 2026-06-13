from neurova.core.connection_pool import SQLiteConnectionPool, get_connection_pool
from neurova.core.database import database_connection, get_db_conn

# Test connection pool
print('=== Connection Pool Test ===')

# Create a pool
pool = get_connection_pool('neurova_memory.db', max_connections=3)
print(f'Pool created: {pool.db_path}')

# Get and return connections
conn1 = pool.get_connection()
print(f'Got connection 1: {conn1}')
print(f'Pool size: {pool.pool_size}, Active: {pool.active_count}')

conn2 = pool.get_connection()
print(f'Got connection 2: {conn2}')
print(f'Pool size: {pool.pool_size}, Active: {pool.active_count}')

# Return connections
pool.return_connection(conn1)
print(f'Returned connection 1')
print(f'Pool size: {pool.pool_size}, Active: {pool.active_count}')

pool.return_connection(conn2)
print(f'Returned connection 2')
print(f'Pool size: {pool.pool_size}, Active: {pool.active_count}')

# Test context manager
print('\n=== Context Manager Test ===')
with database_connection('neurova_memory.db') as conn:
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print(f'Tables: {[t[0] for t in tables]}')

print('\nAll tests passed!')
