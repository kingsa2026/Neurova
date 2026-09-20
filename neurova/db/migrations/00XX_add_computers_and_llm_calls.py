"""
Migration: Add computers table and llm_calls ledger
"""

from sqlalchemy import create_table, MetaData, Column, String, Integer, Float, DateTime, UUID, JSON, Boolean, Text

def upgrade(engine):
    """Upgrade database schema"""
    metadata = MetaData()
    metadata.reflect(bind=engine)

    # Create computers table
    if 'computers' not in metadata.tables:
        create_table(
            'computers',
            metadata,
            Column('computer_id', String, primary_key=True),
            Column('name', String, nullable=False),
            Column('kind', String, nullable=False),  # cloud/local/vps
            Column('engine', String, nullable=False),  # managed/claude/codex/etc
            Column('status', String, nullable=False),  # online/offline/busy
            Column('last_seen_at', DateTime),
            Column('owner_user_id', String, index=True),
            Column('company_id', String, index=True),
            Column('agents', JSON),  # {agent_id: agent_data}
            Column('daemon_token', String),
            Column('daemon_version', String),
            Column('paired_at', DateTime),
            Column('revoked_at', DateTime),
            Column('credential_hash', String),
            Column('metadata', JSON),
            Column('created_at', DateTime, nullable=False),
            Column('updated_at', DateTime, nullable=False),
        )
        print("Created computers table")

    # Create llm_calls table
    if 'llm_calls' not in metadata.tables:
        create_table(
            'llm_calls',
            metadata,
            Column('call_id', String, primary_key=True),
            Column('agent_id', String, nullable=False, index=True),
            Column('turn_id', String, index=True),
            Column('session_id', String),
            Column('provider', String, nullable=False),
            Column('model', String, nullable=False),
            Column('direction', String, nullable=False),
            Column('input_tokens', Integer, nullable=False, default=0),
            Column('output_tokens', Integer, default=0),
            Column('cache_read_tokens', Integer, default=0),
            Column('cache_write_tokens', Integer, default=0),
            Column('cost_usd', Float, nullable=False),
            Column('called_at', DateTime, nullable=False, index=True),
        )

        # Create indexes for performance
        with engine.connect() as conn:
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_llm_calls_agent
                ON llm_calls(agent_id, called_at)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_llm_calls_company
                ON llm_calls USING GIN (
                    SELECT agent_id, company_id FROM agents WHERE id = llm_calls.agent_id
                )
            """)

        print("Created llm_calls table")

    # Create llm_calls_rollup table for performance
    if 'llm_calls_rollup' not in metadata.tables:
        create_table(
            'llm_calls_rollup',
            metadata,
            Column('agent_id', String, primary_key=True),
            Column('hour', DateTime, nullable=False),
            Column('provider', String),
            Column('model', String),
            Column('total_input', Integer, default=0),
            Column('total_output', Integer, default=0),
            Column('total_cost', Float, default=0),
        )

        with engine.connect() as conn:
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_llm_rollup_hour
                ON llm_calls_rollup(hour DESC)
            """)

        print("Created llm_calls_rollup table")

    print("Database upgrade completed successfully")

def downgrade(engine):
    """Downgrade database schema"""
    metadata = MetaData()
    metadata.reflect(bind=engine)

    # Drop tables in reverse order
    tables = [
        metadata.tables.get('llm_calls_rollup'),
        metadata.tables.get('llm_calls'),
        metadata.tables.get('computers'),
    ]

    for table in tables:
        if table and table.name in metadata.tables:
            table.drop(checkfirst=True)
            print(f"Dropped table: {table.name}")

    print("Database downgrade completed successfully")

if __name__ == "__main__":
    from sqlalchemy import create_engine

    # Local testing
    engine = create_engine("sqlite:///neurova_memory.db")
    upgrade(engine)
